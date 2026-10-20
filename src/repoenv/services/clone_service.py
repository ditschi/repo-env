"""Service for ``renv clone``: resolve remote repos, then clone/update them locally.

Two independent phases:

1. **Resolve** (:func:`resolve_clone_targets`) -- turn ``--url``/``--include``/
   ``--exclude``/``--role`` into a concrete list of :class:`ResolvedRepo`
   (host, owner, repo, clone URL), calling the host's SCM API (GitHub,
   GitLab, Bitbucket, Azure DevOps, Gitea) only when a wildcard forces
   discovery.
2. **Execute** (:func:`clone_or_update`) -- for each resolved repo, clone it
   if missing, or apply ``--update``/``--reset-default``/``--force`` if it
   already exists under ``--source``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from repoenv.adapters import git_adapter
from repoenv.adapters.scm import detect
from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider
from repoenv.domain.owner_repo import (
    expand_owner_repo_patterns,
    has_wildcard,
    match_owner_repo,
    root_owner,
    search_hint,
)
from repoenv.domain.repo_url import UrlSpec, build_clone_url, parse_url, url_host
from repoenv.domain.scm import NESTED_OWNER_KINDS, ProviderKind
from repoenv.domain.selection import split_csv
from repoenv.errors import GitError, NothingMatchedError, UsageError

_Pattern = tuple[str, str]


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
    ctx: _HostContext, *, role: Role, role_explicit: bool
) -> tuple[list[OrgMembership], list[OrgMembership], bool]:
    """Return ``(selected memberships, all memberships, fell_back_to_any)``.

    If the default role (``member``) finds nothing and the caller didn't pass
    ``--role`` explicitly, automatically retries with ``any`` rather than
    failing outright -- see the module docstring on ``Role``.
    """
    memberships = ctx.provider().list_memberships()
    selected = _filter_memberships(memberships, role)
    fell_back = False
    if not selected and not role_explicit and role is not Role.ANY:
        selected = _filter_memberships(memberships, Role.ANY)
        fell_back = True
    if not selected:
        raise NothingMatchedError(
            f"No organizations found on {ctx.host} for --role {role.value}.",
            hint=f"Check your credentials for {ctx.host} ({ctx.provider().auth_hint()}), "
            "or use a literal owner in --include to bypass membership lookup entirely.",
        )
    return selected, memberships, fell_back


class _HostContext:
    """Provider kind of one host plus its adapter and listing cache, created on demand."""

    def __init__(self, host: str, kind: ProviderKind | None, base_url: str | None) -> None:
        self.host = host
        self.kind = kind
        self.base_url = base_url
        self._provider: ScmProvider | None = None
        self._listings: dict[tuple[str, str | None], list[RemoteRepo]] = {}
        self._default_protocol: str | None = None

    def protocol(self, explicit: str | None) -> str:
        """``explicit`` if given, else the provider's default (looked up once per host)."""
        if explicit:
            return explicit
        if self._default_protocol is None:
            self._default_protocol = self.provider().default_protocol() if self.kind else "ssh"
        return self._default_protocol

    def provider(self) -> ScmProvider:
        if self.kind is None:
            kinds = ", ".join(kind.value for kind in ProviderKind)
            raise UsageError(
                f"Could not determine which SCM provider serves {self.host}.",
                hint=f"Pass --provider <kind> or run 'renv config providers.{self.host} <kind>' ({kinds}).",
            )
        if self._provider is None:
            self._provider = detect.make_provider(self.kind, self.host, base_url=self.base_url)
        return self._provider

    def list_repos(self, owner: str, name_hint: str | None) -> list[RemoteRepo]:
        key = (owner, name_hint)
        if key not in self._listings:
            self._listings[key] = self.provider().list_repos(owner, name_hint=name_hint)
        return self._listings[key]


def _scope_to_owner(owner: str, patterns: list[_Pattern], *, nested: bool) -> list[_Pattern]:
    """Pin patterns to the owner given in ``--url`` (and its subgroups/projects when ``nested``)."""
    scoped: list[_Pattern] = []
    for owner_glob, repo_glob in patterns:
        if fnmatch(owner, owner_glob):
            scoped.append((owner, repo_glob))
            if nested:
                scoped.append((f"{owner}/*", repo_glob))
        elif nested and owner_glob.startswith(f"{owner}/"):
            scoped.append((owner_glob, repo_glob))
    return scoped


