"""Real (non-mocked) coverage for sync/prune/rm --force.

The existing unit tests for these commands mock the underlying git-touching
service function (e.g. ``lifecycle_service.sync_environment`` returns a
canned failure list), so they only prove the CLI wiring, not that the actual
git operations behave correctly against real worktrees.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from repoenv.adapters import git_adapter
from tests.integration.support.gitfixtures import run_git, worktree_listing
from tests.integration.support.renv_helpers import Renv


def _push_colleague_commit(renv: Renv) -> None:
    """A colleague pushes new work to alpha's shared remote after we cloned."""
    other_clone = renv.repos.root / "other-clone"
    run_git(["clone", "-q", str(renv.repos.remotes / "alpha.git"), str(other_clone)], cwd=renv.repos.root)
    run_git(["config", "user.email", "other@example.com"], cwd=other_clone)
    run_git(["config", "user.name", "Other"], cwd=other_clone)
    (other_clone / "new-file.txt").write_text("from colleague\n", encoding="utf-8")
    run_git(["add", "-A"], cwd=other_clone)
    run_git(["commit", "-q", "-m", "colleague change"], cwd=other_clone)
    run_git(["push", "-q", "origin", "HEAD:main"], cwd=other_clone)


def _rev_parse(repo: Path, *args: str) -> str:
    return run_git(["rev-parse", *args], cwd=repo).stdout.strip()


def test_sync_fetches_remote_without_touching_worktree(renv: Renv) -> None:
    (alpha,) = renv.setup("alpha")
    renv.ok("create", "web", "--branch", "feature/x", "--include", "alpha")

    wt = renv.worktrees / "web" / "alpha"
    (wt / "local-change.txt").write_text("uncommitted\n", encoding="utf-8")
    _push_colleague_commit(renv)

    before = _rev_parse(alpha, "origin/main")
    renv.ok("sync", "web")
    after = _rev_parse(alpha, "origin/main")

    assert before != after, "origin/main should have advanced after sync"
    # sync only fetches; it must not touch the worktree's own branch or files.
    assert (wt / "local-change.txt").exists()
    assert _rev_parse(wt, "--abbrev-ref", "HEAD") == "feature/x"


def test_prune_clears_stale_worktree_metadata_after_manual_deletion(renv: Renv, web_env: Path) -> None:
    wt = web_env / "alpha"
    source_repo = renv.source / "alpha"
    assert str(wt) in worktree_listing(source_repo)

    # Bypass renv entirely: delete the worktree directory by hand.
    shutil.rmtree(wt)

    renv.ok("prune", "web")
    assert str(wt) not in worktree_listing(source_repo)

    # With the stale metadata cleared, recreating no longer hits a conflict.
    renv.ok("repair", "web")
    assert wt.exists()


def test_rm_refuses_real_dirty_worktree_then_force_removes_it(renv: Renv, web_env: Path) -> None:
    wt = web_env / "alpha"
    (wt / "README.md").write_text("uncommitted edit\n", encoding="utf-8")

    assert renv.invoke("rm", "web").exit_code != 0
    assert wt.exists()

    renv.ok("rm", "web", "--force")
    assert not wt.exists()


def test_rm_partial_with_delete_branches_real(renv: Renv) -> None:
    alpha, beta = renv.setup("alpha", "beta")
    renv.ok("create", "web", "-b", "task/x", "--include", "alpha", "--include", "beta")

    renv.ok("rm", "web", "-i", "beta", "--delete-branches")
    assert not (renv.worktrees / "web" / "beta").exists()
    assert (renv.worktrees / "web" / "alpha").exists()
    assert not git_adapter.branch_exists(beta, "task/x")
    assert git_adapter.branch_exists(alpha, "task/x")

    # Whole-env removal with --delete-branches cleans the rest.
    renv.ok("rm", "web", "--delete-branches")
    assert not git_adapter.branch_exists(alpha, "task/x")
