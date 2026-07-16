"""Service for ``renv clone``: resolve remote repos, then clone/update them locally.

Two independent phases:

1. **Resolve** (:func:`resolve_clone_targets`) -- turn ``--url``/``--include``/
   ``--exclude``/``--role`` into a concrete list of :class:`ResolvedRepo`
   (host, owner, repo, clone URL), calling the GitHub API only when a
   wildcard forces discovery.
2. **Execute** (:func:`clone_or_update`) -- for each resolved repo, clone it
   if missing, or apply ``--update``/``--reset-default``/``--force`` if it
   already exists under ``--source``.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from repoenv.adapters import gh_adapter, git_adapter
from repoenv.adapters.gh_adapter import OrgMembership
from repoenv.domain.owner_repo import expand_owner_repo_patterns, has_wildcard, match_owner_repo
from repoenv.domain.repo_url import UrlSpec, build_clone_url, parse_url
from repoenv.domain.selection import split_csv
from repoenv.errors import GitError, NothingMatchedError, UsageError


class Role(str, Enum):
    """Which org memberships count as candidate owners for a wildcard owner glob.

    - ``member``: any *active* membership, regardless of your role in the org
      (the default -- "orgs you actively belong to").
    - ``owner``: only orgs where your role is ``admin`` (GitHub's "Owner").
    - ``any``: active *and* pending memberships, any role -- the broadest set.
    """

    MEMBER = "member"
    OWNER = "owner"
    ANY = "any"


@dataclass(frozen=True)
class ResolvedRepo:
    """One repository resolved to an exact clone target."""

    host: str
    owner: str
    repo: str
    clone_url: str

    @property
    def relative_path(self) -> str:
        """Path under ``--source`` this repo lives at: ``host/owner/repo``."""
        return f"{self.host}/{self.owner}/{self.repo}"


@dataclass
class ResolveResult:
    """Output of resolving ``--url``/``--include``/``--exclude``/``--role``."""

    repos: list[ResolvedRepo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Action(str, Enum):
    """Outcome of processing one resolved repo."""

    CLONED = "cloned"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class CloneOutcome:
    """Outcome of :func:`clone_or_update` for one repo."""

    repo: ResolvedRepo
    action: Action
    detail: str = ""


def _filter_memberships(memberships: list[OrgMembership], role: Role) -> list[OrgMembership]:
    if role is Role.OWNER:
        return [m for m in memberships if m.role == "admin" and m.state == "active"]
    if role is Role.MEMBER:
        return [m for m in memberships if m.state == "active"]
    return list(memberships)  # ANY: active + pending, any role


def _resolve_candidate_owners(
    host: str, *, role: Role, role_explicit: bool
) -> tuple[list[OrgMembership], list[OrgMembership], bool]:
    """Return ``(selected memberships, all memberships, fell_back_to_any)``.

    If the default role (``member``) finds nothing and the caller didn't pass
    ``--role`` explicitly, automatically retries with ``any`` rather than
    failing outright -- see the module docstring on ``Role``.
    """
    memberships = gh_adapter.list_org_memberships(host=host)
    selected = _filter_memberships(memberships, role)
    fell_back = False
    if not selected and not role_explicit and role is not Role.ANY:
        selected = _filter_memberships(memberships, Role.ANY)
        fell_back = True
    if not selected:
        raise NothingMatchedError(
            f"No organizations found on {host} for --role {role.value}.",
            hint="Run 'gh auth status' (use 'gh auth login --hostname <host>' for enterprise hosts), "
            "or use a literal owner in --include to bypass org membership entirely.",
        )
    return selected, memberships, fell_back


def _repos_for_owner(host: str, owner: str, repo_globs: list[str]) -> list[str]:
    """Resolve which of ``owner``'s repos match ``repo_globs`` (OR-ed)."""
    literal = [glob for glob in repo_globs if not has_wildcard(glob)]
    wildcard = [glob for glob in repo_globs if has_wildcard(glob)]
    repos = list(dict.fromkeys(literal))
    if wildcard:
        available = gh_adapter.list_owner_repos(owner, host=host)
        repos.extend(name for name in available if any(fnmatch(name, glob) for glob in wildcard))
    return repos


def _repo_globs_by_owner(owner_repo_pairs: list[tuple[str, str]], owners: list[str]) -> dict[str, list[str]]:
    by_owner: dict[str, list[str]] = {}
    for owner in owners:
        for owner_glob, repo_glob in owner_repo_pairs:
            if fnmatch(owner, owner_glob):
                by_owner.setdefault(owner, []).append(repo_glob)
    return by_owner


def _resolve_host_spec(
    spec: UrlSpec,
    *,
    include_patterns: list[tuple[str, str]],
    exclude_patterns: list[tuple[str, str]],
    role: Role,
    role_explicit: bool,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Resolve one host-only/host+owner ``--url`` entry to ``(owner, repo)`` pairs."""
    patterns = include_patterns
    if spec.owner:
        # The URL already pins the owner; only the repo-glob side of patterns
        # whose owner-glob matches it still applies.
        patterns = [
            (spec.owner, repo_glob) for owner_glob, repo_glob in patterns if fnmatch(spec.owner, owner_glob)
        ]

    literal_owner_patterns = [(o, r) for o, r in patterns if not has_wildcard(o)]
    wildcard_owner_patterns = [(o, r) for o, r in patterns if has_wildcard(o)]

    warnings: list[str] = []
    pairs: list[tuple[str, str]] = []

    literal_owners = list(dict.fromkeys(owner for owner, _ in literal_owner_patterns))
    for owner, repo_globs in _repo_globs_by_owner(literal_owner_patterns, literal_owners).items():
        pairs.extend((owner, repo) for repo in _repos_for_owner(spec.host, owner, repo_globs))

    if wildcard_owner_patterns:
        selected, memberships, fell_back = _resolve_candidate_owners(
            spec.host, role=role, role_explicit=role_explicit
        )
        if fell_back:
            warnings.append(
                f"No organizations on {spec.host} matched --role {role.value}; "
                "automatically retried with --role any."
            )

        selected_logins = {m.login for m in selected}
        matched_owners = [
            login
            for login in sorted(selected_logins)
            if any(fnmatch(login, owner_glob) for owner_glob, _ in wildcard_owner_patterns)
        ]

        wildcard_pairs: list[tuple[str, str]] = []
        for owner, repo_globs in _repo_globs_by_owner(wildcard_owner_patterns, matched_owners).items():
            wildcard_pairs.extend((owner, repo) for repo in _repos_for_owner(spec.host, owner, repo_globs))

        if wildcard_pairs:
            skipped = sorted(
                m.login
                for m in memberships
                if m.login not in selected_logins
                and any(fnmatch(m.login, owner_glob) for owner_glob, _ in wildcard_owner_patterns)
            )
            if skipped:
                warnings.append(
                    f"Skipped {len(skipped)} organization(s) on {spec.host} without "
                    f"'{role.value}' access: {', '.join(skipped)} (use --role any to include them)."
                )

        pairs.extend(wildcard_pairs)

    if exclude_patterns:
        pairs = [
            (owner, repo) for owner, repo in pairs if not match_owner_repo(owner, repo, exclude_patterns)
        ]

    return sorted(set(pairs)), warnings


def _record_fully_qualified(
    spec: UrlSpec,
    *,
    include_patterns: list[tuple[str, str]],
    exclude_patterns: list[tuple[str, str]],
    record: Callable[[str, str, str], None],
) -> None:
    assert spec.owner is not None and spec.repo is not None
    if not match_owner_repo(spec.owner, spec.repo, include_patterns):
        return
    if exclude_patterns and match_owner_repo(spec.owner, spec.repo, exclude_patterns):
        return
    record(spec.host, spec.owner, spec.repo)


def resolve_clone_targets(
    *,
    urls: list[str],
    include: list[str],
    exclude: list[str],
    role: Role = Role.MEMBER,
    role_explicit: bool = False,
    protocol: str | None = None,
) -> ResolveResult:
    """Resolve ``--url``/``--include``/``--exclude``/``--role`` into clone targets.

    ``protocol`` ('ssh'/'https') is applied to every resolved repo when
    given; otherwise it's looked up per host via ``gh config get
    git_protocol`` (cached so each host is only queried once).
    """
    url_values = split_csv(urls)
    if not url_values:
        raise UsageError(
            "At least one --url is required.",
            hint="e.g. --url https://github.com --include 'myorg/*'.",
        )

    include_patterns = expand_owner_repo_patterns(include) if include else [("*", "*")]
    exclude_patterns = expand_owner_repo_patterns(exclude)

    warnings: list[str] = []
    resolved: dict[tuple[str, str, str], ResolvedRepo] = {}
    protocol_by_host: dict[str, str] = {}

    def _protocol_for(host: str) -> str:
        if protocol:
            return protocol
        if host not in protocol_by_host:
            protocol_by_host[host] = gh_adapter.git_protocol(host)
        return protocol_by_host[host]

    def _record(host: str, owner: str, repo: str) -> None:
        key = (host, owner, repo)
        if key in resolved:
            return
        resolved[key] = ResolvedRepo(
            host=host,
            owner=owner,
            repo=repo,
            clone_url=build_clone_url(host, owner, repo, protocol=_protocol_for(host)),
        )

    for raw_url in url_values:
        spec = parse_url(raw_url)

        if spec.is_fully_qualified:
            _record_fully_qualified(
                spec,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                record=_record,
            )
            continue

        pairs, host_warnings = _resolve_host_spec(
            spec,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            role=role,
            role_explicit=role_explicit,
        )
        warnings.extend(host_warnings)
        for owner, repo in pairs:
            _record(spec.host, owner, repo)

    repos = sorted(resolved.values(), key=lambda r: (r.host, r.owner, r.repo))
    return ResolveResult(repos=repos, warnings=warnings)


def _sync_existing_repo(
    repo: ResolvedRepo,
    dest: Path,
    *,
    update: bool,
    reset_default: bool,
    force: bool,
) -> CloneOutcome:
    git_adapter.fetch(dest, "origin")

    if not git_adapter.is_clean(dest) and not force:
        return CloneOutcome(repo, Action.SKIPPED, "local changes present (use --force to override)")

    details: list[str] = []

    if reset_default:
        default = git_adapter.default_branch(dest, "origin")
        git_adapter.checkout_tracking(dest, default, remote="origin", force=force)
        details.append(f"checked out '{default}'")

    if update:
        branch = git_adapter.current_branch(dest)
        if branch is None:
            return CloneOutcome(
                repo, Action.SKIPPED, "detached HEAD; use --reset-default to pick a branch first"
            )
        upstream = f"origin/{branch}"
        if force:
            git_adapter.reset_hard(dest, upstream)
            details.append(f"reset to '{upstream}'")
        elif git_adapter.fast_forward(dest, upstream):
            details.append(f"fast-forwarded to '{upstream}'")
        else:
            return CloneOutcome(repo, Action.SKIPPED, f"diverged from '{upstream}' (use --force)")

    return CloneOutcome(repo, Action.UPDATED, "; ".join(details))


def clone_or_update(
    repo: ResolvedRepo,
    *,
    source: Path,
    update: bool,
    reset_default: bool,
    force: bool,
) -> CloneOutcome:
    """Clone ``repo`` if missing under ``source``, else apply update/reset-default/force."""
    dest = source / repo.relative_path

    if not git_adapter.is_git_repo(dest):
        try:
            git_adapter.clone(repo.clone_url, dest)
        except GitError as exc:
            return CloneOutcome(repo, Action.FAILED, str(exc))
        return CloneOutcome(repo, Action.CLONED, str(dest))

    if not (update or reset_default):
        return CloneOutcome(
            repo, Action.UNCHANGED, "already present; pass --update/--reset-default to sync it"
        )

    try:
        return _sync_existing_repo(repo, dest, update=update, reset_default=reset_default, force=force)
    except GitError as exc:
        return CloneOutcome(repo, Action.FAILED, str(exc))


def execute_clone_plan(
    repos: list[ResolvedRepo],
    *,
    source: Path,
    update: bool,
    reset_default: bool,
    force: bool,
    jobs: int = 1,
) -> list[CloneOutcome]:
    """Clone/update every repo in ``repos``, in parallel when ``jobs > 1``."""

    def _task(repo: ResolvedRepo) -> CloneOutcome:
        return clone_or_update(repo, source=source, update=update, reset_default=reset_default, force=force)

    if jobs <= 1:
        return [_task(repo) for repo in repos]

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        outcomes = list(pool.map(_task, repos))
    return sorted(outcomes, key=lambda o: (o.repo.host, o.repo.owner, o.repo.repo))
