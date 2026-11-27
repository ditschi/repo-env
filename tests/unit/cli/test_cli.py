from __future__ import annotations

import sys
from dataclasses import dataclass, field
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
    missing = [
        text for text in ("stale", "stale environment", "renv ls --reconcile") if text not in result.output
    ]
    assert not missing, result.output


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
    """Contract: `cd "$(renv path demo)"` relies on stdout holding only the path."""
    registry = state_store.Registry()
    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))
    registry.add(env)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["path", "demo"])
    assert result.exit_code == 0
    assert result.stdout.strip() == str(Path("/tmp/demo"))


def test_init_non_interactive(repoenv_home: Path) -> None:
    runner = CliRunner()
    source = repoenv_home / "src"
    dest = repoenv_home / "envs"
    result = runner.invoke(app, ["init", "-y", "--source", str(source), "--dest", str(dest)])
    assert result.exit_code == 0
    cfg = config_store.load_config()
    assert cfg.source == source
    assert cfg.dest == dest


@dataclass(frozen=True)
class _FakeQuestion:
    answer: str | None

    def unsafe_ask(self) -> str | None:
        return self.answer


def _patch_questionary_path(monkeypatch: pytest.MonkeyPatch, question: _FakeQuestion) -> dict[str, object]:
    """Make ``questionary.path`` return ``question``; returns the arguments it was called with."""
    import questionary

    captured: dict[str, object] = {}

    def _fake_path(message: str, default: str, only_directories: bool) -> _FakeQuestion:
        captured.update(message=message, default=default, only_directories=only_directories)
        return question

    monkeypatch.setattr(questionary, "path", _fake_path)
    return captured


def test_ask_path_uses_directory_completion(monkeypatch) -> None:
    captured = _patch_questionary_path(monkeypatch, _FakeQuestion("~/clones"))

    result = init_module._ask_path("Source directory of clones", Path("/tmp/default"))

    assert captured == {
        "message": "Source directory of clones:",
        "default": str(Path("/tmp/default")),
        "only_directories": True,
    }
    assert result == Path("~/clones").expanduser()


def test_ask_path_uses_default_when_empty_answer(monkeypatch) -> None:
    default = Path("/tmp/default")
    _patch_questionary_path(monkeypatch, _FakeQuestion(""))

    result = init_module._ask_path("Source directory of clones", default)

    assert result == default


def test_ask_path_none_answer_raises_keyboard_interrupt(monkeypatch) -> None:
    _patch_questionary_path(monkeypatch, _FakeQuestion(None))

    with pytest.raises(KeyboardInterrupt):
        init_module._ask_path("Source directory of clones", Path("/tmp/default"))


def _fake_interactive_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def _run_interactive_init() -> None:
    init_module.init_command(
        source=None,
        dest=None,
        default_branch=None,
        install_completion=False,
        yes=False,
    )


def _cancel_prompt(_prompt, _default):
    raise KeyboardInterrupt()


def _record_save_config(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Replace ``config_store.save_config``; returns the list of configs it was asked to save."""
    saved: list[object] = []

    def _fake_save_config(config):
        saved.append(config)
        return Path("/tmp/unused")

    monkeypatch.setattr(config_store, "save_config", _fake_save_config)
    return saved


@dataclass
class _AcceptDefaultPrompt:
    """Fake prompt that accepts its default and records every default it was offered."""

    asked: list[object] = field(default_factory=list)

    def __call__(self, _prompt: str, default: object) -> object:
        self.asked.append(default)
        return default


def test_init_interactive_prefills_from_existing_config(repoenv_home: Path, monkeypatch) -> None:
    existing_source = repoenv_home / "existing-src"
    existing_dest = repoenv_home / "existing-envs"
    config_store.save_config(
        config_store.UserConfig(source=existing_source, dest=existing_dest, default_branch="main")
    )

    ask_path = _AcceptDefaultPrompt()
    ask_text = _AcceptDefaultPrompt()

    _fake_interactive_terminal(monkeypatch)
    monkeypatch.setattr(init_module, "_ask_path", ask_path)
    monkeypatch.setattr(init_module, "_ask_text", ask_text)

    _run_interactive_init()

    assert ask_path.asked == [existing_source, existing_dest]
    assert ask_text.asked == ["main"]


def test_init_ctrl_c_aborts_without_writing(monkeypatch) -> None:
    _fake_interactive_terminal(monkeypatch)
    monkeypatch.setattr(init_module, "_ask_path", _cancel_prompt)
    saved = _record_save_config(monkeypatch)

    with pytest.raises(typer.Exit) as exc:
        _run_interactive_init()

    assert exc.value.exit_code == 130
    assert saved == []


def test_init_none_cancel_aborts_without_writing(monkeypatch) -> None:
    _fake_interactive_terminal(monkeypatch)
    monkeypatch.setattr(init_module, "_ask_path", lambda _prompt, default: default)
    monkeypatch.setattr(init_module, "_ask_text", _cancel_prompt)
    saved = _record_save_config(monkeypatch)

    with pytest.raises(typer.Exit) as exc:
        _run_interactive_init()

    assert exc.value.exit_code == 130
    assert saved == []
