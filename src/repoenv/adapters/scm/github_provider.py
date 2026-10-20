"""GitHub.com and GitHub Enterprise Server discovery via PyGithub.

Authenticated listings use one GraphQL query per 100 repositories that
returns only name + clone URLs (GitHub has no server-side glob filter, so
this is the cheapest full listing). Anonymous access falls back to REST,
since GitHub's GraphQL API always requires a token.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

from repoenv.adapters import gh_adapter
from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider, missing_extra
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError

if TYPE_CHECKING:
    from github import Github

_REPOS_QUERY = """
query($owner: String!, $cursor: String) {
  repositoryOwner(login: $owner) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      nodes { name url sshUrl }
    }
  }
}
"""


class GitHubProvider(ScmProvider):
    """GitHub / GitHub Enterprise Server."""

    kind = ProviderKind.GITHUB
    label = "GitHub"

    def _api_url(self) -> str:
        if self.base_url == "https://github.com":
            return "https://api.github.com"
        return f"{self.base_url}/api/v3"

    def _client(self) -> Github:
        try:
            from github import Auth, Github
        except ImportError as exc:
            raise missing_extra("github", self.label) from exc
        auth = Auth.Token(self.credential.secret) if self.credential else None
        # GraphQL reads are POSTs, which PyGithub would otherwise throttle as writes (1s apart).
        return Github(
            base_url=self._api_url(),
            auth=auth,
            per_page=100,
            seconds_between_requests=None,
            seconds_between_writes=None,
        )

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        client = self._client()
        from github import GithubException

        try:
            if self.credential is None:
                return self._list_repos_rest(client, owner)
            return self._list_repos_graphql(client, owner)
        except GithubException as exc:
            raise self.api_error(f"listing repositories of '{owner}'", exc) from exc

    def _list_repos_graphql(self, client: Github, owner: str) -> list[RemoteRepo]:
        repos: list[RemoteRepo] = []
        cursor: str | None = None
        while True:
            _, payload = client.requester.graphql_query(_REPOS_QUERY, {"owner": owner, "cursor": cursor})
            node: dict[str, Any] | None = payload["data"]["repositoryOwner"]
            if node is None:
                raise GitError(f"No GitHub user or organization '{owner}' on {self.host}.")
            connection = node["repositories"]
            repos.extend(
                RemoteRepo(
                    owner=owner, name=item["name"], https_url=f"{item['url']}.git", ssh_url=item["sshUrl"]
                )
                for item in connection["nodes"]
            )
            if not connection["pageInfo"]["hasNextPage"]:
                return repos
            cursor = connection["pageInfo"]["endCursor"]

    def _list_repos_rest(self, client: Github, owner: str) -> list[RemoteRepo]:
        from github import UnknownObjectException

        try:
            listing = client.get_organization(owner).get_repos()
        except UnknownObjectException:
            listing = client.get_user(owner).get_repos(type="owner")
        return [
            RemoteRepo(owner=owner, name=r.name, https_url=r.clone_url, ssh_url=r.ssh_url) for r in listing
        ]

    def list_memberships(self) -> list[OrgMembership]:
        if self.credential is None:
            raise GitError(
                f"Listing your organizations on {self.host} requires authentication.", hint=self.auth_hint()
            )
        client = self._client()
        from github import GithubException

        try:
            memberships = client.get_user().get_organization_memberships()
            return [
                OrgMembership(login=m.organization.login, role=m.role, state=m.state) for m in memberships
            ]
        except GithubException as exc:
            raise self.api_error("listing organization memberships", exc) from exc

    def default_protocol(self) -> str:
        if shutil.which("gh") is None:
            return "ssh"
        return gh_adapter.git_protocol(self.host)
