from __future__ import annotations

import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.cli.commands import select as select_module
from repoenv.domain.models import Environment
from repoenv.errors import UsageError


def _seed_environment(repoenv_home: Path, name: str = "demo") -> Environment:
    registry = state_store.Registry()
    env_path = repoenv_home / "envs" / name
    env_path.mkdir(parents=True)
    env = Environment(name=name, path=env_path, source=repoenv_home / "src")
    registry.add(env)
    state_store.save_registry(registry)
    return env


class _FakeConfirm:
    def __init__(self, answer: bool) -> None:
        self._answer = answer

    def unsafe_ask(self) -> bool:
        return self._answer


def test_select_requires_interactive_terminal(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["select"])
    assert isinstance(result.exception, UsageError)


def test_select_no_environments(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    select_module.select_command()

    assert "No environments yet" in capsys.readouterr().err


def test_select_dispatches_to_status(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    env = _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(select_module, "_ask_environment", lambda _envs: env.name)
    monkeypatch.setattr(select_module, "_ask_action", lambda: "status")

    select_module.select_command()

    assert f"Environment '{env.name}'" in capsys.readouterr().err


def test_select_dispatches_to_activate(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(select_module, "_ask_environment", lambda _envs: env.name)
    monkeypatch.setattr(select_module, "_ask_action", lambda: "activate")

    select_module.select_command()

    assert state_store.load_registry().get_active() == env.name


def test_select_dispatches_to_path(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    env = _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(select_module, "_ask_environment", lambda _envs: env.name)
    monkeypatch.setattr(select_module, "_ask_action", lambda: "path")

    select_module.select_command()

    assert capsys.readouterr().out.strip() == str(env.path)


def test_select_rm_confirmed_removes_environment(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(select_module, "_ask_environment", lambda _envs: env.name)
    monkeypatch.setattr(select_module, "_ask_action", lambda: "rm")
    monkeypatch.setattr("questionary.confirm", lambda *_a, **_k: _FakeConfirm(True))

    select_module.select_command()

    assert state_store.load_registry().get(env.name) is None


def test_select_rm_declined_keeps_environment(
    repoenv_home: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    env = _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(select_module, "_ask_environment", lambda _envs: env.name)
    monkeypatch.setattr(select_module, "_ask_action", lambda: "rm")
    monkeypatch.setattr("questionary.confirm", lambda *_a, **_k: _FakeConfirm(False))

    select_module.select_command()

    assert state_store.load_registry().get(env.name) is not None
    assert "Cancelled" in capsys.readouterr().err


def test_select_cancel_on_environment_prompt_aborts(
    repoenv_home: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _seed_environment(repoenv_home)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        select_module, "_ask_environment", lambda _envs: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    with pytest.raises(typer.Exit) as exc:
        select_module.select_command()

    assert exc.value.exit_code == 130
    assert "Cancelled" in capsys.readouterr().err


def test_ask_environment_returns_selected_name(monkeypatch: pytest.MonkeyPatch) -> None:
    import questionary

    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))

    class _FakeSelect:
        def unsafe_ask(self) -> str:
            return "demo"

    monkeypatch.setattr(questionary, "select", lambda *_a, **_k: _FakeSelect())

    assert select_module._ask_environment([env]) == "demo"


def test_ask_environment_none_answer_raises_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    import questionary

    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))

    class _FakeSelect:
        def unsafe_ask(self) -> None:
            return None

    monkeypatch.setattr(questionary, "select", lambda *_a, **_k: _FakeSelect())

    with pytest.raises(KeyboardInterrupt):
        select_module._ask_environment([env])


def test_ask_action_none_answer_raises_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    import questionary

    class _FakeSelect:
        def unsafe_ask(self) -> None:
            return None

    monkeypatch.setattr(questionary, "select", lambda *_a, **_k: _FakeSelect())

    with pytest.raises(KeyboardInterrupt):
        select_module._ask_action()
