"""Tests for git-like command typo suggestions."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from repoenv.errors import UsageError


def test_safe_command_typo_autocorrects_immediately(repoenv_home: Path) -> None:
    """A typo of a read-only command (e.g. 'll' -> 'ls') just runs -- no error, no prompt."""
    runner = CliRunner()
    result = runner.invoke(app, ["ll"])
    assert result.exit_code == 0
    assert result.exception is None
    assert "Using read-only command 'ls'" in result.stderr


def test_mutating_command_typo_without_autocorrect_fails_cleanly(repoenv_home: Path) -> None:
    """A typo of a state-changing command must not auto-run, and must not crash with a traceback."""
    runner = CliRunner()
    result = runner.invoke(app, ["creat"])
    assert result.exit_code != 0
    assert isinstance(result.exception, UsageError)
    assert "No such command 'creat'" in str(result.exception)
    assert "Did you mean 'create'?" in (result.exception.hint or "")


def test_mutating_command_typo_autocorrects_when_configured(repoenv_home: Path) -> None:
    from repoenv.adapters import config_store

    config_store.save_config(config_store.UserConfig(autocorrect=0.0))

    runner = CliRunner()
    result = runner.invoke(app, ["repai"])
    # 'repair' fails for an unrelated reason (no environment to resolve), but it
    # must have actually been *run* -- not blocked by a "no such command" error.
    assert "No such command" not in (str(result.exception) if result.exception else "")


def test_unknown_command_with_no_close_match_raises_original_error() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["zzzzzzzzzz"])
    assert result.exit_code != 0
    assert "No such command" in result.output or "No such command" in str(result.exception)
