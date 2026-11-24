"""In-process fake of the SCM list APIs used by ``renv clone`` discovery.

One HTTP server speaks just enough of the GitHub (GraphQL + REST), GitLab,
Bitbucket Cloud, Bitbucket Server, Azure DevOps and Gitea APIs for the real
client libraries to list repos and memberships -- with deliberately tiny pages
so every pagination path is exercised. Clone URLs point at local bare repos
(``file://``), so the discovered repos can really be cloned.
"""
# aihealth: disable=primitive_obsession -- fake HTTP server: request/response bodies are raw JSON by design

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class FakeRepo:
    owner: str  # full owner path, e.g. "grp/sub" or "org/project"
    name: str

    def is_under(self, root: str, *, nested: bool) -> bool:
        """Owned by ``root`` itself or, when ``nested``, by any of its sub-owners."""
        if self.owner == root:
            return True
        return nested and self.owner.startswith(f"{root}/")


@dataclass
class FakeScmData:
    remotes: Path
    repos: list[FakeRepo] = field(default_factory=list)
    # (login, role, state)
    memberships: list[tuple[str, str, str]] = field(default_factory=list)
    page_size: int = 2

    def clone_url(self, repo: FakeRepo) -> str:
        return (self.remotes / repo.owner / f"{repo.name}.git").as_uri()

    def repos_under(self, root: str, *, nested: bool) -> list[FakeRepo]:
        return [r for r in self.repos if r.is_under(root, nested=nested)]

    def exists(self, owner: str) -> bool:
        return any(login == owner for login, _, _ in self.memberships) or any(
            r.is_under(owner, nested=True) for r in self.repos
        )


@dataclass
class Seen:
    paths: list[str] = field(default_factory=list)
    auth_headers: set[str] = field(default_factory=set)


class FakeScmServer:
    def __init__(self, data: FakeScmData) -> None:
        self.data = data
        self.seen = Seen()
        handler = type("Handler", (_Handler,), {"server_state": self})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> FakeScmServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def page(self, items: Sequence[Any], number: int) -> tuple[list[Any], bool]:
        size = self.data.page_size
        chunk = list(items[(number - 1) * size : number * size])
        return chunk, number * size < len(items)


@dataclass(frozen=True)
class _Request:
    """A GET request to one provider API: path segments after the API prefix plus the query."""

    path: str
    parts: tuple[str, ...]
    query: dict[str, list[str]]

    def arg(self, name: str) -> str:
        """First value of query parameter ``name``, or ``""``."""
        return self.query.get(name, [""])[0]

    @property
    def owner(self) -> str:
        """The owner segment of ``/<kind>/<owner>/...`` paths."""
        return self.parts[1]

    @property
    def page(self) -> int:
        return int(self.arg("page") or "1")

    def next_page_query(self) -> str:
        rest = {k: v[0] for k, v in self.query.items() if k != "page"}
        rest["page"] = str(self.page + 1)
        return "&".join(f"{k}={v}" for k, v in rest.items())


class _Route(NamedTuple):
    """``pattern`` segments (``*`` = any) -> handler; ``missing`` is the 404 body if the owner is unknown."""

    pattern: tuple[str, ...]
    handler: Callable[[_Handler, _Request], None]
    missing: Any = None

    def matches(self, request: _Request) -> bool:
        return len(request.parts) == len(self.pattern) and all(
            expected in ("*", part) for part, expected in zip(request.parts, self.pattern)
        )


