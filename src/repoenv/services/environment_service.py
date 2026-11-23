"""Environment service: create environments (validate-then-execute + journal).

This is the Phase 1 core. Selection is resolved against the source directory,
every repo is validated first, and only then are worktrees created so a failure
mid-batch leaves a consistent, resumable state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from repoenv.adapters import git_adapter, paths
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.errors import NothingMatchedError, UsageError

_RENV_MARKER_FILENAMES = (paths.ENV_META_FILENAME, paths.ENV_MARKER_FILENAME)
_REMOTE = "origin"

ProgressCallback = Callable[[str, int, int], None]


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


@dataclass(frozen=True)
class CreateRequest:
    """User input for :func:`build_create_plan`."""

    name: str
    source: Path
    dest: Path
    include: list[str] | None = None
    exclude: list[str] | None = None
    branch: str | None = None
    alias: str | None = None
    default_branch: str | None = None
    include_worktrees: bool = False


@dataclass(frozen=True)
class MergeTarget:
    """Name, parent directory and alias of the environment a merge creates."""

    name: str
    dest_root: Path
    alias: str | None = None


@dataclass(frozen=True)
class ExecuteOptions:
    """Run-wide options for :func:`execute_create_plan` / :func:`execute_add_plan`.

    If ``preserve=True``, source repos are used as-is without fetching or
    updating. *on_repo_start(repo_name, current_index, total)* is called before
    each repo so the caller can show progress.
    """

    preserve: bool = False
    on_branch_conflict: BranchConflictStrategy = BranchConflictStrategy.DETACH
    on_repo_start: ProgressCallback | None = None


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
    branch_overrides: dict[str, str] = field(default_factory=dict)
    branch_conflicts: list[str] = field(default_factory=list)


@dataclass
class AddPlan:
    """Validated plan for adding repositories to an existing environment."""

    env_name: str
    source: Path
    env_path: Path
    repos: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    skipped_worktrees: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorktreeRequest:
    """Everything needed to create (or attach) one repository's worktree."""

    repo_path: Path
    worktree_path: Path
    remote: str
    base: str
    target_branch: str
    create_branch: bool
    preserve: bool
    on_branch_conflict: BranchConflictStrategy
    move_context: str

    @property
    def start_point(self) -> str:
        """The ref a new worktree starts from."""
        return "HEAD" if self.preserve else f"{self.remote}/{self.base}"


@dataclass(frozen=True)
class _RepoJob:
    """One repository to materialise during a create/add run."""

    env_name: str
    repo_name: str
    source: Path
    env_path: Path
    base_branch: str | None
    branch: str | None
    fallback_branch: str | None


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


def _expand_group_token(token: str, groups: dict[str, str]) -> str:
    """Return the stored glob for an ``@group`` token, or the token itself."""
    if not token.startswith("@"):
        return token
    group_name = token[1:]
    if group_name not in groups:
        raise UsageError(
            f"Unknown repo group '@{group_name}'.",
            hint="Set it with 'renv config groups.<name> <pattern>', " "or run 'renv config' to list groups.",
        )
    return groups[group_name]


def expand_repo_groups(patterns: list[str], groups: dict[str, str]) -> list[str]:
    """Expand ``@group`` tokens in include/exclude patterns into their stored globs.

    A group holds one glob, or a comma-separated list of globs (the same
    format ``--include``/``--exclude`` already accept), set via
    ``renv config groups.<name> <pattern>``. Plain (non-``@``) tokens pass
    through unchanged, so this is safe to call unconditionally.
    """
    tokens = (part.strip() for raw in patterns for part in raw.split(","))
    return [_expand_group_token(token, groups) for token in tokens if token]


def _discover_candidates(source: Path, *, hint: str) -> list[str]:
    candidates = git_adapter.discover_repos(source)
    if not candidates:
        raise NothingMatchedError(f"No git repositories found under {source}.", hint=hint)
    return candidates


def _select_repos(
    candidates: list[str], source: Path, include: list[str] | None, exclude: list[str] | None
) -> list[str]:
    norm_include = _normalize_patterns(include, source) if include else include
    norm_exclude = _normalize_patterns(exclude, source) if exclude else exclude
    return resolve_selection(candidates, include=norm_include, exclude=norm_exclude)


