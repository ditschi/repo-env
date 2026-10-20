"""GitLab.com and self-managed GitLab discovery via python-gitlab (``repo-env[gitlab]``).

A top-level group is listed in one paginated call that includes all
subgroups; the glob's longest literal is passed as ``search`` so GitLab
filters server-side before the exact match is applied locally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider, missing_extra
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError

if TYPE_CHECKING:
    from gitlab import Gitlab

_GUEST, _OWNER = 10, 50


class GitLabProvider(ScmProvider):
    """GitLab (SaaS or self-managed)."""

    kind = ProviderKind.GITLAB
    label = "GitLab"
    supports_name_hint = True

    def _client(self) -> Gitlab:
        try:
            import gitlab
        except ImportError as exc:
            raise missing_extra("gitlab", self.label) from exc
        # Bearer auth accepts personal, group, project and OAuth tokens alike.
        token = self.credential.secret if self.credential else None
        return gitlab.Gitlab(self.base_url, oauth_token=token, per_page=100)

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        client = self._client()
        from gitlab.exceptions import GitlabError

        params: dict[str, Any] = {"iterator": True}
        if name_hint:
            params["search"] = name_hint
        try:
            try:
                projects = list(
                    client.groups.get(owner, lazy=True).projects.list(include_subgroups=True, **params)
                )
            except GitlabError as exc:
                if exc.response_code != 404:
                    raise
                projects = self._user_projects(client, owner, params)
        except GitlabError as exc:
            raise self.api_error(f"listing projects of '{owner}'", exc) from exc
        return [
            RemoteRepo(
                owner=project.namespace["full_path"],
                name=project.path,
                https_url=project.http_url_to_repo,
                ssh_url=project.ssh_url_to_repo,
            )
            for project in projects
        ]

    def _user_projects(self, client: Gitlab, owner: str, params: dict[str, Any]) -> list[Any]:
        users = client.users.list(username=owner, get_all=False)
        if not users:
            raise GitError(f"No GitLab group or user '{owner}' on {self.host}.")
        return list(client.users.get(users[0].id, lazy=True).projects.list(**params))

    def list_memberships(self) -> list[OrgMembership]:
        if self.credential is None:
            raise GitError(
                f"Listing your groups on {self.host} requires authentication.", hint=self.auth_hint()
            )
        client = self._client()
        from gitlab.exceptions import GitlabError

        try:
            member_paths = [g.full_path for g in client.groups.list(iterator=True, min_access_level=_GUEST)]
            owner_paths = {g.full_path for g in client.groups.list(iterator=True, min_access_level=_OWNER)}
        except GitlabError as exc:
            raise self.api_error("listing group memberships", exc) from exc
        # Members of only a subgroup still discover through its top-level group.
        roots = dict.fromkeys(path.split("/", 1)[0] for path in member_paths)
        return [
            OrgMembership(login=root, role="admin" if root in owner_paths else "member", state="active")
            for root in roots
        ]
