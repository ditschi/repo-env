"""Real (non-mocked) coverage for sync/prune/rm --force.

The existing unit tests for these commands mock the underlying git-touching
service function (e.g. ``lifecycle_service.sync_environment`` returns a
canned failure list), so they only prove the CLI wiring, not that the actual
git operations behave correctly against real worktrees.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv


def test_sync_fetches_remote_without_touching_worktree(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    alpha = repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--branch", "feature/x", "--include", "alpha"]).exit_code == 0

    wt = worktrees_dir / "web" / "alpha"
    (wt / "local-change.txt").write_text("uncommitted\n", encoding="utf-8")

    # A colleague pushes new work to the shared remote after we cloned.
    other_clone = source_dir.parent / "other-clone"
    run_git(
        ["clone", "-q", str(alpha.parent.parent / "remotes" / "alpha.git"), str(other_clone)],
        cwd=source_dir.parent,
    )
    run_git(["config", "user.email", "other@example.com"], cwd=other_clone)
    run_git(["config", "user.name", "Other"], cwd=other_clone)
    (other_clone / "new-file.txt").write_text("from colleague\n", encoding="utf-8")
    run_git(["add", "-A"], cwd=other_clone)
    run_git(["commit", "-q", "-m", "colleague change"], cwd=other_clone)
    run_git(["push", "-q", "origin", "HEAD:main"], cwd=other_clone)

    before = run_git(["rev-parse", "origin/main"], cwd=alpha).stdout.strip()
    result = runner.invoke(app, ["sync", "web"])
    assert result.exit_code == 0, result.output
    after = run_git(["rev-parse", "origin/main"], cwd=alpha).stdout.strip()

    assert before != after, "origin/main should have advanced after sync"
    # sync only fetches; it must not touch the worktree's own branch or files.
    assert (wt / "local-change.txt").exists()
    assert run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt).stdout.strip() == "feature/x"


def test_prune_clears_stale_worktree_metadata_after_manual_deletion(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha"]).exit_code == 0

    wt = worktrees_dir / "web" / "alpha"
    source_repo = source_dir / "alpha"

    listing_before = run_git(["worktree", "list", "--porcelain"], cwd=source_repo).stdout
    assert str(wt) in listing_before

    # Bypass renv entirely: delete the worktree directory by hand.
    import shutil

    shutil.rmtree(wt)

    result = runner.invoke(app, ["prune", "web"])
    assert result.exit_code == 0, result.output

    listing_after = run_git(["worktree", "list", "--porcelain"], cwd=source_repo).stdout
    assert str(wt) not in listing_after

    # With the stale metadata cleared, recreating no longer hits a conflict.
    recreate = runner.invoke(app, ["repair", "web"])
    assert recreate.exit_code == 0, recreate.output
    assert wt.exists()


def test_rm_refuses_real_dirty_worktree_then_force_removes_it(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha"]).exit_code == 0

    wt = worktrees_dir / "web" / "alpha"
    (wt / "README.md").write_text("uncommitted edit\n", encoding="utf-8")

    refused = runner.invoke(app, ["rm", "web"])
    assert refused.exit_code != 0
    assert wt.exists()

    forced = runner.invoke(app, ["rm", "web", "--force", "--delete-files"])
    assert forced.exit_code == 0, forced.output
    assert not wt.exists()
