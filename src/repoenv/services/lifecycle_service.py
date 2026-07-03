"""Lifecycle service: remove, rename, sync, status/doctor, prune reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repoenv.adapters import git_adapter
from repoenv.domain.models import Environment, RepoStatus


@dataclass
class RepoHealth:
    """Health of a single repo entry within an environment."""

    repo: str
    worktree_path: Path
    present: bool
    dirty: bool


def check_dirty(env: Environment) -> list[str]:
    """Return names of repos whose worktrees have uncommitted changes."""
    dirty: list[str] = []
    for entry in env.repos:
        if entry.worktree_path.exists() and not git_adapter.is_clean(entry.worktree_path):
            dirty.append(entry.repo)
    return dirty


def remove_worktrees(env: Environment, *, force: bool) -> None:
    """Remove all worktrees of ``env`` from their source repositories."""
    for entry in env.repos:
        repo_path = env.source / entry.repo
        if not repo_path.exists():
            continue
        if entry.worktree_path.exists():
            git_adapter.remove_worktree(repo_path, entry.worktree_path, force=force)
        git_adapter.prune_worktrees(repo_path)


def sync_environment(env: Environment) -> list[str]:
    """Fetch each repo's remote; return names that failed to fetch."""
    failed: list[str] = []
    for entry in env.repos:
        repo_path = env.source / entry.repo
        try:
            git_adapter.fetch(repo_path, entry.remote)
        except Exception:  # noqa: BLE001 - report per-repo, keep going
            failed.append(entry.repo)
    return failed


def assess_health(env: Environment) -> list[RepoHealth]:
    """Return per-repo health, marking missing worktrees as stale."""
    health: list[RepoHealth] = []
    for entry in env.repos:
        present = entry.worktree_path.exists()
        dirty = present and not git_adapter.is_clean(entry.worktree_path)
        if not present:
            entry.status = RepoStatus.STALE
        health.append(
            RepoHealth(
                repo=entry.repo,
                worktree_path=entry.worktree_path,
                present=present,
                dirty=dirty,
            )
        )
    return health


def prune_environment(env: Environment) -> int:
    """Run ``git worktree prune`` for each repo; return count pruned."""
    pruned = 0
    for entry in env.repos:
        repo_path = env.source / entry.repo
        if repo_path.exists():
            git_adapter.prune_worktrees(repo_path)
            pruned += 1
    return pruned
