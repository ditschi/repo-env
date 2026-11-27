"""Pull-request creation using clone's provider detection and credentials.

GitHub retains the gh CLI integration. Other providers use the shared,
redirect-safe REST transport and need no optional discovery client libraries.
"""

# aihealth: disable=primitive_obsession -- REST boundary: maps raw provider JSON, query dicts, branch names

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from repoenv.adapters import gh_adapter, git_adapter
from repoenv.adapters.scm import detect, rest
from repoenv.adapters.scm.base import ScmProvider
from repoenv.adapters.scm.credentials import Credential
from repoenv.domain.repo_url import parse_url, url_host
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError, UsageError


def _segment(value: str) -> str:
    return quote(value, safe="")


def _nested(item: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(item, dict):
            return None
        item = item.get(key)
    return item


@dataclass(frozen=True)
class PrOptions:
    """Optional PR metadata; not every provider supports every option."""

    draft: bool = False
    reviewers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrRequest:
    """One fully rendered pull request to create."""

    title: str
    body: str
    base: str
    head: str
    options: PrOptions = field(default_factory=PrOptions)


# Where each provider's PR JSON carries the web URL (Bitbucket Server: see ``_reported_url``).
_WEB_URL_KEYS: dict[ProviderKind, tuple[str, ...]] = {
    ProviderKind.GITLAB: ("web_url",),
    ProviderKind.GITEA: ("html_url",),
    ProviderKind.BITBUCKET_CLOUD: ("links", "html", "href"),
    ProviderKind.AZURE_DEVOPS: ("_links", "web", "href"),
}

# ``Authorization`` scheme per provider; GitLab uses ``PRIVATE-TOKEN`` instead.
_TOKEN_SCHEMES: dict[ProviderKind, str] = {
    ProviderKind.AZURE_DEVOPS: "Basic",
    ProviderKind.GITEA: "token",
}


def _unsupported_flags(kind: ProviderKind, options: PrOptions) -> list[str]:
    """Return the CLI flags a non-GitHub provider cannot honour."""
    unsupported = []
    if options.draft and kind not in (ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS):
        unsupported.append("--draft")
    metadata = (
        ("--reviewer", options.reviewers),
        ("--label", options.labels),
        ("--assignee", options.assignees),
    )
    unsupported.extend(flag for flag, values in metadata if values)
    return unsupported


class PullRequests:
    """PR operations for one fully resolved remote repository."""

    def __init__(self, provider: ScmProvider, owner: str, repo: str, worktree: Path) -> None:
        self.provider = provider
        self.owner = owner
        self.repo = repo
        self.worktree = worktree

    def validate_options(self, options: PrOptions) -> None:
        """Reject unsupported options before lookup, creation, or a caller's push."""
        kind = self.provider.kind
        if kind is ProviderKind.GITHUB:
            if not gh_adapter.is_available():
                raise UsageError(
                    "The GitHub CLI 'gh' is not available.",
                    hint="Install gh and run 'gh auth login' for GitHub/GHES pull requests.",
                )
            return
        unsupported = _unsupported_flags(kind, options)
        if unsupported:
            raise UsageError(
                f"{self.provider.label} PR creation does not support: {', '.join(unsupported)}.",
                hint="Omit these flags and set the corresponding metadata in the provider UI.",
            )

    @property
    def _github_repo(self) -> str:
        return f"{self.provider.host}/{self.owner}/{self.repo}"

    @property
    def _azure_owner_path(self) -> str:
        """``org/project`` with each segment URL-quoted."""
        return "/".join(_segment(part) for part in self.owner.split("/"))

    @property
    def _endpoint(self) -> str:
        base = self.provider.base_url
        owner, repo = _segment(self.owner), _segment(self.repo)
        kind = self.provider.kind
        if kind is ProviderKind.GITLAB:
            return f"{base}/api/v4/projects/{_segment(self.owner + '/' + self.repo)}/merge_requests"
        if kind is ProviderKind.BITBUCKET_CLOUD:
            if base == "https://bitbucket.org":
                base = "https://api.bitbucket.org"
            return f"{base}/2.0/repositories/{owner}/{repo}/pullrequests"
        if kind is ProviderKind.BITBUCKET_SERVER:
            return f"{base}/rest/api/1.0/projects/{owner}/repos/{repo}/pull-requests"
        if kind is ProviderKind.AZURE_DEVOPS:
            return f"{base}/{self._azure_owner_path}/_apis/git/repositories/{repo}/pullrequests"
        if kind is ProviderKind.GITEA:
            return f"{base}/api/v1/repos/{owner}/{repo}/pulls"
        raise UsageError(f"No REST PR endpoint for {self.provider.label}.")

    def _request(
        self, *, query: dict[str, str | int] | None = None, payload: dict[str, Any] | None = None
    ) -> tuple[Any, rest.HttpResponse]:
        provider = self.provider
        if provider.credential is None:
            raise GitError(
                f"{provider.label} PR operations on {provider.host} require authentication.",
                hint=provider.auth_hint(),
            )
        headers = self._auth_headers(provider.credential)
        url = self._endpoint + self._query_string(query)
        method = "POST" if payload is not None else "GET"
        response = rest.send(rest.HttpRequest(url, method=method, payload=payload, headers=headers))
        data = response.json()
        if not response.ok or not isinstance(data, (dict, list)):
            # Do not echo response bodies: they may contain credentials or private request data.
            raise GitError(
                f"{provider.label} PR API error on {provider.host} "
                f"({'creating' if payload is not None else 'listing'} PRs, HTTP {response.status}).",
                hint=provider.auth_hint(),
            )
        return data, response

    def _auth_headers(self, credential: Credential) -> dict[str, str]:
        kind = self.provider.kind
        if kind is ProviderKind.GITLAB:
            return {"PRIVATE-TOKEN": credential.secret}
        return rest.auth_headers(credential, token_scheme=_TOKEN_SCHEMES.get(kind, "Bearer"))

    def _query_string(self, query: dict[str, str | int] | None) -> str:
        params = dict(query or {})
        if self.provider.kind is ProviderKind.AZURE_DEVOPS:
            params["api-version"] = "7.1"
        return "?" + urlencode(params) if params else ""

    def _url(self, item: dict[str, Any]) -> str:
        url = self._reported_url(item)
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise GitError(f"{self.provider.label} PR API returned no valid web URL.")
        return url

    def _reported_url(self, item: dict[str, Any]) -> Any:
        """The web URL as the API reports it (unvalidated); Azure may only report the PR id."""
        kind = self.provider.kind
        if kind is ProviderKind.BITBUCKET_SERVER:
            links = _nested(item, "links", "self")
            return _nested(links[0], "href") if isinstance(links, list) and links else None
        keys = _WEB_URL_KEYS.get(kind)
        url = _nested(item, *keys) if keys else None
        if url or kind is not ProviderKind.AZURE_DEVOPS:
            return url
        return self._azure_web_url(item)

    def _azure_web_url(self, item: dict[str, Any]) -> str | None:
        pr_id = item.get("pullRequestId")
        if not isinstance(pr_id, int):
            return None
        repo = _segment(self.repo)
        return f"{self.provider.base_url}/{self._azure_owner_path}/_git/{repo}/pullrequest/{pr_id}"

    def _list_query(self, head: str) -> dict[str, str | int]:
        kind = self.provider.kind
        if kind is ProviderKind.GITLAB:
            return {"state": "opened", "source_branch": head, "per_page": 100}
        if kind is ProviderKind.BITBUCKET_CLOUD:
            return {"state": "OPEN", "pagelen": 100}
        if kind is ProviderKind.BITBUCKET_SERVER:
            return {"state": "OPEN", "direction": "OUTGOING", "at": f"refs/heads/{head}", "limit": 100}
        if kind is ProviderKind.AZURE_DEVOPS:
            return {
                "searchCriteria.status": "active",
                "searchCriteria.sourceRefName": f"refs/heads/{head}",
                "$top": 100,
            }
        return {"state": "open", "limit": 50}

    def _items(self, data: Any) -> list[dict[str, Any]]:
        kind = self.provider.kind
        if kind in (ProviderKind.GITLAB, ProviderKind.GITEA):
            items = data
        else:
            items = _nested(data, "value" if kind is ProviderKind.AZURE_DEVOPS else "values")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise GitError(f"{self.provider.label} PR API returned an invalid listing.")
        return items

    def _matches(self, item: dict[str, Any], head: str) -> bool:
        kind = self.provider.kind
        if kind is ProviderKind.BITBUCKET_CLOUD:
            branch = _nested(item, "source", "branch", "name")
        elif kind is ProviderKind.GITEA:
            branch = _nested(item, "head", "ref")
        else:
            return True  # These APIs filter by source branch server-side.
        if not isinstance(branch, str):
            raise GitError(f"{self.provider.label} PR API returned no source branch.")
        return branch == head

    def _advance(
        self, query: dict[str, str | int], data: Any, response: rest.HttpResponse, count: int
    ) -> bool:
        kind = self.provider.kind
        if kind is ProviderKind.BITBUCKET_SERVER:
            if data.get("isLastPage") is True:
                return False
            start = data.get("nextPageStart")
            if not isinstance(start, int) or start <= int(query.get("start", 0)):
                raise GitError("Bitbucket Server PR API returned invalid pagination.")
            query["start"] = start
        elif kind is ProviderKind.BITBUCKET_CLOUD:
            return bool(data.get("next"))
        elif kind is ProviderKind.GITLAB:
            return bool(response.headers.get("x-next-page"))
        elif kind is ProviderKind.AZURE_DEVOPS:
            query["$skip"] = int(query.get("$skip", 0)) + count
        return True

    def existing_url(self, *, head: str) -> str | None:
        """Find an open PR for the source branch; never treat API failure as absence."""
        if self.provider.kind is ProviderKind.GITHUB:
            return gh_adapter.existing_pr_url(self.worktree, head=head, repository=self._github_repo)
        query = self._list_query(head)
        page = 1
        while True:
            data, response = self._request(query={**query, "page": page})
            items = self._items(data)
            for item in items:
                if self._matches(item, head):
                    return self._url(item)
            if not items or not self._advance(query, data, response, len(items)):
                return None
            page += 1

    def create(self, request: PrRequest) -> str:
        """Create a PR; no method in this adapter pushes git branches."""
        options = request.options
        self.validate_options(options)
        if self.provider.kind is ProviderKind.GITHUB:
            pull_request = gh_adapter.GhPullRequest(
                title=request.title,
                body=request.body,
                head=request.head,
                base=request.base,
                draft=options.draft,
                reviewers=options.reviewers,
                labels=options.labels,
                assignees=options.assignees,
            )
            return gh_adapter.create_pr(self.worktree, pull_request, repository=self._github_repo)
        data, _ = self._request(payload=self._payload(request))
        if not isinstance(data, dict):
            raise GitError(f"{self.provider.label} PR API returned an invalid creation result.")
        return self._url(data)

    def _payload(self, request: PrRequest) -> dict[str, Any]:
        title, body, base, head = request.title, request.body, request.base, request.head
        draft = request.options.draft
        kind = self.provider.kind
        payload: dict[str, Any]
        if kind is ProviderKind.GITLAB:
            payload = {
                "title": f"Draft: {title}" if draft and not title.lower().startswith("draft:") else title,
                "description": body,
                "source_branch": head,
                "target_branch": base,
            }
        elif kind is ProviderKind.BITBUCKET_CLOUD:
            payload = {
                "title": title,
                "description": body,
                "source": {"branch": {"name": head}},
                "destination": {"branch": {"name": base}},
                "close_source_branch": False,
            }
        elif kind is ProviderKind.BITBUCKET_SERVER:
            repository = {"slug": self.repo, "project": {"key": self.owner}}
            payload = {
                "title": title,
                "description": body,
                "fromRef": {"id": f"refs/heads/{head}", "repository": repository},
                "toRef": {"id": f"refs/heads/{base}", "repository": repository},
            }
        elif kind is ProviderKind.AZURE_DEVOPS:
            payload = {
                "title": title,
                "description": body,
                "sourceRefName": f"refs/heads/{head}",
                "targetRefName": f"refs/heads/{base}",
                "isDraft": draft,
            }
        else:
            payload = {"title": title, "body": body, "head": head, "base": base}
        return payload


def _strip_context_path(url: str, base_url: str | None) -> str:
    """Drop a configured context path (e.g. ``/bitbucket``) so the URL parses like a root install."""
    prefix = urlsplit(base_url).path.rstrip("/") if base_url else ""
    if not prefix:
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https", "ssh") or not parts.path.startswith(prefix + "/"):
        return url
    return urlunsplit(parts._replace(path=parts.path[len(prefix) :]))


def for_worktree(worktree: Path, remote: str, *, settings: dict[str, str]) -> PullRequests:
    """Resolve the selected remote, including nested owners and configured context paths."""
    raw = git_adapter.remote_url(worktree, remote)
    host = url_host(raw)
    kind, base_url = detect.detect(host, override=None, settings=settings)
    if kind is None:
        raise UsageError(
            f"Could not determine which SCM provider serves {host}.",
            hint=f"Run 'renv config providers.{host} <kind>'.",
        )
    spec = parse_url(_strip_context_path(raw, base_url), kind)
    if spec.owner is None or spec.repo is None:
        raise UsageError(f"Remote '{remote}' in {worktree.name} is not a full repository URL.")
    return PullRequests(detect.make_provider(kind, host, base_url=base_url), spec.owner, spec.repo, worktree)