def _nothing_matched(skipped_worktrees: list[str]) -> NothingMatchedError:
    hint = "Check your glob patterns and --exclude filters."
    if skipped_worktrees:
        hint += (
            f" {len(skipped_worktrees)} repo(s) were skipped because they are "
            "git worktrees; pass --include-worktrees to include them."
        )
    return NothingMatchedError("No repositories matched the selection.", hint=hint)


def build_create_plan(request: CreateRequest) -> CreatePlan:
    """Validate inputs and return a plan without touching the filesystem."""
    if not request.name:
        raise UsageError("Environment name must not be empty.")

    # Always work with resolved absolute paths so stored metadata is portable.
    source = request.source.resolve()
    dest = request.dest.resolve()

    if not source.exists():
        raise UsageError(f"Source directory does not exist: {source}")

    candidates = _discover_candidates(
        source, hint="Point --source at a directory containing cloned repositories."
    )
    candidates, skipped_wt = _filter_candidates(
        source=source, candidates=candidates, dest=dest, include_worktrees=request.include_worktrees
    )
    selected = _select_repos(candidates, source, request.include, request.exclude)
    if not selected:
        raise _nothing_matched(skipped_wt)

    return CreatePlan(
        name=request.name,
        env_path=(dest / request.name).resolve(),
        source=source,
        base_branch=request.default_branch,
        new_branch=request.branch,
        alias=request.alias,
        repos=list(selected),
        skipped_worktrees=skipped_wt,
    )


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


def _reject_linked_worktree_source(repo_path: Path) -> None:
    if not git_adapter.is_linked_worktree(repo_path):
        return
    raise UsageError(
        f"Source repository '{repo_path}' is a linked worktree and cannot host new worktrees.",
        hint=(
            "Use the main clone/repository as --source, or omit "
            "--include-worktrees to skip linked worktrees."
        ),
    )


def _add_worktree_from_start_point(request: WorktreeRequest, *, create_branch: bool) -> None:
    git_adapter.add_worktree(
        request.repo_path,
        request.worktree_path,
        branch=request.target_branch,
        base=request.start_point,
        create_branch=create_branch,
    )


def _move_branch_into_worktree(request: WorktreeRequest, in_use: Path) -> str:
    """Move the branch (and its local changes) from *in_use* into the new worktree."""
    created = git_adapter.stash_push(
        in_use,
        include_untracked=True,
        message=f"repo-env move {request.move_context}",
    )
    if Path(in_use).resolve() == Path(request.repo_path).resolve():
        git_adapter.checkout(in_use, request.base)
    else:
        git_adapter.checkout(in_use, "--detach")
    git_adapter.add_worktree_existing_branch(request.repo_path, request.worktree_path, request.target_branch)
    if created:
        git_adapter.stash_pop(request.worktree_path)
    return f"moved branch '{request.target_branch}' from {in_use}"


def _resolve_branch_conflict(request: WorktreeRequest, in_use: Path) -> str:
    """Handle a target branch that is already checked out in *in_use*."""
    strategy = request.on_branch_conflict
    if strategy is BranchConflictStrategy.FAIL:
        raise UsageError(
            f"Branch '{request.target_branch}' is already checked out in {in_use}.",
            hint="Free the branch, or pass --on-branch-conflict=detach|move.",
        )
    if strategy is BranchConflictStrategy.MOVE:
        return _move_branch_into_worktree(request, in_use)
    _add_worktree_from_start_point(request, create_branch=False)
    return f"branch '{request.target_branch}' in use at {in_use}; created detached worktree"


def _create_or_attach_worktree(request: WorktreeRequest) -> str | None:
    """Ensure a worktree exists; return an optional note for the RepoEntry."""
    _reject_linked_worktree_source(request.repo_path)
    git_adapter.prune_worktrees(request.repo_path)
    if not request.preserve:
        git_adapter.fetch(request.repo_path, request.remote)

    if not request.create_branch:
        _add_worktree_from_start_point(request, create_branch=False)
        return None

    in_use = git_adapter.find_worktree_for_branch(request.repo_path, request.target_branch)
    if in_use is not None:
        return _resolve_branch_conflict(request, in_use)

    if git_adapter.branch_exists(request.repo_path, request.target_branch):
        git_adapter.add_worktree_existing_branch(
            request.repo_path, request.worktree_path, request.target_branch
        )
        return None

    _add_worktree_from_start_point(request, create_branch=True)
    return None


