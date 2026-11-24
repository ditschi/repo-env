"""Integration tests for --on-branch-conflict worktree handling."""

from __future__ import annotations

from pathlib import Path

from click.testing import Result

from repoenv.adapters import state_store
from repoenv.domain.models import RepoStatus
from tests.integration.support import gitfixtures
from tests.integration.support.renv_helpers import (
    Renv,
    assert_failed_with,
    create_batch_with_branch_conflict,
    env_meta,
)


def _create_feat_alpha(renv: Renv, *opts: str) -> Result:
    """``renv create feat --include alpha <opts>``; returns the result without checking it."""
    return renv.invoke("create", "feat", "--include", "alpha", *opts)


def _alpha_in_source_on(renv: Renv, branch: str) -> Path:
    """Clone ``alpha`` with ``branch`` checked out in the source clone, then init."""
    (clone,) = renv.setup("alpha")
    gitfixtures.checkout_branch_in_source(clone, branch)
    return clone


def test_create_no_conflict_new_branch(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    renv.ok("create", "feat", "--branch", "feature/new")
    alpha = renv.worktrees / "feat" / "alpha"
    assert (alpha / ".git").exists()
    assert gitfixtures.current_branch(alpha) == "feature/new"


def test_create_attaches_existing_unused_branch(renv: Renv) -> None:
    (clone,) = renv.setup("alpha")
    gitfixtures.run_git(["branch", "feature/exists"], cwd=clone)

    renv.ok("create", "feat", "--branch", "feature/exists", "--include", "alpha")
    wt = renv.worktrees / "feat" / "alpha"
    assert gitfixtures.current_branch(wt) == "feature/exists"
    assert gitfixtures.is_detached(wt) is False


def test_create_branch_checked_out_in_source_detach_default(renv: Renv) -> None:
    _alpha_in_source_on(renv, "feature/in-source")

    assert _create_feat_alpha(renv, "--branch", "feature/in-source").exit_code == 0
    wt = renv.worktrees / "feat" / "alpha"
    assert wt.exists()
    assert gitfixtures.is_detached(wt) is True

    note = env_meta(renv.worktrees / "feat")["environment"]["repos"][0]["note"]
    assert note is not None
    assert "detached worktree" in note


def test_create_branch_checked_out_in_source_fail(renv: Renv) -> None:
    _alpha_in_source_on(renv, "feature/in-source")

    result = _create_feat_alpha(renv, "--branch", "feature/in-source", "--on-branch-conflict", "fail")
    assert_failed_with(result, "Some repositories failed")


def test_create_branch_checked_out_in_source_move_with_dirty_file(renv: Renv) -> None:
    clone = _alpha_in_source_on(renv, "feature/move")
    (clone / "local-only.txt").write_text("keep-me", encoding="utf-8")

    result = _create_feat_alpha(renv, "--branch", "feature/move", "--on-branch-conflict", "move")
    assert result.exit_code == 0, result.output
    wt = renv.worktrees / "feat" / "alpha"
    assert gitfixtures.current_branch(wt) == "feature/move"
    assert (wt / "local-only.txt").read_text(encoding="utf-8") == "keep-me"
    assert gitfixtures.current_branch(clone) == "main"


def test_create_branch_checked_out_in_foreign_worktree_move(renv: Renv) -> None:
    (clone,) = renv.setup("alpha")
    foreign = renv.repos.root / "foreign" / "alpha"
    gitfixtures.create_foreign_worktree(clone, foreign, "feature/foreign")

    result = _create_feat_alpha(renv, "--branch", "feature/foreign", "--on-branch-conflict", "move")
    assert result.exit_code == 0, result.output
    assert gitfixtures.current_branch(renv.worktrees / "feat" / "alpha") == "feature/foreign"
    assert gitfixtures.is_detached(foreign) is True


def test_create_orphaned_worktree_auto_heals(renv: Renv) -> None:
    (clone,) = renv.setup("alpha")
    gitfixtures.simulate_orphaned_worktree(
        clone, renv.repos.root / "orphan" / "alpha", branch="feature/orphan"
    )

    assert _create_feat_alpha(renv, "--branch", "feature/orphan").exit_code == 0
    assert (renv.worktrees / "feat" / "alpha" / ".git").exists()


def test_create_stray_directory_clear_error(renv: Renv) -> None:
    renv.setup("alpha")
    gitfixtures.leave_stray_directory(renv.worktrees / "feat" / "alpha")

    result = _create_feat_alpha(renv, "--branch", "feature/x")
    assert result.exit_code != 0
    assert result.exception is not None
    assert "already exists and is not empty" in str(result.exception)


def test_add_branch_conflict_detach(renv: Renv) -> None:
    clone, _ = renv.setup("alpha", "beta")
    gitfixtures.checkout_branch_in_source(clone, "feature/add")
    renv.ok("create", "env", "--include", "beta")

    renv.ok("add", "env", "--include", "alpha", "--branch", "feature/add")
    wt = renv.worktrees / "env" / "alpha"
    assert wt.exists()
    assert gitfixtures.is_detached(wt) is True


def test_partial_failure_saves_env_and_status_shows_note(renv: Renv) -> None:
    assert_failed_with(create_batch_with_branch_conflict(renv), "Some repositories failed")
    assert (renv.worktrees / "batch" / "alpha" / ".git").exists()
    assert not (renv.worktrees / "batch" / "beta" / ".git").exists()
    assert "batch" in state_store.load_registry()

    by_repo = renv.status("batch")
    assert by_repo["alpha"]["present"] is True
    assert by_repo["beta"]["status"] == RepoStatus.FAILED.value
    assert by_repo["beta"]["note"] is not None
    assert "failed" in by_repo["beta"]["note"].lower()
