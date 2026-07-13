"""Lifecycle service: remove, rename, sync, status/check, prune reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repoenv.adapters import git_adapter
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import resolve_selection
from repoenv.services import environment_service
from repoenv.services.environment_service import BranchConflictStrategy


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
            if entry.status is not RepoStatus.FAILED:
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


def _is_healthy_worktree(entry: RepoEntry) -> bool:
    return entry.worktree_path.exists() and git_adapter.is_worktree_root(entry.worktree_path)


def list_repair_candidates(
    env: Environment,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Return repo names whose worktrees are missing or otherwise need repair."""
    repo_names = [entry.repo for entry in env.repos]
    if include is not None or exclude is not None:
        repo_names = resolve_selection(repo_names, include=include, exclude=exclude)
    allowed = set(repo_names)
    return [entry.repo for entry in env.repos if entry.repo in allowed and not _is_healthy_worktree(entry)]


def repair_environment(
    env: Environment,
    *,
    preserve: bool = False,
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Recreate missing or failed worktrees from registry metadata."""
    candidates = set(list_repair_candidates(env, include=include, exclude=exclude))
    repaired: list[str] = []
    failed: list[str] = []

    for entry in env.repos:
        if entry.repo not in candidates:
            continue
        if _is_healthy_worktree(entry):
            continue

        repo_path = env.source / entry.repo
        try:
            environment_service._ensure_worktree_path_is_clean(entry.worktree_path)
            note = environment_service._create_or_attach_worktree(
                repo_path=repo_path,
                worktree_path=entry.worktree_path,
                remote=entry.remote,
                base=entry.base,
                target_branch=entry.branch,
                create_branch=entry.branch_created,
                preserve=preserve,
                on_branch_conflict=on_branch_conflict,
                move_context=f"{env.name}/{entry.repo}/{entry.branch}",
            )
            entry.status = RepoStatus.OK
            entry.note = note
            entry.source_sha = environment_service._resolve_source_sha(
                repo_path, remote=entry.remote, base=entry.base, preserve=preserve
            )
            repaired.append(entry.repo)
        except Exception as exc:  # noqa: BLE001 - per-repo robustness
            failed.append(entry.repo)
            entry.status = RepoStatus.FAILED
            entry.note = f"failed: {exc}"

    if repaired or failed:
        env.touch()
    return repaired, failed
