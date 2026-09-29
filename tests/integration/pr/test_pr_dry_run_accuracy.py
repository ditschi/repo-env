"""``renv pr --dry-run`` must accurately preview what a real run would do.

Before this, dry-run printed the raw, unrendered {repo}/{branch}/{env}
template and ignored --include/--exclude entirely (always listing every repo
in the environment), so it could show repos that would never actually get a
PR, and never showed what the title/body would actually expand to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_pr_dry_run_renders_template_and_respects_include(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "env", "--branch", "feature/x"]).exit_code == 0

    result = runner.invoke(
        app,
        ["pr", "env", "--title", "Rollout {repo} on {branch}", "--include", "alpha", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "would create PRs for 1 repo(s)" in result.output
    assert "Rollout alpha on feature/x" in result.output
    assert "beta" not in result.output
    assert "{repo}" not in result.output