def _materialize_repo(job: _RepoJob, options: ExecuteOptions) -> RepoEntry:
    """Create the worktree for one repo and return its entry (FAILED on error)."""
    repo_path = job.source / job.repo_name
    worktree_path = job.env_path / job.repo_name
    create_branch = job.branch is not None
    resolved_base, target_branch = job.base_branch, job.branch
    already_exists = worktree_path.exists() and git_adapter.is_worktree_root(worktree_path)
    status, note = RepoStatus.OK, None
    try:
        if resolved_base is None:
            resolved_base = git_adapter.default_branch(repo_path, _REMOTE)
        if target_branch is None:
            target_branch = resolved_base
        if not already_exists:
            _ensure_worktree_path_is_clean(worktree_path)
            note = _create_or_attach_worktree(
                WorktreeRequest(
                    repo_path=repo_path,
                    worktree_path=worktree_path,
                    remote=_REMOTE,
                    base=resolved_base,
                    target_branch=target_branch,
                    create_branch=create_branch,
                    preserve=options.preserve,
                    on_branch_conflict=options.on_branch_conflict,
                    move_context=f"{job.env_name}/{job.repo_name}/{target_branch}",
                )
            )
    except Exception as exc:  # noqa: BLE001 - per-repo robustness
        status, note = RepoStatus.FAILED, f"failed: {exc}"
    base = resolved_base or "unknown"
    return RepoEntry(
        repo=job.repo_name,
        worktree_path=worktree_path,
        remote=_REMOTE,
        base=base,
        branch=target_branch or job.fallback_branch or base,
        branch_created=create_branch,
        source_sha=_resolve_source_sha(repo_path, remote=_REMOTE, base=base, preserve=options.preserve),
        status=status,
        note=note,
    )


def _run_jobs(jobs: list[_RepoJob], options: ExecuteOptions) -> Iterator[RepoEntry]:
    """Materialise *jobs* in order, reporting progress before each one."""
    total = len(jobs)
    for idx, job in enumerate(jobs, start=1):
        if options.on_repo_start is not None:
            options.on_repo_start(job.repo_name, idx, total)
        yield _materialize_repo(job, options)


def _ensure_destination_usable(env_path: Path) -> None:
    if not env_path.exists():
        return
    has_marker = any((env_path / m).exists() for m in _RENV_MARKER_FILENAMES)
    if not has_marker and any(env_path.iterdir()):
        raise UsageError(
            f"Destination '{env_path}' already exists and is not empty.",
            hint="Remove the directory manually, or run 'renv import' if it contains existing worktrees.",
        )


def execute_create_plan(plan: CreatePlan, *, options: ExecuteOptions | None = None) -> Environment:
    """Execute a validated plan: create worktrees and return the environment.

    See :class:`ExecuteOptions` for ``preserve``, the branch-conflict strategy
    and the progress callback.

    Raises :class:`~repoenv.errors.UsageError` if *plan.env_path* already exists
    on disk with content but without an renv marker (indicates a stale/conflicting
    directory that was not created by repo-env).
    """
    _ensure_destination_usable(plan.env_path)
    plan.env_path.mkdir(parents=True, exist_ok=True)
    env = Environment(
        name=plan.name,
        alias=plan.alias,
        path=plan.env_path,
        source=plan.source,
        base_branch=plan.base_branch,
    )
    jobs = [
        _RepoJob(
            env_name=plan.name,
            repo_name=repo_name,
            source=plan.source,
            env_path=plan.env_path,
            base_branch=plan.base_branch,
            branch=plan.branch_overrides.get(repo_name, plan.new_branch),
            fallback_branch=plan.new_branch,
        )
        for repo_name in plan.repos
    ]
    env.repos.extend(_run_jobs(jobs, options or ExecuteOptions()))
    return env


def failed_repos(env: Environment) -> list[str]:
    """Return repo names whose worktree creation failed."""
    return [entry.repo for entry in env.repos if entry.status is RepoStatus.FAILED]


