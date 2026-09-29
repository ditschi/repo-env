"""``renv add`` without ``--branch`` should join the environment's existing task branch.

Before this behavior, a repo added later to an environment created with
``--branch feature/x`` landed detached at the default branch instead of on
``feature/x`` unless the caller remembered to repeat ``--branch`` by hand.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_add_without_branch_reuses_environment_task_branch(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    branch = "feature/rollout"

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    create = runner.invoke(app, ["create", "task", "--branch", branch, "--include", "alpha"])
    assert create.exit_code == 0, create.output

    add = runner.invoke(app, ["add", "task", "--include", "beta"])
    assert add.exit_code == 0, add.output

    assert RepoFactory.current_branch(worktrees_dir / "task" / "beta") == branch


def test_add_explicit_branch_still_overrides_inference(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    create = runner.invoke(app, ["create", "task", "--branch", "feature/a", "--include", "alpha"])
    assert create.exit_code == 0, create.output

    add = runner.invoke(app, ["add", "task", "--include", "beta", "--branch", "feature/b"])
    assert add.exit_code == 0, add.output

    assert RepoFactory.current_branch(worktrees_dir / "task" / "beta") == "feature/b"
