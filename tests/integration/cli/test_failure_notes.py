"""Per-repo failure reasons must be visible without passing ``--json``.

``RepoEntry.note`` already captures *why* a worktree failed (e.g. "could not
determine the default branch"), but ``create``/``add``'s human-readable error
summary and ``renv status``'s default output used to only say a repo
"failed" / was "MISSING" with no reason, so a real failure looked identical
to nothing having happened at all.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv


def test_create_failure_reason_shown_without_json(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    broken = repo_factory.make_bare_and_clone("broken")
    run_git(["remote", "remove", "origin"], cwd=broken)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "env", "--include", "broken"])

    assert result.exit_code != 0
    assert result.exception is not None
    assert "default branch" in getattr(result.exception, "message", str(result.exception))

    status = runner.invoke(app, ["status", "env"])
    assert "default branch" in status.output