def failure_details(env: Environment) -> list[tuple[str, str | None]]:
    """Return (repo, note) pairs for repos whose worktree creation failed."""
    return [(entry.repo, entry.note) for entry in env.repos if entry.status is RepoStatus.FAILED]


def infer_env_branch(env: Environment) -> str | None:
    """Best-effort: the task branch already in use by this environment's repos.

    Only considers repos where ``renv`` itself created the branch (as opposed
    to a detached checkout of the default branch), so ``add`` without
    ``--branch`` joins the same task branch instead of defaulting to detached.
    """
    counts = Counter(entry.branch for entry in env.repos if entry.branch_created and entry.branch)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def build_add_plan(
    *,
    env: Environment,
    include: list[str] | None,
    exclude: list[str] | None,
    include_worktrees: bool = False,
) -> AddPlan:
    """Validate inputs and build a plan to add repos into ``env``."""
    candidates = _discover_candidates(
        env.source, hint="Point source to a directory containing cloned repositories."
    )
    candidates, skipped_wt = _filter_candidates(
        source=env.source, candidates=candidates, dest=None, include_worktrees=include_worktrees
    )
    selected = _select_repos(candidates, env.source, include, exclude)
    if not selected:
        raise _nothing_matched(skipped_wt)

    existing = {entry.repo for entry in env.repos}
    plan = AddPlan(env_name=env.name, source=env.source, env_path=env.path, skipped_worktrees=skipped_wt)
    plan.skipped = {repo: "already present in environment" for repo in selected if repo in existing}
    plan.repos = [repo for repo in selected if repo not in existing]

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
    options: ExecuteOptions | None = None,
) -> Environment:
    """Execute a validated add plan and append new repo entries to ``env``.

    See :class:`ExecuteOptions` for ``preserve``, the branch-conflict strategy
    and the progress callback.
    """
    jobs = [
        _RepoJob(
            env_name=env.name,
            repo_name=repo_name,
            source=plan.source,
            env_path=plan.env_path,
            base_branch=env.base_branch,
            branch=branch,
            fallback_branch=branch,
        )
        for repo_name in plan.repos
    ]
    env.repos.extend(_run_jobs(jobs, options or ExecuteOptions()))
    env.touch()
    return env


def _carry_over_branches(
    left: Environment, right: Environment, merged: Iterable[str]
) -> tuple[dict[str, str], list[str]]:
    """Return ``(branch_overrides, branch_conflicts)`` for the merged repos."""
    left_branches = {entry.repo: entry.branch for entry in left.repos if entry.branch_created}
    right_branches = {entry.repo: entry.branch for entry in right.repos if entry.branch_created}

    branch_overrides: dict[str, str] = {}
    branch_conflicts: list[str] = []
    for repo in merged:
        left_branch = left_branches.get(repo)
        right_branch = right_branches.get(repo)
        chosen = left_branch or right_branch
        if chosen is not None:
            branch_overrides[repo] = chosen
        if left_branch is not None and right_branch is not None and left_branch != right_branch:
            branch_conflicts.append(
                f"{repo}: '{left_branch}' (from {left.name}) vs '{right_branch}' "
                f"(from {right.name}); using '{left_branch}'"
            )
    return branch_overrides, branch_conflicts


def build_merge_plan(*, left: Environment, right: Environment, op: SetOp, target: MergeTarget) -> CreatePlan:
    """Build a create plan by combining repo sets from two environments.

    Each repo keeps the task branch it already had in ``left``/``right`` (only
    real, ``renv``-created branches count -- a plain detached checkout at the
    default branch is not carried over). If a repo has a different branch on
    each side, ``left`` wins and the conflict is recorded in
    ``plan.branch_conflicts`` for the caller to report.
    """
    left_names = [entry.repo for entry in left.repos]
    right_names = [entry.repo for entry in right.repos]
    merged = set_combine(left_names, right_names, op)
    if not merged:
        raise NothingMatchedError(
            "Merge operation resulted in an empty repository set.",
            hint="Try a different set operation or source environments.",
        )

    plan = build_create_plan(
        CreateRequest(
            name=target.name,
            source=left.source,
            dest=target.dest_root,
            include=merged,
            alias=target.alias,
            default_branch=left.base_branch,
        )
    )
    plan.branch_overrides, plan.branch_conflicts = _carry_over_branches(left, right, merged)
    return plan
