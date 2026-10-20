"""Gitea / Forgejo (incl. codeberg.org) discovery over the REST API (stdlib only, no extra needed)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from repoenv.adapters.scm import rest
from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError

_PAGE_SIZE = 50  # Gitea's default maximum page size


class GiteaProvider(ScmProvider):
    """Gitea and Forgejo."""

    kind = ProviderKind.GITEA
    label = "Gitea"

    def _pages(self, path: str, action: str) -> list[dict[str, Any]] | None:
        """All items of a paginated endpoint, or ``None`` when it returns 404."""
        headers = rest.auth_headers(self.credential, token_scheme="token")
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            response = rest.get(
                f"{self.base_url}/api/v1/{path}?limit={_PAGE_SIZE}&page={page}", headers=headers
            )
            if response.status == 404:
                return None
            batch = response.json()
            if not response.ok or not isinstance(batch, list):
                raise GitError(
                    f"Gitea API error on {self.host} while {action} (HTTP {response.status}).",
                    hint=self.auth_hint(),
                )
            items.extend(batch)
            total = response.headers.get("x-total-count")
            if not batch or (total is not None and len(items) >= int(total)):
                return items
            page += 1

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        action = f"listing repositories of '{owner}'"
        items = self._pages(f"orgs/{quote(owner)}/repos", action)
        if items is None:
            items = self._pages(f"users/{quote(owner)}/repos", action)
        if items is None:
            raise GitError(f"No Gitea organization or user '{owner}' on {self.host}.")
        return [
            RemoteRepo(
                owner=owner, name=item["name"], https_url=item["clone_url"], ssh_url=item.get("ssh_url", "")
            )
            for item in items
        ]

    def list_memberships(self) -> list[OrgMembership]:
        if self.credential is None:
            raise GitError(
                f"Listing your organizations on {self.host} requires authentication.", hint=self.auth_hint()
            )
        items = self._pages("user/orgs", "listing organizations") or []
        return [OrgMembership(login=item["username"], role="member", state="active") for item in items]
