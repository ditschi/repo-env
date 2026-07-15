from __future__ import annotations

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv


def _seed_branch(repo_factory: RepoFactory, name: str, branch: str, extra_file: str) -> None:
    """Add ``branch`` (with an extra file) to the remote of ``name``."""
    clone = repo_factory.clone_path(name)
    repo_factory.create_local_branch(clone, branch)
    repo_factory.write_file(clone, extra_file, f"{branch}-only\n")
    repo_factory.commit_all(clone, f"{branch} work")
    run_git(["push", "origin", branch], cwd=clone)
    repo_factory.checkout_branch(clone, "main")


def test_multibranch_create_run_and_add(
    repo_factory: RepoFactory, repoenv_home, source_dir, worktrees_dir
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    _seed_branch(repo_factory, "alpha", "develop", "dev.txt")
    _seed_branch(repo_factory, "alpha", "release/1.0", "rel.txt")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    # One worktree per base branch, dirs + created branches postfixed by base.
    result = runner.invoke(
        app,
        ["create", "multi", "--include", "alpha", "--from", "main,develop", "-b", "feature/x"],
    )
    assert result.exit_code == 0, result.output

    main_wt = worktrees_dir / "multi" / "alpha-main"
    develop_wt = worktrees_dir / "multi" / "alpha-develop"
    assert (main_wt / ".git").exists()
    assert (develop_wt / ".git").exists()

    assert RepoFactory.current_branch(main_wt) == "feature/x-main"
    assert RepoFactory.current_branch(develop_wt) == "feature/x-develop"

    # Each branch is based on the correct source branch.
    assert not (main_wt / "dev.txt").exists()
    assert (develop_wt / "dev.txt").exists()

    # run fans out across every worktree (both branches of the same repo).
    run_result = runner.invoke(app, ["run", "multi", "--", "git", "rev-parse", "--abbrev-ref", "HEAD"])
    assert run_result.exit_code == 0, run_result.output
    assert "feature/x-main" in run_result.output
    assert "feature/x-develop" in run_result.output

    # add another branch-worktree of the same repo from a new base; dir postfixed.
    add_result = runner.invoke(
        app, ["add", "multi", "--include", "alpha", "--from", "release/1.0", "-b", "hotfix/y"]
    )
    assert add_result.exit_code == 0, add_result.output
    rel_wt = worktrees_dir / "multi" / "alpha-release-1.0"
    assert (rel_wt / ".git").exists()
    # Single --from => directory is postfixed (repo already present) but the
    # explicitly named branch is used as-is (no per-base postfix).
    assert RepoFactory.current_branch(rel_wt) == "hotfix/y"
