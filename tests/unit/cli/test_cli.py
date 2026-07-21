from __future__ import annotations

import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from repoenv.adapters import config_store, state_store
from repoenv.cli.app import app
from repoenv.cli.commands import init as init_module
from repoenv.domain.models import Environment


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "repo-env" in result.stdout


def test_short_help_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_ls_empty(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_ls_warns_for_stale_environment_path(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    stale_path = repoenv_home / "missing-env"
    env = Environment(name="stale", path=stale_path, source=repoenv_home / "src")
    registry.add(env)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "stale" in result.output
    assert "stale environment" in result.output
    assert "renv ls --reconcile" in result.output


def test_ls_reconcile_removes_stale_entries(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    stale = Environment(name="stale", path=repoenv_home / "missing", source=repoenv_home / "src")
    live_path = repoenv_home / "envs" / "live"
    live_path.mkdir(parents=True)
    live = Environment(name="live", path=live_path, source=repoenv_home / "src")
    registry.add(stale)
    registry.add(live)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["ls", "--reconcile"])
    assert result.exit_code == 0
    assert "removed stale environment" in result.output

    reloaded = state_store.load_registry()
    assert reloaded.get("stale") is None
    assert reloaded.get("live") is not None


def test_path_prints_stdout_only(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))
    registry.add(env)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["path", "demo"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "/tmp/demo"


def test_init_non_interactive(repoenv_home: Path) -> None:
    runner = CliRunner()
    source = repoenv_home / "src"
    dest = repoenv_home / "envs"
    result = runner.invoke(app, ["init", "-y", "--source", str(source), "--dest", str(dest)])
    assert result.exit_code == 0
    cfg = config_store.load_config()
    assert cfg.source == source
    assert cfg.dest == dest


def test_ask_path_uses_directory_completion(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyQuestion:
        def unsafe_ask(self) -> str:
            return "~/clones"

    def _fake_path(message: str, default: str, only_directories: bool):
        captured["message"] = message
        captured["default"] = default
        captured["only_directories"] = only_directories
        return _DummyQuestion()

    import questionary

    monkeypatch.setattr(questionary, "path", _fake_path)
    result = init_module._ask_path("Source directory of clones", Path("/tmp/default"))

    assert captured["message"] == "Source directory of clones:"
    assert captured["default"] == "/tmp/default"
    assert captured["only_directories"] is True
    assert result == Path("~/clones").expanduser()


def test_ask_path_uses_default_when_empty_answer(monkeypatch) -> None:
    default = Path("/tmp/default")

    class _DummyQuestion:
        def unsafe_ask(self):
            return ""

    def _fake_path(message: str, default: str, only_directories: bool):
        return _DummyQuestion()

    import questionary

    monkeypatch.setattr(questionary, "path", _fake_path)
    result = init_module._ask_path("Source directory of clones", default)

    assert result == default


def test_ask_path_none_answer_raises_keyboard_interrupt(monkeypatch) -> None:
    class _DummyQuestion:
        def unsafe_ask(self):
            return None

    def _fake_path(message: str, default: str, only_directories: bool):
        return _DummyQuestion()

    import questionary

    monkeypatch.setattr(questionary, "path", _fake_path)

    with pytest.raises(KeyboardInterrupt):
        init_module._ask_path("Source directory of clones", Path("/tmp/default"))


def test_init_interactive_prefills_from_existing_config(repoenv_home: Path, monkeypatch) -> None:
    existing_source = repoenv_home / "existing-src"
    existing_dest = repoenv_home / "existing-envs"
    config_store.save_config(
        config_store.UserConfig(source=existing_source, dest=existing_dest, default_branch="main")
    )

    asked_path_defaults: list[Path] = []
    asked_text_defaults: list[str] = []

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def _fake_ask_path(_prompt: str, default: Path) -> Path:
        asked_path_defaults.append(default)
        return default

    def _fake_ask_text(_prompt: str, default: str) -> str:
        asked_text_defaults.append(default)
        return default

    monkeypatch.setattr(init_module, "_ask_path", _fake_ask_path)
    monkeypatch.setattr(init_module, "_ask_text", _fake_ask_text)

    init_module.init_command(
        source=None,
        dest=None,
        default_branch=None,
        install_completion=False,
        yes=False,
    )

    assert asked_path_defaults == [existing_source, existing_dest]
    assert asked_text_defaults == ["main"]


def test_init_ctrl_c_aborts_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        init_module, "_ask_path", lambda _prompt, _default: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    save_called = False

    def _fake_save_config(_config):
        nonlocal save_called
        save_called = True
        return Path("/tmp/unused")

    monkeypatch.setattr(config_store, "save_config", _fake_save_config)

    with pytest.raises(typer.Exit) as exc:
        init_module.init_command(
            source=None,
            dest=None,
            default_branch=None,
            install_completion=False,
            yes=False,
        )

    assert exc.value.exit_code == 130
    assert save_called is False


def test_init_none_cancel_aborts_without_writing(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(init_module, "_ask_path", lambda _prompt, default: default)
    monkeypatch.setattr(
        init_module, "_ask_text", lambda _prompt, _default: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    save_called = False

    def _fake_save_config(_config):
        nonlocal save_called
        save_called = True
        return Path("/tmp/unused")

    monkeypatch.setattr(config_store, "save_config", _fake_save_config)

    with pytest.raises(typer.Exit) as exc:
        init_module.init_command(
            source=None,
            dest=None,
            default_branch=None,
            install_completion=False,
            yes=False,
        )

    assert exc.value.exit_code == 130
    assert save_called is False
