"""Helpers for driving the renv CLI in integration tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app


def init_renv(runner: CliRunner, *, source: Path, worktrees: Path) -> None:
    """Run ``renv init`` with the standard integration-test layout."""
    result = runner.invoke(
        app,
        ["init", "-y", "--source", str(source), "--dest", str(worktrees)],
    )
    assert result.exit_code == 0, result.output