class _Handler(BaseHTTPRequestHandler):
    server_state: FakeScmServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - silence stderr logging
        pass

    # --- plumbing -------------------------------------------------------
    @property
    def _state(self) -> FakeScmServer:
        return self.server_state

    @property
    def _data(self) -> FakeScmData:
        return self.server_state.data

    def _send(
        self, payload: Any, status: HTTPStatus = HTTPStatus.OK, headers: Mapping[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _record(self) -> tuple[str, dict[str, list[str]]]:
        parts = urlsplit(self.path)
        self._state.seen.paths.append(self.path)
        if self.headers.get("Authorization"):
            self._state.seen.auth_headers.add(self.headers["Authorization"])
        return parts.path, parse_qs(parts.query)

    def _next_page_url(self, request: _Request) -> str:
        return f"{self._state.base_url}{request.path}?{request.next_page_query()}"

    def _link_paged(self, request: _Request, items: Sequence[Any]) -> None:
        chunk, more = self._state.page(items, request.page)
        headers = {"X-Total-Count": str(len(items))}
        if more:
            headers["Link"] = f'<{self._next_page_url(request)}>; rel="next"'
        self._send(chunk, headers=headers)

    def _cloud_paged(self, request: _Request, values: Sequence[Any]) -> None:
        chunk, more = self._state.page(values, request.page)
        payload: dict[str, Any] = {"values": chunk, "pagelen": len(chunk), "page": request.page}
        if more:
            payload["next"] = self._next_page_url(request)
        self._send(payload)

    def _start_paged(self, request: _Request, values: Sequence[Any]) -> None:
        start = int(request.arg("start") or "0")
        size = self._data.page_size
        chunk = list(values[start : start + size])
        payload: dict[str, Any] = {"values": chunk, "size": len(chunk), "start": start}
        payload["isLastPage"] = start + size >= len(values)
        if not payload["isLastPage"]:
            payload["nextPageStart"] = start + size
        self._send(payload)

    # --- dispatch -------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path, _ = self._record()
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/graphql":
            self._github_graphql(request["variables"])
        else:
            self._send({"message": "Not Found"}, HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path, query = self._record()
        for api in _APIS:
            if path.startswith(api.prefix):
                self._dispatch(api, _Request(path, tuple(path[len(api.prefix) :].split("/")), query))
                return
        if "/_apis/git/repositories" in path:
            self._azure(path.split("/")[1])
            return
        self._send({"message": "Not Found"}, HTTPStatus.NOT_FOUND)

    def _dispatch(self, api: _Api, request: _Request) -> None:
        route = next((r for r in api.routes if r.matches(request)), None)
        if route is None:
            self._send(api.not_found, HTTPStatus.NOT_FOUND)
        elif route.missing is not None and not self._data.exists(request.owner):
            self._send(route.missing, HTTPStatus.NOT_FOUND)
        else:
            route.handler(self, request)

    # --- shared ---------------------------------------------------------
    def _owner_repos(self, request: _Request) -> None:
        """GitHub REST and Gitea list an org's/user's repos in the same shape."""
        items = [
            {"name": r.name, "clone_url": self._data.clone_url(r), "ssh_url": f"git@x:{r.name}"}
            for r in self._data.repos_under(request.owner, nested=False)
        ]
        self._link_paged(request, items)

    def _login(self, request: _Request) -> None:
        self._send({"login": request.owner})

    # --- GitHub ---------------------------------------------------------
    def _github_graphql(self, variables: Mapping[str, Any]) -> None:
        owner = variables["owner"]
        if not self._data.exists(owner):
            self._send({"data": {"repositoryOwner": None}})
            return
        number = int(variables.get("cursor") or "1")
        chunk, more = self._state.page(self._data.repos_under(owner, nested=False), number)
        nodes = [
            {"name": r.name, "url": self._data.clone_url(r)[: -len(".git")], "sshUrl": f"git@x:{r.name}"}
            for r in chunk
        ]
        connection = {"pageInfo": {"hasNextPage": more, "endCursor": str(number + 1)}, "nodes": nodes}
        self._send({"data": {"repositoryOwner": {"repositories": connection}}})

    def _github_memberships(self, request: _Request) -> None:
        items = [
            {"organization": {"login": login}, "role": role, "state": state}
            for login, role, state in self._data.memberships
        ]
        self._link_paged(request, items)

    # --- GitLab ---------------------------------------------------------
    def _gitlab_projects(self, request: _Request, repos: Sequence[FakeRepo]) -> None:
        search = request.arg("search").lower()
        items = [
            {
                "id": index,
                "name": r.name,
                "path": r.name,
                "namespace": {"full_path": r.owner},
                "http_url_to_repo": self._data.clone_url(r),
                "ssh_url_to_repo": f"git@x:{r.owner}/{r.name}.git",
            }
            for index, r in enumerate(repos)
            if search in r.name.lower()
        ]
        self._link_paged(request, items)

    def _gitlab_group_projects(self, request: _Request) -> None:
        nested = (request.arg("include_subgroups") or "false").lower() == "true"
        self._gitlab_projects(request, self._data.repos_under(request.owner, nested=nested))

    def _gitlab_user_projects(self, request: _Request) -> None:
        self._gitlab_projects(request, self._data.repos_under(request.owner, nested=False))

    def _gitlab_groups(self, request: _Request) -> None:
        minimum = int(request.arg("min_access_level") or "10")
        groups = [
            {"id": i, "full_path": login}
            for i, (login, role, state) in enumerate(self._data.memberships)
            if state == "active"
            if minimum < 50 or role == "admin"
        ]
        self._link_paged(request, groups)

    def _gitlab_users(self, request: _Request) -> None:
        # The id doubles as the username so /users/<id>/projects can be resolved.
        name = request.query["username"][0]
        self._send([{"id": name, "username": name}] if self._data.repos_under(name, nested=False) else [])

    # --- Bitbucket Cloud ------------------------------------------------
    def _bitbucket_workspace(self, request: _Request) -> None:
        slug, base = request.owner, self._state.base_url
        links = {
            "repositories": {"href": f"{base}/2.0/repositories/{slug}"},
            **{name: {"href": f"{base}/2.0/x/{name}"} for name in ("projects", "members")},
            "self": {"href": f"{base}/2.0/workspaces/{slug}"},
        }
        self._send({"type": "workspace", "slug": slug, "name": slug, "links": links})

    def _bitbucket_repositories(self, request: _Request) -> None:
        # q looks like: name ~ "radar"
        needle = request.arg("q").split('"')[1].lower() if "q" in request.query else ""
        base = self._state.base_url
        values = [
            {
                "type": "repository",
                "slug": r.name,
                "name": r.name,
                "links": {
                    "self": {"href": f"{base}/2.0/repositories/{r.owner}/{r.name}"},
                    "clone": [
                        {"name": "https", "href": self._data.clone_url(r)},
                        {"name": "ssh", "href": f"git@x:{r.owner}/{r.name}.git"},
                    ],
                },
            }
            for r in self._data.repos_under(request.owner, nested=False)
            if needle in r.name.lower()
        ]
        self._cloud_paged(request, values)

    def _bitbucket_user_workspaces(self, request: _Request) -> None:
        admin_only = request.arg("administrator") == "True"
        values = [
            {"workspace": {"slug": login}, "administrator": role == "admin"}
            for login, role, _ in self._data.memberships
            if not admin_only or role == "admin"
        ]
        self._cloud_paged(request, values)

    # --- Bitbucket Server -----------------------------------------------
    def _bitbucket_server_repos(self, request: _Request) -> None:
        values = [
            {
                "slug": r.name,
                "name": r.name,
                "project": {"key": r.owner},
                "links": {
                    "clone": [
                        {"name": "http", "href": self._data.clone_url(r)},
                        {"name": "ssh", "href": f"ssh://git@x:7999/{r.owner}/{r.name}.git"},
                    ]
                },
            }
            for r in self._data.repos_under(request.owner, nested=False)
        ]
        self._start_paged(request, values)

    def _bitbucket_server_projects(self, request: _Request) -> None:
        self._start_paged(request, [{"key": login} for login, _, _ in self._data.memberships])

    # --- Azure DevOps ---------------------------------------------------
    def _azure(self, org: str) -> None:
        value = [
            {
                "name": r.name,
                "project": {"name": r.owner.split("/", 1)[1]},
                "remoteUrl": self._data.clone_url(r),
                "sshUrl": f"git@ssh.x:v3/{r.owner}/{r.name}",
            }
            for r in self._data.repos_under(org, nested=True)
        ]
        self._send({"value": value, "count": len(value)})

    # --- Gitea ----------------------------------------------------------
    def _gitea_orgs(self, request: _Request) -> None:
        self._link_paged(request, [{"username": login} for login, _, _ in self._data.memberships])


class _Api(NamedTuple):
    """One provider API: its path prefix, its generic 404 body and its GET routes."""

    prefix: str
    not_found: Any
    routes: tuple[_Route, ...]


_GITHUB_404 = {"message": "Not Found"}
_GITEA_404 = {"message": "not found"}

_APIS = (
    _Api(
        "/api/v3/",
        _GITHUB_404,
        (
            _Route(("user", "memberships", "orgs"), _Handler._github_memberships),
            _Route(("orgs", "*", "repos"), _Handler._owner_repos, _GITHUB_404),
            _Route(("users", "*", "repos"), _Handler._owner_repos, _GITHUB_404),
            _Route(("orgs", "*"), _Handler._login, _GITHUB_404),
            _Route(("users", "*"), _Handler._login),
        ),
    ),
    _Api(
        "/api/v4/",
        {"message": "404 Not Found"},
        (
            _Route(
                ("groups", "*", "projects"),
                _Handler._gitlab_group_projects,
                {"message": "404 Group Not Found"},
            ),
            _Route(("groups",), _Handler._gitlab_groups),
            _Route(("users",), _Handler._gitlab_users),
            _Route(("users", "*", "projects"), _Handler._gitlab_user_projects),
        ),
    ),
    _Api(
        "/2.0/",
        {"type": "error"},
        (
            _Route(
                ("workspaces", "*"),
                _Handler._bitbucket_workspace,
                {"type": "error", "error": {"message": "not found"}},
            ),
            _Route(("repositories", "*"), _Handler._bitbucket_repositories),
            _Route(("user", "workspaces"), _Handler._bitbucket_user_workspaces),
        ),
    ),
    _Api(
        "/rest/api/1.0/",
        {"errors": [{"message": "not found"}]},
        (
            _Route(
                ("projects", "*", "repos"),
                _Handler._bitbucket_server_repos,
                {"errors": [{"message": "Project does not exist."}]},
            ),
            _Route(("projects",), _Handler._bitbucket_server_projects),
        ),
    ),
    _Api(
        "/api/v1/",
        _GITEA_404,
        (
            _Route(("orgs", "*", "repos"), _Handler._owner_repos, _GITEA_404),
            _Route(("users", "*", "repos"), _Handler._owner_repos, _GITEA_404),
            _Route(("user", "orgs"), _Handler._gitea_orgs),
        ),
    ),
)
