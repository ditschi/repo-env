"""Bitbucket Cloud and Bitbucket Server/Data Center discovery via atlassian-python-api.

Requires the ``repo-env[bitbucket]`` extra.
"""

from __future__ import annotations

from typing import Any

from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider, missing_extra, strip_userinfo
from repoenv.domain.scm import ProviderKind


def _auth_kwargs(provider: ScmProvider) -> dict[str, str]:
    credential = provider.credential
    if credential is None:
        return {}
    if credential.username:
        return {"username": credential.username, "password": credential.secret}
    return {"token": credential.secret}


def _clone_links(links: list[dict[str, str]], https_name: str) -> tuple[str, str]:
    by_name = {link["name"]: link["href"] for link in links}
    return strip_userinfo(by_name.get(https_name, "")), by_name.get("ssh", "")


class BitbucketCloudProvider(ScmProvider):
    """bitbucket.org. Workspaces are the owners; ``name ~ "<hint>"`` filters server-side."""

    kind = ProviderKind.BITBUCKET_CLOUD
    label = "Bitbucket Cloud"
    supports_name_hint = True

    def _client(self) -> Any:
        try:
            from atlassian.bitbucket import Cloud
        except ImportError as exc:
            raise missing_extra("bitbucket", self.label) from exc
        api_url = "https://api.bitbucket.org" if self.base_url == "https://bitbucket.org" else self.base_url
        return Cloud(url=api_url, **_auth_kwargs(self))

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        client = self._client()
        query = f'name ~ "{name_hint}"' if name_hint else None
        try:
            repos = []
            for repo in client.workspaces.get(owner).repositories.each(q=query):
                https_url, ssh_url = _clone_links(repo.data["links"]["clone"], "https")
                repos.append(RemoteRepo(owner=owner, name=repo.slug, https_url=https_url, ssh_url=ssh_url))
            return repos
        except (OSError, ValueError) as exc:  # requests' HTTPError is an OSError
            raise self.api_error(f"listing repositories of workspace '{owner}'", exc) from exc

    def list_memberships(self) -> list[OrgMembership]:
        client = self._client()
        try:
            admin = {workspace.slug for workspace in client.workspaces.each(administrator=True)}
            return [
                OrgMembership(login=w.slug, role="admin" if w.slug in admin else "member", state="active")
                for w in client.workspaces.each()
            ]
        except (OSError, ValueError) as exc:
            raise self.api_error("listing workspaces", exc) from exc


class BitbucketServerProvider(ScmProvider):
    """Self-hosted Bitbucket Server / Data Center. Projects (or ``~user``) are the owners."""

    kind = ProviderKind.BITBUCKET_SERVER
    label = "Bitbucket Server"

    def _client(self) -> Any:
        try:
            from atlassian import Bitbucket
        except ImportError as exc:
            raise missing_extra("bitbucket", self.label) from exc
        return Bitbucket(url=self.base_url, **_auth_kwargs(self))

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        client = self._client()
        try:
            repos = []
            for repo in client.repo_list(owner, limit=1000):
                https_url, ssh_url = _clone_links(repo.get("links", {}).get("clone", []), "http")
                repos.append(RemoteRepo(owner=owner, name=repo["slug"], https_url=https_url, ssh_url=ssh_url))
            return repos
        except (OSError, ValueError) as exc:
            raise self.api_error(f"listing repositories of project '{owner}'", exc) from exc

    def list_memberships(self) -> list[OrgMembership]:
        client = self._client()
        try:
            return [
                OrgMembership(login=project["key"], role="member", state="active")
                for project in client.project_list(limit=1000)
            ]
        except (OSError, ValueError) as exc:
            raise self.api_error("listing projects", exc) from exc
