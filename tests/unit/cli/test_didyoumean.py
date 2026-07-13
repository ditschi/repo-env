"""Tests for git-like command typo suggestions."""

from __future__ import annotations

from typer.testing import CliRunner

from repoenv.cli.app import app


def test_unknown_command_suggests_closest_match() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["staus"])
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "Did you mean 'status'?" in str(result.exception)
