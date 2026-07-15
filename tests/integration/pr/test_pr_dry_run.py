from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_pr_dry_run(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir,
    worktrees_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    # Avoid requiring the real GitHub CLI in integration tests.
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "env"]).exit_code == 0

    result = runner.invoke(app, ["pr", "env", "--title", "test: pr {repo}", "--dry-run"])
    assert result.exit_code == 0
