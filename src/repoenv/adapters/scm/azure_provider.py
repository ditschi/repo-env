"""Azure DevOps Services / Server discovery over the REST API (stdlib only, no extra needed).

Owners are ``organization/project``; one request lists every repository of
an organization (the endpoint isn't paginated). Organizations themselves
can't be enumerated with a PAT, so the organization must be literal.
"""

from __future__ import annotations

from urllib.parse import quote

from repoenv.adapters.scm import rest
from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider, strip_userinfo
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError, UsageError


class AzureDevOpsProvider(ScmProvider):
    """dev.azure.com (and Azure DevOps Server via a ``providers.<host>`` base URL)."""

    kind = ProviderKind.AZURE_DEVOPS
    label = "Azure DevOps"

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        url = f"{self.base_url}/{quote(owner)}/_apis/git/repositories?api-version=7.1"
        # PATs and Entra tokens both work as the basic-auth password.
        response = rest.get(url, headers=rest.auth_headers(self.credential, token_scheme="Basic"))
        payload = response.json()
        if not response.ok or not isinstance(payload, dict):
            raise GitError(
                f"Azure DevOps API error on {self.host} while listing repositories of '{owner}' "
                f"(HTTP {response.status}).",
                hint=self.auth_hint(),
            )
        return [
            RemoteRepo(
                owner=f"{owner}/{item['project']['name']}",
                name=item["name"],
                https_url=strip_userinfo(item["remoteUrl"]),
                ssh_url=item.get("sshUrl", ""),
            )
            for item in payload.get("value", [])
        ]

    def list_memberships(self) -> list[OrgMembership]:
        raise UsageError(
            "Azure DevOps organizations can't be discovered with a wildcard.",
            hint="Name the organization literally, e.g. --include 'my-org/*/*' "
            "or --url https://dev.azure.com/my-org.",
        )
