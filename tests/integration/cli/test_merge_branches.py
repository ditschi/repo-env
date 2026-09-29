"""``renv merge`` must preserve each repo's own task branch.

Before this, ``build_merge_plan`` only combined repo *names*; the merged
environment's worktrees were always freshly created detached at the default
branch, silently dropping whatever branch each source environment was
actually working on.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_merge_union_preserves_each_sides_branch(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "left", "--branch", "feature/a", "--include", "alpha"]).exit_code == 0
    )
    assert (
        runner.invoke(app, ["create", "right", "--branch", "feature/b", "--include", "beta"]).exit_code == 0
    )

    merge = runner.invoke(app, ["merge", "merged", "left", "right", "--op", "union"])
    assert merge.exit_code == 0, merge.output

    assert RepoFactory.current_branch(worktrees_dir / "merged" / "alpha") == "feature/a"
    assert RepoFactory.current_branch(worktrees_dir / "merged" / "beta") == "feature/b"


def test_merge_intersect_conflicting_branch_prefers_left_and_reports(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "left", "--branch", "feature/left", "--include", "alpha"]).exit_code
        == 0
    )
    assert (
        runner.invoke(app, ["create", "right", "--branch", "feature/right", "--include", "alpha"]).exit_code
        == 0
    )

    merge = runner.invoke(app, ["merge", "merged", "left", "right", "--op", "intersect"])
    assert merge.exit_code == 0, merge.output
    assert "branch conflict" in merge.output
    assert "feature/left" in merge.output
    assert "feature/right" in merge.output

    assert RepoFactory.current_branch(worktrees_dir / "merged" / "alpha") == "feature/left"


def test_merge_moves_branch_out_of_the_source_environment(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    """Git allows one worktree per branch, so preserving the branch in ``merged``
    means the original environment's worktree loses it (goes detached)."""
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "left", "--branch", "feature/a", "--include", "alpha"]).exit_code == 0
    )
    repo_factory.make_bare_and_clone("beta")
    assert (
        runner.invoke(app, ["create", "right", "--branch", "feature/b", "--include", "beta"]).exit_code == 0
    )

    merge = runner.invoke(app, ["merge", "merged", "left", "right", "--op", "union"])
    assert merge.exit_code == 0, merge.output

    assert RepoFactory.current_branch(worktrees_dir / "merged" / "alpha") == "feature/a"
    assert RepoFactory.is_detached(worktrees_dir / "left" / "alpha") is True


def test_merge_does_not_carry_over_plain_detached_checkout(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    """A repo created without --branch (detached at default) has no 'task branch' to carry over."""
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "left", "--include", "alpha"]).exit_code == 0
    repo_factory.make_bare_and_clone("beta")
    assert (
        runner.invoke(app, ["create", "right", "--branch", "feature/b", "--include", "beta"]).exit_code == 0
    )

    merge = runner.invoke(app, ["merge", "merged", "left", "right", "--op", "union"])
    assert merge.exit_code == 0, merge.output
    assert "branch conflict" not in merge.output
    assert RepoFactory.is_detached(worktrees_dir / "merged" / "alpha") is True
    assert RepoFactory.current_branch(worktrees_dir / "merged" / "beta") == "feature/b"
