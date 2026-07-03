"""Environment service: create environments (validate-then-execute + journal).

This is the Phase 1 core. Selection is resolved against the source directory,
every repo is validated first, and only then are worktrees created so a failure
mid-batch leaves a consistent, resumable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repoenv.adapters import git_adapter
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.errors import NothingMatchedError, UsageError


@dataclass
class CreatePlan:
    """A validated, previewable plan for creating an environment."""

    name: str
    env_path: Path
    source: Path
    base_branch: str | None
    new_branch: str | None
    alias: str | None
    repos: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


@dataclass
class AddPlan:
    """Validated plan for adding repositories to an existing environment."""

    env_name: str
    source: Path
    env_path: Path
    repos: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def build_create_plan(
    *,
    name: str,
    source: Path,
    dest: Path,
    include: list[str] | None,
    exclude: list[str] | None,
    branch: str | None,
    alias: str | None,
    default_branch: str | None,
    force: bool,
) -> CreatePlan:
    """Validate inputs and return a plan without touching the filesystem."""
    if not name:
        raise UsageError("Environment name must not be empty.")
    if not source.exists():
        raise UsageError(f"Source directory does not exist: {source}")

    candidates = git_adapter.discover_repos(source)
    if not candidates:
        raise NothingMatchedError(
            f"No git repositories found under {source}.",
            hint="Point --source at a directory containing cloned repositories.",
        )

    selected = resolve_selection(candidates, include=include, exclude=exclude)
    if not selected:
        raise NothingMatchedError(
            "No repositories matched the selection.",
            hint="Check your glob patterns and --exclude filters.",
        )

    env_path = dest / name
    plan = CreatePlan(
        name=name,
        env_path=env_path,
        source=source,
        base_branch=default_branch,
        new_branch=branch,
        alias=alias,
    )

    for repo_name in selected:
        repo_path = source / repo_name
        if not force and not git_adapter.is_clean(repo_path):
            plan.skipped[repo_name] = "source has uncommitted changes"
            continue
        plan.repos.append(repo_name)

    if not plan.repos:
        raise NothingMatchedError(
            "All matched repositories were skipped.",
            hint="Commit/stash changes in the source repos, or pass --force.",
        )
    return plan


def execute_create_plan(plan: CreatePlan) -> Environment:
    """Execute a validated plan: create worktrees and return the environment."""
    plan.env_path.mkdir(parents=True, exist_ok=True)
    env = Environment(
        name=plan.name,
        alias=plan.alias,
        path=plan.env_path,
        source=plan.source,
        base_branch=plan.base_branch,
    )

    for repo_name in plan.repos:
        repo_path = plan.source / repo_name
        remote = "origin"
        base = plan.base_branch or git_adapter.default_branch(repo_path, remote)
        target_branch = plan.new_branch or base
        create_branch = plan.new_branch is not None
        worktree_path = plan.env_path / repo_name

        git_adapter.fetch(repo_path, remote)
        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=f"{remote}/{base}",
            create_branch=create_branch,
        )
        env.repos.append(
            RepoEntry(
                repo=repo_name,
                worktree_path=worktree_path,
                remote=remote,
                base=base,
                branch=target_branch,
                branch_created=create_branch,
                source_sha=git_adapter.rev_parse(repo_path, f"{remote}/{base}"),
                status=RepoStatus.OK,
            )
        )
    return env


def build_add_plan(
    *,
    env: Environment,
    include: list[str] | None,
    exclude: list[str] | None,
    force: bool,
) -> AddPlan:
    """Validate inputs and build a plan to add repos into ``env``."""
    candidates = git_adapter.discover_repos(env.source)
    if not candidates:
        raise NothingMatchedError(
            f"No git repositories found under {env.source}.",
            hint="Point source to a directory containing cloned repositories.",
        )

    selected = resolve_selection(candidates, include=include, exclude=exclude)
    if not selected:
        raise NothingMatchedError(
            "No repositories matched the selection.",
            hint="Check your glob patterns and --exclude filters.",
        )

    existing = {entry.repo for entry in env.repos}
    plan = AddPlan(env_name=env.name, source=env.source, env_path=env.path)
    for repo_name in selected:
        if repo_name in existing:
            plan.skipped[repo_name] = "already present in environment"
            continue
        repo_path = env.source / repo_name
        if not force and not git_adapter.is_clean(repo_path):
            plan.skipped[repo_name] = "source has uncommitted changes"
            continue
        plan.repos.append(repo_name)

    if not plan.repos:
        raise NothingMatchedError(
            "No repositories eligible to add.",
            hint="Adjust selection or pass --force to include dirty repositories.",
        )
    return plan


def execute_add_plan(env: Environment, plan: AddPlan, *, branch: str | None = None) -> Environment:
    """Execute a validated add plan and append new repo entries to ``env``."""
    for repo_name in plan.repos:
        repo_path = plan.source / repo_name
        remote = "origin"
        base = env.base_branch or git_adapter.default_branch(repo_path, remote)
        target_branch = branch or base
        create_branch = branch is not None
        worktree_path = plan.env_path / repo_name

        git_adapter.fetch(repo_path, remote)
        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=f"{remote}/{base}",
            create_branch=create_branch,
        )
        env.repos.append(
            RepoEntry(
                repo=repo_name,
                worktree_path=worktree_path,
                remote=remote,
                base=base,
                branch=target_branch,
                branch_created=create_branch,
                source_sha=git_adapter.rev_parse(repo_path, f"{remote}/{base}"),
                status=RepoStatus.OK,
            )
        )
    env.touch()
    return env


def build_merge_plan(
    *,
    left: Environment,
    right: Environment,
    op: SetOp,
    dest_name: str,
    dest_root: Path,
    alias: str | None,
) -> CreatePlan:
    """Build a create plan by combining repo sets from two environments."""
    left_names = [entry.repo for entry in left.repos]
    right_names = [entry.repo for entry in right.repos]
    merged = set_combine(left_names, right_names, op)
    if not merged:
        raise NothingMatchedError(
            "Merge operation resulted in an empty repository set.",
            hint="Try a different set operation or source environments.",
        )

    return build_create_plan(
        name=dest_name,
        source=left.source,
        dest=dest_root,
        include=merged,
        exclude=None,
        branch=None,
        alias=alias,
        default_branch=left.base_branch,
        force=True,
    )
