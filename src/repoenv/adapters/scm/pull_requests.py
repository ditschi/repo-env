"""Pull-request creation using clone's provider detection and credentials.

GitHub retains the gh CLI integration. Other providers use the shared,
redirect-safe REST transport and need no optional discovery client libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from repoenv.adapters import gh_adapter, git_adapter
from repoenv.adapters.scm import detect, rest
from repoenv.adapters.scm.base import ScmProvider
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


class PullRequests:
    """PR operations for one fully resolved remote repository."""

    def __init__(self, provider: ScmProvider, owner: str, repo: str, worktree: Path) -> None:
        self.provider = provider
        self.owner = owner
        self.repo = repo
        self.worktree = worktree

    def validate_options(
        self, *, draft: bool, reviewers: list[str], labels: list[str], assignees: list[str]
    ) -> None:
        """Reject unsupported options before lookup, creation, or a caller's push."""
        kind = self.provider.kind
        if kind is ProviderKind.GITHUB:
            if not gh_adapter.is_available():
                raise UsageError(
                    "The GitHub CLI 'gh' is not available.",
                    hint="Install gh and run 'gh auth login' for GitHub/GHES pull requests.",
                )
            return
        unsupported = []
        if draft and kind not in (ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS):
            unsupported.append("--draft")
        for flag, values in (("--reviewer", reviewers), ("--label", labels), ("--assignee", assignees)):
            if values:
                unsupported.append(flag)
        if unsupported:
            raise UsageError(
                f"{self.provider.label} PR creation does not support: {', '.join(unsupported)}.",
                hint="Omit these flags and set the corresponding metadata in the provider UI.",
            )

    @property
    def _github_repo(self) -> str:
        return f"{self.provider.host}/{self.owner}/{self.repo}"

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
            path = "/".join(_segment(part) for part in self.owner.split("/"))
            return f"{base}/{path}/_apis/git/repositories/{repo}/pullrequests"
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
        scheme = "Basic" if provider.kind is ProviderKind.AZURE_DEVOPS else "Bearer"
        if provider.kind is ProviderKind.GITEA:
            scheme = "token"
        headers = rest.auth_headers(provider.credential, token_scheme=scheme)
        if provider.kind is ProviderKind.GITLAB:
            headers = {"PRIVATE-TOKEN": provider.credential.secret}
        params = dict(query or {})
        if provider.kind is ProviderKind.AZURE_DEVOPS:
            params["api-version"] = "7.1"
        url = self._endpoint + ("?" + urlencode(params) if params else "")
        response = rest.request(
            url, method="POST" if payload is not None else "GET", payload=payload, headers=headers
        )
        data = response.json()
        if not response.ok or not isinstance(data, (dict, list)):
            # Do not echo response bodies: they may contain credentials or private request data.
            raise GitError(
                f"{provider.label} PR API error on {provider.host} "
                f"({'creating' if payload is not None else 'listing'} PRs, HTTP {response.status}).",
                hint=provider.auth_hint(),
            )
        return data, response

    def _url(self, item: dict[str, Any]) -> str:
        kind = self.provider.kind
        url: Any = None
        if kind is ProviderKind.GITLAB:
            url = item.get("web_url")
        elif kind is ProviderKind.GITEA:
            url = item.get("html_url")
        elif kind is ProviderKind.BITBUCKET_CLOUD:
            url = _nested(item, "links", "html", "href")
        elif kind is ProviderKind.BITBUCKET_SERVER:
            links = _nested(item, "links", "self")
            url = _nested(links[0], "href") if isinstance(links, list) and links else None
        elif kind is ProviderKind.AZURE_DEVOPS:
            url = _nested(item, "_links", "web", "href")
            if not url and isinstance(item.get("pullRequestId"), int):
                path = "/".join(_segment(part) for part in self.owner.split("/"))
                url = (
                    f"{self.provider.base_url}/{path}/_git/{_segment(self.repo)}"
                    f"/pullrequest/{item['pullRequestId']}"
                )
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise GitError(f"{self.provider.label} PR API returned no valid web URL.")
        return url

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

    def create(
        self,
        *,
        title: str,
        body: str,
        base: str,
        head: str,
        draft: bool,
        reviewers: list[str],
        labels: list[str],
        assignees: list[str],
    ) -> str:
        """Create a PR; no method in this adapter pushes git branches."""
        self.validate_options(draft=draft, reviewers=reviewers, labels=labels, assignees=assignees)
        kind = self.provider.kind
        if kind is ProviderKind.GITHUB:
            return gh_adapter.create_pr(
                self.worktree,
                title=title,
                body=body,
                base=base,
                head=head,
                draft=draft,
                reviewers=reviewers,
                labels=labels,
                assignees=assignees,
                repository=self._github_repo,
            )
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
        data, _ = self._request(payload=payload)
        if not isinstance(data, dict):
            raise GitError(f"{self.provider.label} PR API returned an invalid creation result.")
        return self._url(data)


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
    if base_url:
        parts = urlsplit(raw)
        prefix = urlsplit(base_url).path.rstrip("/")
        if parts.scheme in ("http", "https", "ssh") and prefix and parts.path.startswith(prefix + "/"):
            raw = urlunsplit(parts._replace(path=parts.path[len(prefix) :]))
    spec = parse_url(raw, kind)
    if spec.owner is None or spec.repo is None:
        raise UsageError(f"Remote '{remote}' in {worktree.name} is not a full repository URL.")
    return PullRequests(detect.make_provider(kind, host, base_url=base_url), spec.owner, spec.repo, worktree)
