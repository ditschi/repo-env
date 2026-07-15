"""Environment service: create environments (validate-then-execute + journal).

This is the Phase 1 core. Selection is resolved against the source directory,
every repo is validated first, and only then are worktrees created so a failure
mid-batch leaves a consistent, resumable state.

Multi-branch: a single repo can appear multiple times in one environment, once
per requested base branch (``--from``). Worktree directories use a flat layout;
when a repo yields more than one worktree the base branch is appended as a
postfix (``alpha-main``, ``alpha-develop``), and any created branch is likewise
postfixed (``feature/x-main``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from repoenv.adapters import git_adapter, paths
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.errors import NothingMatchedError, UsageError

_RENV_MARKER_FILENAMES = (paths.ENV_META_FILENAME, paths.ENV_MARKER_FILENAME)

_DIR_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class BranchConflictStrategy(str, Enum):
    DETACH = "detach"
    MOVE = "move"
    FAIL = "fail"


def parse_branch_list(values: list[str] | None) -> list[str]:
    """Split repeated and/or comma-separated ``--from`` values into an ordered list.

    ``["main,develop", "release/1.0"]`` -> ``["main", "develop", "release/1.0"]``.
    Order is preserved and duplicates are removed.
    """
    if not values:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for item in raw.split(","):
            branch = item.strip()
            if branch and branch not in seen:
                seen.add(branch)
                result.append(branch)
    return result


def _sanitize_ref_for_dir(ref: str) -> str:
    """Turn a branch ref into a filesystem-friendly postfix (``feature/x`` -> ``feature-x``)."""
    cleaned = _DIR_SANITIZE_RE.sub("-", ref.strip()).strip("-")
    return cleaned or "branch"


def _target_branch(branch: str | None, base: str | None, *, postfix: bool) -> str | None:
    """Resolve the branch to create for one worktree, postfixing on multi-branch."""
    if branch is None:
        return None
    if not postfix or base is None:
        return branch
    return f"{branch}-{_sanitize_ref_for_dir(base)}"


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
class PlannedWorktree:
    """One repo × base-branch worktree to be created under the environment dir."""

    repo: str
    worktree_dir: str
    base: str | None
    new_branch: str | None

    @property
    def create_branch(self) -> bool:
        """True when a fresh branch should be created (vs. detached checkout)."""
        return self.new_branch is not None


@dataclass
class CreatePlan:
    """A validated, previewable plan for creating an environment."""

    name: str
    env_path: Path
    source: Path
    alias: str | None
    default_base: str | None = None
    worktrees: list[PlannedWorktree] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        """Worktree directory names (used for preview/rendering)."""
        return [w.worktree_dir for w in self.worktrees]


@dataclass
class AddPlan:
    """Validated plan for adding repositories to an existing environment."""

    env_name: str
    source: Path
    env_path: Path
    worktrees: list[PlannedWorktree] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        """Worktree directory names (used for preview/rendering)."""
        return [w.worktree_dir for w in self.worktrees]


def _assign_dir(repo: str, base: str | None, *, postfix: bool, used: set[str]) -> str:
    """Pick a unique, flat worktree directory name, postfixing the base on demand."""
    if postfix and base is not None:
        candidate = f"{repo}-{_sanitize_ref_for_dir(base)}"
    else:
        candidate = repo
    if candidate not in used:
        used.add(candidate)
        return candidate
    # Sanitisation clash (e.g. ``feat/x`` vs ``feat-x``): disambiguate numerically.
    stem = f"{repo}-{_sanitize_ref_for_dir(base)}" if base is not None else repo
    candidate = stem
    suffix = 2
    while candidate in used:
        candidate = f"{stem}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


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
    from_branches: list[str] | None = None,
    include_renv: bool = False,
) -> CreatePlan:
    """Validate inputs and return a plan without touching the filesystem.

    ``from_branches`` lists the base branch(es) to start from. With a single base
    the classic one-worktree-per-repo layout is used; with multiple bases each
    repo gets one worktree per base, postfixed by the base branch name.
    """
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

    bases: list[str | None] = list(from_branches) if from_branches else [default_branch]
    postfix = len(bases) > 1

    env_path = dest / name
    plan = CreatePlan(
        name=name,
        env_path=env_path,
        source=source,
        alias=alias,
        default_base=default_branch,
    )

    used: set[str] = set()
    for repo_name in selected:
        for base in bases:
            worktree_dir = _assign_dir(repo_name, base, postfix=postfix, used=used)
            plan.worktrees.append(
                PlannedWorktree(
                    repo=repo_name,
                    worktree_dir=worktree_dir,
                    base=base,
                    new_branch=_target_branch(branch, base, postfix=postfix),
                )
            )

    return plan


def _ensure_worktree_path_is_clean(worktree_path: Path) -> None:
    if not worktree_path.exists():
        return
    if git_adapter.is_worktree_root(worktree_path):
        return
    raise UsageError(
        f"Worktree path exists but is not a git repo: {worktree_path}",
        hint="Remove the directory or choose a different --dest.",
    )


def _resolve_source_sha(repo_path: Path, *, remote: str, base: str, preserve: bool) -> str | None:
    """Best-effort resolve of the source ref SHA for metadata."""
    try:
        ref = f"{remote}/{base}" if not preserve else "HEAD"
        return git_adapter.rev_parse(repo_path, ref)
    except Exception:  # noqa: BLE001 - per-repo robustness for optional metadata
        return None


def _create_or_attach_worktree(
    *,
    repo_path: Path,
    worktree_path: Path,
    remote: str,
    base: str,
    target_branch: str,
    create_branch: bool,
    preserve: bool,
    on_branch_conflict: BranchConflictStrategy,
    move_context: str,
) -> str | None:
    """Ensure a worktree exists; return an optional note for the RepoEntry."""
    git_adapter.prune_worktrees(repo_path)
    if not preserve:
        git_adapter.fetch(repo_path, remote)

    # With --preserve we branch off the local base ref (e.g. ``develop``) so
    # multi-branch bases are honoured; otherwise off the freshly fetched remote.
    base_ref = base if preserve else f"{remote}/{base}"

    if not create_branch:
        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=base_ref,
            create_branch=False,
        )
        return None

    in_use = git_adapter.find_worktree_for_branch(repo_path, target_branch)
    if in_use is not None:
        if on_branch_conflict is BranchConflictStrategy.FAIL:
            raise UsageError(
                f"Branch '{target_branch}' is already checked out in {in_use}.",
                hint="Free the branch, or pass --on-branch-conflict=detach|move.",
            )
        if on_branch_conflict is BranchConflictStrategy.MOVE:
            created = git_adapter.stash_push(
                in_use,
                include_untracked=True,
                message=f"repo-env move {move_context}",
            )
            if Path(in_use).resolve() == Path(repo_path).resolve():
                git_adapter.checkout(in_use, base)
            else:
                git_adapter.checkout(in_use, "--detach")
            git_adapter.add_worktree_existing_branch(repo_path, worktree_path, target_branch)
            if created:
                git_adapter.stash_pop(worktree_path)
            return f"moved branch '{target_branch}' from {in_use}"

        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=base_ref,
            create_branch=False,
        )
        return f"branch '{target_branch}' in use at {in_use}; created detached worktree"

    if git_adapter.branch_exists(repo_path, target_branch):
        git_adapter.add_worktree_existing_branch(repo_path, worktree_path, target_branch)
        return None

    git_adapter.add_worktree(
        repo_path,
        worktree_path,
        branch=target_branch,
        base=base_ref,
        create_branch=True,
    )
    return None


def _execute_worktree(
    *,
    env: Environment,
    source: Path,
    env_name: str,
    planned: PlannedWorktree,
    default_base: str | None,
    preserve: bool,
    on_branch_conflict: BranchConflictStrategy,
    failures: list[str],
) -> None:
    """Create one planned worktree and append its RepoEntry to ``env``."""
    repo_path = source / planned.repo
    remote = "origin"
    resolved_base: str | None = planned.base
    target_branch: str | None = planned.new_branch
    create_branch = planned.create_branch
    worktree_path = env.path / planned.worktree_dir

    already_exists = worktree_path.exists() and git_adapter.is_worktree_root(worktree_path)
    note: str | None = None
    try:
        if resolved_base is None:
            resolved_base = git_adapter.default_branch(repo_path, remote)
        if target_branch is None:
            target_branch = resolved_base
        if not already_exists:
            _ensure_worktree_path_is_clean(worktree_path)
            note = _create_or_attach_worktree(
                repo_path=repo_path,
                worktree_path=worktree_path,
                remote=remote,
                base=resolved_base,
                target_branch=target_branch,
                create_branch=create_branch,
                preserve=preserve,
                on_branch_conflict=on_branch_conflict,
                move_context=f"{env_name}/{planned.repo}/{target_branch}",
            )
    except Exception as exc:  # noqa: BLE001 - per-repo robustness
        failures.append(planned.worktree_dir)
        note = f"failed: {exc}"
    base = resolved_base or default_base or "unknown"
    branch_name = target_branch or planned.new_branch or base
    env.repos.append(
        RepoEntry(
            repo=planned.repo,
            worktree_path=worktree_path,
            remote=remote,
            base=base,
            branch=branch_name,
            branch_created=create_branch,
            source_sha=_resolve_source_sha(repo_path, remote=remote, base=base, preserve=preserve),
            status=RepoStatus.FAILED if planned.worktree_dir in failures else RepoStatus.OK,
            note=note,
        )
    )


def execute_create_plan(
    plan: CreatePlan,
    *,
    preserve: bool = False,
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH,
) -> Environment:
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
        base_branch=plan.default_base,
    )

    failures: list[str] = []
    for planned in plan.worktrees:
        _execute_worktree(
            env=env,
            source=plan.source,
            env_name=plan.name,
            planned=planned,
            default_base=plan.default_base,
            preserve=preserve,
            on_branch_conflict=on_branch_conflict,
            failures=failures,
        )
    return env


def failed_repos(env: Environment) -> list[str]:
    """Return worktree labels whose creation failed."""
    return [entry.worktree_path.name for entry in env.repos if entry.status is RepoStatus.FAILED]


def _plan_add_legacy(
    *,
    env: Environment,
    selected: list[str],
    branch: str | None,
    used: set[str],
    plan: AddPlan,
) -> None:
    """Classic add (no ``--from``): skip repos already present, one worktree each."""
    existing_repos = {entry.repo for entry in env.repos}
    for repo_name in selected:
        if repo_name in existing_repos or repo_name in used:
            plan.skipped[repo_name] = "already present in environment"
            continue
        used.add(repo_name)
        plan.worktrees.append(
            PlannedWorktree(
                repo=repo_name,
                worktree_dir=repo_name,
                base=env.base_branch,
                new_branch=_target_branch(branch, env.base_branch, postfix=False),
            )
        )


def _plan_add_from(
    *,
    env: Environment,
    selected: list[str],
    from_branches: list[str],
    branch: str | None,
    used: set[str],
    plan: AddPlan,
) -> None:
    """Add one branch-worktree per base branch, postfixing the directory as needed."""
    postfix = len(from_branches) > 1
    present_repos = {entry.repo for entry in env.repos}
    for repo_name in selected:
        # A brand-new repo with a single base keeps the plain dir; an existing
        # repo (already has worktrees) is always postfixed for consistency.
        plain_ok = not postfix and repo_name not in present_repos and repo_name not in used
        for base in from_branches:
            worktree_dir = repo_name if plain_ok else f"{repo_name}-{_sanitize_ref_for_dir(base)}"
            if worktree_dir in used:
                plan.skipped[worktree_dir] = "already present in environment"
                continue
            used.add(worktree_dir)
            plan.worktrees.append(
                PlannedWorktree(
                    repo=repo_name,
                    worktree_dir=worktree_dir,
                    base=base,
                    new_branch=_target_branch(branch, base, postfix=postfix),
                )
            )


def build_add_plan(
    *,
    env: Environment,
    include: list[str] | None,
    exclude: list[str] | None,
    from_branches: list[str] | None = None,
    branch: str | None = None,
    include_renv: bool = False,
) -> AddPlan:
    """Validate inputs and build a plan to add repos/branch-worktrees into ``env``.

    Without ``--from`` this keeps the classic behaviour (skip repos already
    present, one worktree per repo). With ``--from`` a new branch-worktree is
    planned per base branch, so the same repo can be added on another branch.
    """
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

    plan = AddPlan(env_name=env.name, source=env.source, env_path=env.path)
    used: set[str] = {entry.worktree_path.name for entry in env.repos}

    if not from_branches:
        _plan_add_legacy(env=env, selected=selected, branch=branch, used=used, plan=plan)
    else:
        _plan_add_from(
            env=env,
            selected=selected,
            from_branches=list(from_branches),
            branch=branch,
            used=used,
            plan=plan,
        )

    if not plan.worktrees:
        raise NothingMatchedError(
            "No repositories eligible to add.",
            hint="Adjust selection or all selected repos/branches already present.",
        )
    return plan


def execute_add_plan(
    env: Environment,
    plan: AddPlan,
    *,
    preserve: bool = False,
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH,
) -> Environment:
    """Execute a validated add plan and append new repo entries to ``env``.

    If ``preserve=True``, use source repos as-is without fetching or updating.
    """
    failures: list[str] = []
    for planned in plan.worktrees:
        _execute_worktree(
            env=env,
            source=plan.source,
            env_name=env.name,
            planned=planned,
            default_base=env.base_branch,
            preserve=preserve,
            on_branch_conflict=on_branch_conflict,
            failures=failures,
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
