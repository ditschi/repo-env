"""Tests for ``repoenv.__main__.main`` -- the last line of defense against raw tracebacks."""

from __future__ import annotations

import pytest

from repoenv import __main__ as entrypoint
from repoenv.errors import ExitCode, UsageError


def test_debug_requested_via_flag() -> None:
    assert entrypoint._debug_requested(["ls", "--debug"]) is True
    assert entrypoint._debug_requested(["ls"]) is False


def test_debug_requested_via_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOENV_DEBUG", "1")
    assert entrypoint._debug_requested(["ls"]) is True


def test_repoenv_error_prints_friendly_message_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["renv", "ls"])

    def _boom() -> None:
        raise UsageError("boom", hint="try again")

    monkeypatch.setattr(entrypoint, "app", _boom)

    printed: list[str] = []
    monkeypatch.setattr(entrypoint.console, "print_error", lambda error: printed.append(error.message))

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == int(ExitCode.USAGE)
    assert printed == ["boom"]


def test_repoenv_error_reraises_with_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["renv", "ls", "--debug"])

    def _boom() -> None:
        raise UsageError("boom")

    monkeypatch.setattr(entrypoint, "app", _boom)

    with pytest.raises(UsageError):
        entrypoint.main()


def test_unexpected_exception_is_hidden_without_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["renv", "ls"])

    def _boom() -> None:
        raise RuntimeError("totally unexpected")

    monkeypatch.setattr(entrypoint, "app", _boom)

    printed: list[str] = []
    monkeypatch.setattr(entrypoint.console, "print_fatal", lambda message: printed.append(message))

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == int(ExitCode.GENERIC)
    assert printed == ["totally unexpected"]


def test_unexpected_exception_reraises_with_debug_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["renv", "ls"])
    monkeypatch.setenv("REPOENV_DEBUG", "1")

    def _boom() -> None:
        raise RuntimeError("totally unexpected")

    monkeypatch.setattr(entrypoint, "app", _boom)

    with pytest.raises(RuntimeError):
        entrypoint.main()


def test_keyboard_interrupt_exits_130_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["renv", "ls"])

    def _boom() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "app", _boom)

    with pytest.raises(SystemExit) as exc:
        entrypoint.main()

    assert exc.value.code == 130
