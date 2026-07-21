"""Environment service: create environments (validate-then-execute + journal).

This is the Phase 1 core. Selection is resolved against the source directory,
every repo is validated first, and only then are worktrees created so a failure
mid-batch leaves a consistent, resumable state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from repoenv.adapters import git_adapter, paths
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.errors import NothingMatchedError, UsageError

_RENV_MARKER_FILENAMES = (paths.ENV_META_FILENAME, paths.ENV_MARKER_FILENAME)


class BranchConflictStrategy(str, Enum):
    DETACH = "detach"
    MOVE = "move"
    FAIL = "fail"


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
    include_worktrees: bool,
) -> tuple[list[str], list[str]]:
    """Return ``(kept, skipped_worktrees)``.

    *skipped_worktrees* contains candidates that are git *linked* worktrees
    (not main repos). They are omitted unless *include_worktrees* is True,
    because ``git worktree add`` cannot target a linked worktree.
    """
    filtered = list(candidates)

    # Exclude any candidates that live under dest to avoid matching previously
    # created worktrees when dest is a subdirectory of source.
    if dest is not None and dest.is_relative_to(source):
        dest_rel = dest.relative_to(source).as_posix()
        filtered = [c for c in filtered if c != dest_rel and not c.startswith(dest_rel + "/")]

    skipped_worktrees: list[str] = []

    # If source itself is a renv root, user explicitly targets it; keep repos.
    if include_worktrees or _is_renv_root(source):
        return filtered, skipped_worktrees

    result: list[str] = []
    for candidate in filtered:
        candidate_path = source / candidate
        if git_adapter.is_linked_worktree(candidate_path):
            skipped_worktrees.append(candidate)
            continue
        if _is_under_nested_renv_root(source, candidate_path):
            continue
        result.append(candidate)
    return result, skipped_worktrees


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
    skipped_worktrees: list[str] = field(default_factory=list)


@dataclass
class AddPlan:
    """Validated plan for adding repositories to an existing environment."""

    env_name: str
    source: Path
    env_path: Path
    repos: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    skipped_worktrees: list[str] = field(default_factory=list)


def _normalize_patterns(patterns: list[str], source: Path) -> list[str]:
    """Expand ``~`` and make absolute patterns relative to *source*.

    Include/exclude patterns are matched against relative repo names discovered
    under *source*.  When the user passes a pattern like
    ``~/sbx/org/**/demo-*`` we expand ``~`` and strip the *source* prefix so the
    effective pattern becomes ``**/demo-*``.
    """
    result: list[str] = []
    for pat in patterns:
        if pat.startswith("~"):
            pat = str(Path(pat).expanduser())
        if Path(pat).is_absolute():
            try:
                pat = str(Path(pat).relative_to(source))
            except ValueError:
                pass  # not under source – keep as-is, will match nothing
        result.append(pat)
    return result


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
    include_worktrees: bool = False,
) -> CreatePlan:
    """Validate inputs and return a plan without touching the filesystem."""
    if not name:
        raise UsageError("Environment name must not be empty.")

    # Always work with resolved absolute paths so stored metadata is portable.
    source = source.resolve()
    dest = dest.resolve()

    if not source.exists():
        raise UsageError(f"Source directory does not exist: {source}")

    candidates = git_adapter.discover_repos(source)
    if not candidates:
        raise NothingMatchedError(
            f"No git repositories found under {source}.",
            hint="Point --source at a directory containing cloned repositories.",
        )

    candidates, skipped_wt = _filter_candidates(
        source=source, candidates=candidates, dest=dest, include_worktrees=include_worktrees
    )

    norm_include = _normalize_patterns(include, source) if include else include
    norm_exclude = _normalize_patterns(exclude, source) if exclude else exclude
    selected = resolve_selection(candidates, include=norm_include, exclude=norm_exclude)
    if not selected:
        hint = "Check your glob patterns and --exclude filters."
        if skipped_wt:
            hint += (
                f" {len(skipped_wt)} repo(s) were skipped because they are "
                "git worktrees; pass --include-worktrees to include them."
            )
        raise NothingMatchedError("No repositories matched the selection.", hint=hint)

    env_path = (dest / name).resolve()
    plan = CreatePlan(
        name=name,
        env_path=env_path,
        source=source,
        base_branch=default_branch,
        new_branch=branch,
        alias=alias,
        skipped_worktrees=skipped_wt,
    )

    for repo_name in selected:
        plan.repos.append(repo_name)

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
    if git_adapter.is_linked_worktree(repo_path):
        raise UsageError(
            f"Source repository '{repo_path}' is a linked worktree and cannot host new worktrees.",
            hint=(
                "Use the main clone/repository as --source, or omit "
                "--include-worktrees to skip linked worktrees."
            ),
        )

    git_adapter.prune_worktrees(repo_path)
    if not preserve:
        git_adapter.fetch(repo_path, remote)

    if not create_branch:
        git_adapter.add_worktree(
            repo_path,
            worktree_path,
            branch=target_branch,
            base=f"{remote}/{base}" if not preserve else "HEAD",
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
            base=f"{remote}/{base}" if not preserve else "HEAD",
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
        base=f"{remote}/{base}" if not preserve else "HEAD",
        create_branch=True,
    )
    return None


def execute_create_plan(
    plan: CreatePlan,
    *,
    preserve: bool = False,
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH,
    on_repo_start: Callable[[str, int, int], None] | None = None,
) -> Environment:
    """Execute a validated plan: create worktrees and return the environment.

    If ``preserve=True``, use source repos as-is without fetching or updating.
    Otherwise fetch latest from remote and update to default branch.

    *on_repo_start(repo_name, current_index, total)* is called before each repo
    so the caller can show progress.

    Raises :class:`~repoenv.errors.UsageError` if *plan.env_path* already exists
    on disk with content but without an renv marker (indicates a stale/conflicting
    directory that was not created by repo-env).
    """
    if plan.env_path.exists():
        has_marker = any((plan.env_path / m).exists() for m in _RENV_MARKER_FILENAMES)
        if not has_marker and any(plan.env_path.iterdir()):
            raise UsageError(
                f"Destination '{plan.env_path}' already exists and is not empty.",
                hint="Remove the directory manually, or run 'renv import' if it contains existing worktrees.",
            )

    plan.env_path.mkdir(parents=True, exist_ok=True)
    env = Environment(
        name=plan.name,
        alias=plan.alias,
        path=plan.env_path,
        source=plan.source,
        base_branch=plan.base_branch,
    )

    total = len(plan.repos)
    failures: list[str] = []
    for idx, repo_name in enumerate(plan.repos):
        if on_repo_start is not None:
            on_repo_start(repo_name, idx + 1, total)
        repo_path = plan.source / repo_name
        remote = "origin"
        resolved_base: str | None = plan.base_branch
        target_branch: str | None = plan.new_branch
        create_branch = plan.new_branch is not None
        worktree_path = plan.env_path / repo_name

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
                    move_context=f"{plan.name}/{repo_name}/{target_branch}",
                )
        except Exception as exc:  # noqa: BLE001 - per-repo robustness
            failures.append(repo_name)
            note = f"failed: {exc}"
        base = resolved_base or plan.base_branch or "unknown"
        branch_name = target_branch or plan.new_branch or base
        env.repos.append(
            RepoEntry(
                repo=repo_name,
                worktree_path=worktree_path,
                remote=remote,
                base=base,
                branch=branch_name,
                branch_created=create_branch,
                source_sha=_resolve_source_sha(repo_path, remote=remote, base=base, preserve=preserve),
                status=RepoStatus.FAILED if repo_name in failures else RepoStatus.OK,
                note=note,
            )
        )
    return env


def failed_repos(env: Environment) -> list[str]:
    """Return repo names whose worktree creation failed."""
    return [entry.repo for entry in env.repos if entry.status is RepoStatus.FAILED]


def build_add_plan(
    *,
    env: Environment,
    include: list[str] | None,
    exclude: list[str] | None,
    include_worktrees: bool = False,
) -> AddPlan:
    """Validate inputs and build a plan to add repos into ``env``."""
    candidates = git_adapter.discover_repos(env.source)
    if not candidates:
        raise NothingMatchedError(
            f"No git repositories found under {env.source}.",
            hint="Point source to a directory containing cloned repositories.",
        )

    candidates, skipped_wt = _filter_candidates(
        source=env.source, candidates=candidates, dest=None, include_worktrees=include_worktrees
    )
    norm_include = _normalize_patterns(include, env.source) if include else include
    norm_exclude = _normalize_patterns(exclude, env.source) if exclude else exclude
    selected = resolve_selection(candidates, include=norm_include, exclude=norm_exclude)
    if not selected:
        hint = "Check your glob patterns and --exclude filters."
        if skipped_wt:
            hint += (
                f" {len(skipped_wt)} repo(s) were skipped because they are "
                "git worktrees; pass --include-worktrees to include them."
            )
        raise NothingMatchedError("No repositories matched the selection.", hint=hint)

    existing = {entry.repo for entry in env.repos}
    plan = AddPlan(env_name=env.name, source=env.source, env_path=env.path, skipped_worktrees=skipped_wt)
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
    env: Environment,
    plan: AddPlan,
    *,
    branch: str | None = None,
    preserve: bool = False,
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH,
    on_repo_start: Callable[[str, int, int], None] | None = None,
) -> Environment:
    """Execute a validated add plan and append new repo entries to ``env``.

    If ``preserve=True``, use source repos as-is without fetching or updating.
    *on_repo_start(repo_name, current_index, total)* is called before each repo.
    """
    total = len(plan.repos)
    failures: list[str] = []
    for idx, repo_name in enumerate(plan.repos):
        if on_repo_start is not None:
            on_repo_start(repo_name, idx + 1, total)
        repo_path = plan.source / repo_name
        remote = "origin"
        resolved_base: str | None = env.base_branch
        target_branch: str | None = branch
        create_branch = branch is not None
        worktree_path = plan.env_path / repo_name

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
                    move_context=f"{env.name}/{repo_name}/{target_branch}",
                )
        except Exception as exc:  # noqa: BLE001 - per-repo robustness
            failures.append(repo_name)
            note = f"failed: {exc}"
        base = resolved_base or env.base_branch or "unknown"
        branch_name = target_branch or branch or base
        env.repos.append(
            RepoEntry(
                repo=repo_name,
                worktree_path=worktree_path,
                remote=remote,
                base=base,
                branch=branch_name,
                branch_created=create_branch,
                source_sha=_resolve_source_sha(repo_path, remote=remote, base=base, preserve=preserve),
                status=RepoStatus.FAILED if repo_name in failures else RepoStatus.OK,
                note=note,
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
