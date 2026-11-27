"""PR service: bulk pull-request creation across an environment's worktrees."""

from __future__ import annotations

from dataclasses import dataclass, field

from repoenv.adapters import config_store, gh_adapter, git_adapter
from repoenv.adapters.scm import pull_requests
from repoenv.domain.models import Environment, RepoEntry
from repoenv.domain.selection import resolve_selection
from repoenv.errors import GitError, UsageError


@dataclass
class PrPlanItem:
    """One repo's resolved PR intent."""

    repo: str
    head: str
    base: str
    title: str
    body: str


@dataclass
class PrOutcome:
    """Aggregate result of a bulk PR run."""

    created: list[gh_adapter.PrResult] = field(default_factory=list)
    skipped: list[gh_adapter.PrResult] = field(default_factory=list)


@dataclass(frozen=True)
class PrBatch:
    """What ``renv pr`` should create and how to treat each selected repo."""

    title: str
    body: str = ""
    base: str | None = None
    options: pull_requests.PrOptions = field(default_factory=pull_requests.PrOptions)
    push: bool = False
    skip_no_diff: bool = False
    if_exists: str = "skip"
    include: list[str] | None = None
    exclude: list[str] | None = None


@dataclass(frozen=True)
class _Placeholders:
    """Values for the ``{repo}``/``{branch}``/``{env}`` placeholders of a PR title/body."""

    repo: str
    branch: str
    env: str

    def render(self, template: str) -> str:
        """Expand the placeholders in ``template``."""
        return template.format(repo=self.repo, branch=self.branch, env=self.env)


def _select_entries(env: Environment, batch: PrBatch) -> list[RepoEntry]:
    entries = list(env.repos)
    if batch.include is None and batch.exclude is None:
        return entries
    selected = set(resolve_selection([e.repo for e in entries], include=batch.include, exclude=batch.exclude))
    return [e for e in entries if e.repo in selected]


def _current_branch(entry: RepoEntry) -> str:
    return git_adapter.current_branch(entry.worktree_path) or entry.branch


def _plan_item(env: Environment, entry: RepoEntry, batch: PrBatch, head: str) -> PrPlanItem:
    placeholders = _Placeholders(repo=entry.repo, branch=head, env=env.name)
    return PrPlanItem(
        repo=entry.repo,
        head=head,
        base=batch.base or entry.base,
        title=placeholders.render(batch.title),
        body=placeholders.render(batch.body),
    )


def build_pr_preview(env: Environment, batch: PrBatch) -> list[PrPlanItem]:
    """Resolve the repos and rendered title/body/base without calling provider APIs.

    Applies the same --include/--exclude selection and {repo}/{branch}/{env}
    rendering as create_prs, so --dry-run accurately previews what would
    happen (including which repos are actually selected).
    """
    return [_plan_item(env, entry, batch, _current_branch(entry)) for entry in _select_entries(env, batch)]


def _skipped(entry: RepoEntry, url: str, reason: str) -> gh_adapter.PrResult:
    return gh_adapter.PrResult(entry.repo, url, created=False, skipped=True, reason=reason)


def _lacks_diff(entry: RepoEntry, batch: PrBatch) -> bool:
    """True when the worktree has no changes against the PR base branch."""
    return not git_adapter.has_diff(entry.worktree_path, f"{entry.remote}/{batch.base or entry.base}")


def _create_one(
    env: Environment, entry: RepoEntry, client: pull_requests.PullRequests, batch: PrBatch
) -> gh_adapter.PrResult:
    """Create (or skip) the PR for one repo, pushing first only when asked to."""
    worktree = entry.worktree_path
    branch = _current_branch(entry)
    if batch.skip_no_diff and _lacks_diff(entry, batch):
        return _skipped(entry, "", "no diff")

    existing = client.existing_url(head=branch)
    if existing and batch.if_exists == "fail":
        raise GitError(f"An open PR already exists for {entry.repo} on {branch}: {existing}")
    if existing:
        return _skipped(entry, existing, "exists")

    if batch.push:
        git_adapter.push(worktree, remote=entry.remote, branch=branch)

    item = _plan_item(env, entry, batch, branch)
    url = client.create(
        pull_requests.PrRequest(
            title=item.title, body=item.body, base=item.base, head=branch, options=batch.options
        )
    )
    return gh_adapter.PrResult(entry.repo, url, created=True)


def create_prs(env: Environment, batch: PrBatch) -> PrOutcome:
    """Create PRs for each repo in ``env``. Never pushes unless ``batch.push`` is True."""
    if batch.if_exists not in ("skip", "fail"):
        raise UsageError("--if-exists must be 'skip' or 'fail'.")
    entries = _select_entries(env, batch)

    settings = config_store.load_config().providers
    clients = {
        entry.repo: pull_requests.for_worktree(entry.worktree_path, entry.remote, settings=settings)
        for entry in entries
    }
    for client in clients.values():
        client.validate_options(batch.options)

    outcome = PrOutcome()
    for entry in entries:
        result = _create_one(env, entry, clients[entry.repo], batch)
        (outcome.created if result.created else outcome.skipped).append(result)
    return outcome