@dataclass
class _Discovery:
    roots: dict[str, list[_Pattern]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    skipped_owners: list[str] = field(default_factory=list)


def _discovery_roots(
    ctx: _HostContext, patterns: list[_Pattern], *, role: Role, role_explicit: bool
) -> _Discovery:
    """Group wildcard patterns by the top-level owner whose repos must be listed."""
    found = _Discovery()
    wildcard_root: list[_Pattern] = []
    for owner_glob, repo_glob in patterns:
        root = root_owner(owner_glob)
        if has_wildcard(root):
            wildcard_root.append((owner_glob, repo_glob))
        else:
            found.roots.setdefault(root, []).append((owner_glob, repo_glob))
    if not wildcard_root:
        return found

    selected, memberships, fell_back = _resolve_candidate_owners(ctx, role=role, role_explicit=role_explicit)
    if fell_back:
        found.warnings.append(
            f"No organizations on {ctx.host} matched --role {role.value}; "
            "automatically retried with --role any."
        )
    selected_logins = {m.login for m in selected}
    for login in sorted(selected_logins):
        for owner_glob, repo_glob in wildcard_root:
            if fnmatch(login, root_owner(owner_glob)):
                found.roots.setdefault(login, []).append((owner_glob, repo_glob))
    found.skipped_owners = sorted(
        m.login
        for m in memberships
        if m.login not in selected_logins and any(fnmatch(m.login, root_owner(o)) for o, _ in wildcard_root)
    )
    return found


def _discover(
    ctx: _HostContext, discovery: _Discovery, *, role: Role, protocol: str
) -> tuple[dict[tuple[str, str], str], list[str]]:
    """List each discovery root once and keep the repos matching its patterns."""
    found: dict[tuple[str, str], str] = {}
    for root, root_patterns in discovery.roots.items():
        repo_globs = {repo_glob for _, repo_glob in root_patterns}
        hint = None
        if len(repo_globs) == 1 and ctx.provider().supports_name_hint:
            hint = search_hint(next(iter(repo_globs)))
        for remote in ctx.list_repos(root, hint):
            if match_owner_repo(remote.owner, remote.name, root_patterns):
                found[(remote.owner, remote.name)] = remote.clone_url(protocol)
    warnings = list(discovery.warnings)
    if found and discovery.skipped_owners:
        warnings.append(
            f"Skipped {len(discovery.skipped_owners)} organization(s) on {ctx.host} without "
            f"'{role.value}' access: {', '.join(discovery.skipped_owners)} (use --role any to include them)."
        )
    return found, warnings


def _resolve_host_spec(
    spec: UrlSpec,
    ctx: _HostContext,
    *,
    include_patterns: list[_Pattern],
    exclude_patterns: list[_Pattern],
    role: Role,
    role_explicit: bool,
    protocol: str,
) -> tuple[dict[tuple[str, str], str], list[str]]:
    """Resolve one host-only/host+owner ``--url`` entry to ``{(owner, repo): clone_url}``."""
    patterns = include_patterns
    if spec.owner:
        patterns = _scope_to_owner(spec.owner, patterns, nested=ctx.kind in NESTED_OWNER_KINDS)

    found: dict[tuple[str, str], str] = {}
    to_discover: list[_Pattern] = []
    for owner_glob, repo_glob in patterns:
        if has_wildcard(owner_glob) or has_wildcard(repo_glob):
            to_discover.append((owner_glob, repo_glob))
        else:
            found[(owner_glob, repo_glob)] = build_clone_url(
                spec.host, owner_glob, repo_glob, protocol=protocol, kind=ctx.kind
            )

    warnings: list[str] = []
    if to_discover:
        discovery = _discovery_roots(ctx, to_discover, role=role, role_explicit=role_explicit)
        discovered, warnings = _discover(ctx, discovery, role=role, protocol=protocol)
        found.update(discovered)

    found = {key: url for key, url in found.items() if not match_owner_repo(*key, exclude_patterns)}
    return found, warnings


def _resolve_url(
    raw_url: str,
    ctx: _HostContext,
    *,
    include_patterns: list[_Pattern],
    exclude_patterns: list[_Pattern],
    role: Role,
    role_explicit: bool,
    protocol: str,
) -> tuple[dict[tuple[str, str], str], list[str]]:
    spec = parse_url(raw_url, ctx.kind)
    if spec.owner is None or spec.repo is None:
        return _resolve_host_spec(
            spec,
            ctx,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            role=role,
            role_explicit=role_explicit,
            protocol=protocol,
        )
    selected = match_owner_repo(spec.owner, spec.repo, include_patterns) and not match_owner_repo(
        spec.owner, spec.repo, exclude_patterns
    )
    if not selected:
        return {}, []
    return {
        (spec.owner, spec.repo): build_clone_url(
            spec.host, spec.owner, spec.repo, protocol=protocol, kind=ctx.kind
        )
    }, []


def resolve_clone_targets(
    *,
    urls: list[str],
    include: list[str],
    exclude: list[str],
    role: Role = Role.MEMBER,
    role_explicit: bool = False,
    protocol: str | None = None,
    provider: ProviderKind | None = None,
    provider_settings: dict[str, str] | None = None,
) -> ResolveResult:
    """Resolve ``--url``/``--include``/``--exclude``/``--role`` into clone targets.

    ``protocol`` ('ssh'/'https') is applied to every resolved repo when
    given; otherwise each host's provider picks its default (GitHub: gh's
    ``git_protocol`` when gh is installed; others: ssh). ``provider`` forces
    the provider kind for every host; ``provider_settings`` is the
    ``providers.<host>`` config mapping (``"<kind> [<base-url>]"``).
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
    contexts: dict[str, _HostContext] = {}

    for raw_url in url_values:
        host = url_host(raw_url)
        if host not in contexts:
            kind, base_url = detect.detect(host, override=provider, settings=provider_settings or {})
            contexts[host] = _HostContext(host, kind, base_url)
        ctx = contexts[host]
        found, url_warnings = _resolve_url(
            raw_url,
            ctx,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            role=role,
            role_explicit=role_explicit,
            protocol=ctx.protocol(protocol),
        )
        warnings.extend(url_warnings)
        for (owner, repo), clone_url in found.items():
            resolved.setdefault(
                (host, owner, repo), ResolvedRepo(host=host, owner=owner, repo=repo, clone_url=clone_url)
            )

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
