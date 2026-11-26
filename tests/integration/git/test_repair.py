"""Integration tests for ``renv repair``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from repoenv.adapters import state_store
from repoenv.domain.models import RepoStatus
from tests.integration.support import gitfixtures
from tests.integration.support.renv_helpers import (
    Renv,
    assert_failed_with,
    create_batch_with_branch_conflict,
    repos_by_name,
)


def _feat_with_alpha_deleted(renv: Renv, *create_opts: str) -> Path:
    """Create env ``feat`` with ``alpha``, then delete the worktree by hand; returns its path."""
    renv.setup("alpha")
    renv.ok("create", "feat", *create_opts, "--include", "alpha")
    worktree = renv.worktrees / "feat" / "alpha"
    shutil.rmtree(worktree)
    return worktree


def test_repair_restores_deleted_worktree(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    renv.ok("create", "feat", "--branch", "feature/repair")

    alpha = renv.worktrees / "feat" / "alpha"
    shutil.rmtree(alpha)
    renv.ok("repair", "feat")
    assert (alpha / ".git").exists()
    assert gitfixtures.current_branch(alpha) == "feature/repair"


def test_repair_partial_failure_retry(renv: Renv) -> None:
    batch = renv.worktrees / "batch"
    assert create_batch_with_branch_conflict(renv).exit_code != 0
    assert (batch / "alpha" / ".git").exists()
    assert not (batch / "beta" / ".git").exists()

    renv.ok("repair", "batch", "--on-branch-conflict", "detach")
    assert (batch / "beta" / ".git").exists()


def test_repair_orphaned_worktree_metadata(renv: Renv) -> None:
    orphan_path = renv.worktrees / "feat" / "alpha"
    clone = renv.repos.make_bare_and_clone("alpha")
    gitfixtures.simulate_orphaned_worktree(clone, orphan_path, branch="feature/orphan")

    renv.setup()
    renv.ok("create", "feat", "--branch", "feature/orphan", "--include", "alpha")
    shutil.rmtree(orphan_path)
    renv.ok("repair", "feat")
    assert (orphan_path / ".git").exists()


def test_repair_stray_directory_clear_error(renv: Renv) -> None:
    worktree = _feat_with_alpha_deleted(renv, "--branch", "feature/x")
    gitfixtures.leave_stray_directory(worktree)

    assert_failed_with(renv.invoke("repair", "feat"), "Failed to repair")


def test_repair_dry_run_lists_candidates(renv: Renv) -> None:
    worktree = _feat_with_alpha_deleted(renv)

    dry = renv.ok("repair", "feat", "--dry-run")
    assert "alpha" in dry.output
    assert not worktree.exists()


def test_create_reconciles_deleted_env_directory(renv: Renv) -> None:
    renv.setup("alpha")
    renv.ok("create", "ado", "--include", "alpha")

    shutil.rmtree(renv.worktrees / "ado")
    recreate = renv.ok("create", "ado", "--include", "alpha")
    assert "Reconciled" in recreate.output
    assert (renv.worktrees / "ado" / "alpha" / ".git").exists()


def test_repair_noop_when_all_worktrees_healthy(renv: Renv) -> None:
    renv.setup("alpha")
    renv.ok("create", "feat", "--include", "alpha")

    assert "No worktrees need repair" in renv.ok("repair", "feat").output


def test_repair_include_repairs_subset_only(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    renv.ok("create", "feat", "--branch", "feature/subset")
    feat = renv.worktrees / "feat"
    shutil.rmtree(feat / "alpha")
    shutil.rmtree(feat / "beta")

    renv.ok("repair", "feat", "--include", "alpha")
    assert (feat / "alpha" / ".git").exists()
    assert not (feat / "beta").exists()


def test_repair_status_workflow_shows_missing_then_ok(renv: Renv) -> None:
    _feat_with_alpha_deleted(renv, "--branch", "feature/status")

    before = renv.ok("status", "feat", "--json")
    assert repos_by_name(before)["alpha"]["present"] is False
    assert "repair" in before.output.lower()

    renv.ok("repair", "feat")

    after = renv.status("feat")["alpha"]
    assert after["present"] is True
    assert after["status"] == RepoStatus.OK.value


def test_repair_resolves_environment_from_cwd(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = _feat_with_alpha_deleted(renv)
    monkeypatch.chdir(worktree.parent)

    renv.ok("repair")
    assert (worktree / ".git").exists()


def test_repair_after_partial_failure_updates_registry_status(renv: Renv) -> None:
    assert create_batch_with_branch_conflict(renv).exit_code != 0

    renv.ok("repair", "batch", "--on-branch-conflict", "detach")

    batch = state_store.load_registry().get("batch")
    assert batch is not None
    assert {entry.repo: entry.status for entry in batch.repos} == {
        "alpha": RepoStatus.OK,
        "beta": RepoStatus.OK,
    }
    assert (renv.worktrees / "batch" / "beta" / ".git").exists()
