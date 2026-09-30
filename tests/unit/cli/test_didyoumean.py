"""Tests for git-like command typo suggestions."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from repoenv.errors import UsageError


def test_unknown_command_suggests_closest_match() -> None:
    """A typo of a state-changing command must not auto-run, only suggest."""
    runner = CliRunner()
    result = runner.invoke(app, ["creat"])
    assert result.exit_code != 0
    assert isinstance(result.exception, UsageError)
    assert "No such command 'creat'" in str(result.exception)
    assert "Did you mean 'create'?" in (result.exception.hint or "")


def test_safe_command_typo_autocorrects_immediately(repoenv_home: Path) -> None:
    """A typo of a read-only command (e.g. 'lss' -> 'ls') just runs -- no error."""
    runner = CliRunner()
    result = runner.invoke(app, ["lss"])
    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "Using read-only command 'ls'" in result.output


def test_mutating_command_typo_autocorrects_when_configured(repoenv_home: Path) -> None:
    """A state-changing command typo still auto-runs when the user opted in via config."""
    from repoenv.adapters import config_store

    config_store.save_config(config_store.UserConfig(autocorrect=0.0))

    runner = CliRunner()
    result = runner.invoke(app, ["creat"])
    assert result.exit_code != 0  # 'create' itself fails (missing NAME arg), not the typo
    assert not isinstance(result.exception, UsageError) or "No such command" not in str(result.exception)
