"""Environment service: create environments (validate-then-execute + journal).

This is the Phase 1 core. Selection is resolved against the source directory,
every repo is validated first, and only then are worktrees created so a failure
mid-batch leaves a consistent, resumable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repoenv.adapters import git_adapter, paths
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.errors import NothingMatchedError, UsageError

_RENV_MARKER_FILENAMES = (paths.ENV_MARKER_FILENAME, paths.ENV_META_FILENAME)


def _is_renv_root(path: Path) -> bool:
    return any((path / marker).is_file() for marker in _RENV_MARKER_FILENAMES)


def _is_under_nested_renv_root(source: Path, candidate_path: Path) -> bool:
    """Return True if candidate is at or under a nested renv root below source."""
    current = candidate_path
    while current != source:
        if _is_renv_root(current):
            return True
        current = current.parent
    return False


def _filter_candidates(
    *,
    source: Path,
    candidates: list[str],
    dest: Path | None,
    include_renv: bool,
) -> list[str]:
    filtered = list(candidates)

    # Exclude any candidates that live under dest to avoid matching previously
    # created worktrees when dest is a subdirectory of source.
    if dest is not None and dest.is_relative_to(source):
        dest_rel = dest.relative_to(source).as_posix()
        filtered = [c for c in filtered if c != dest_rel and not c.startswith(dest_rel + "/")]

    # If source itself is a renv root, user explicitly targets it; keep repos.
    if include_renv or _is_renv_root(source):
        return filtered

    result: list[str] = []
    for candidate in filtered:
        candidate_path = source / candidate
        if _is_under_nested_renv_root(source, candidate_path):
            continue
        result.append(candidate)
    return result


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
    include_renv: bool = False,
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

    candidates = _filter_candidates(
        source=source, candidates=candidates, dest=dest, include_renv=include_renv
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
        plan.repos.append(repo_name)

    return plan


def execute_create_plan(plan: CreatePlan, *, preserve: bool = False) -> Environment:
    """Execute a validated plan: create worktrees and return the environment.

    If ``preserve=True``, use source repos as-is without fetching or updating.
    Otherwise fetch latest from remote and update to default branch.
    """
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

        already_exists = worktree_path.exists() and git_adapter.is_git_repo(worktree_path)
        if not already_exists:
            if not preserve:
                git_adapter.fetch(repo_path, remote)
            git_adapter.add_worktree(
                repo_path,
                worktree_path,
                branch=target_branch,
                base=f"{remote}/{base}" if not preserve else "HEAD",
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
                source_sha=git_adapter.rev_parse(repo_path, f"{remote}/{base}" if not preserve else "HEAD"),
                status=RepoStatus.OK,
            )
        )
    return env


def build_add_plan(
    *,
    env: Environment,
    include: list[str] | None,
    exclude: list[str] | None,
    include_renv: bool = False,
) -> AddPlan:
    """Validate inputs and build a plan to add repos into ``env``."""
    candidates = git_adapter.discover_repos(env.source)
    if not candidates:
        raise NothingMatchedError(
            f"No git repositories found under {env.source}.",
            hint="Point source to a directory containing cloned repositories.",
        )

    candidates = _filter_candidates(
        source=env.source, candidates=candidates, dest=None, include_renv=include_renv
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
        plan.repos.append(repo_name)

    if not plan.repos:
        raise NothingMatchedError(
            "No repositories eligible to add.",
            hint="Adjust selection or all selected repos already present.",
        )
    return plan


def execute_add_plan(
    env: Environment, plan: AddPlan, *, branch: str | None = None, preserve: bool = False
) -> Environment:
    """Execute a validated add plan and append new repo entries to ``env``.

    If ``preserve=True``, use source repos as-is without fetching or updating.
    """
    for repo_name in plan.repos:
        repo_path = plan.source / repo_name
        remote = "origin"
        base = env.base_branch or git_adapter.default_branch(repo_path, remote)
        target_branch = branch or base
        create_branch = branch is not None
        worktree_path = plan.env_path / repo_name

        if not preserve:
            git_adapter.fetch(repo_path, remote)
        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=f"{remote}/{base}" if not preserve else "HEAD",
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
                source_sha=git_adapter.rev_parse(repo_path, f"{remote}/{base}" if not preserve else "HEAD"),
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
    )
