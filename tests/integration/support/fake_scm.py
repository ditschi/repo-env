"""In-process fake of the SCM list APIs used by ``renv clone`` discovery.

One HTTP server speaks just enough of the GitHub (GraphQL + REST), GitLab,
Bitbucket Cloud, Bitbucket Server, Azure DevOps and Gitea APIs for the real
client libraries to list repos and memberships -- with deliberately tiny pages
so every pagination path is exercised. Clone URLs point at local bare repos
(``file://``), so the discovered repos can really be cloned.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class FakeRepo:
    owner: str  # full owner path, e.g. "grp/sub" or "org/project"
    name: str


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
        return [r for r in self.repos if r.owner == root or (nested and r.owner.startswith(f"{root}/"))]

    def exists(self, owner: str) -> bool:
        return any(login == owner for login, _, _ in self.memberships) or any(
            r.owner == owner or r.owner.startswith(f"{owner}/") for r in self.repos
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

    def page(self, items: list[Any], number: int) -> tuple[list[Any], bool]:
        size = self.data.page_size
        chunk = items[(number - 1) * size : number * size]
        return chunk, number * size < len(items)


class _Handler(BaseHTTPRequestHandler):
    server_state: FakeScmServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - silence stderr logging
        pass

    # --- plumbing -------------------------------------------------------
    @property
    def _state(self) -> FakeScmServer:
        return self.server_state

    def _send(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
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

    def _link_paged(
        self, path: str, query: dict[str, list[str]], items: list[Any], page_param: str = "page"
    ) -> None:
        number = int(query.get(page_param, ["1"])[0])
        chunk, more = self._state.page(items, number)
        headers = {"X-Total-Count": str(len(items))}
        if more:
            rest = {k: v[0] for k, v in query.items() if k != page_param}
            rest[page_param] = str(number + 1)
            qs = "&".join(f"{k}={v}" for k, v in rest.items())
            headers["Link"] = f'<{self._state.base_url}{path}?{qs}>; rel="next"'
        self._send(200, chunk, headers)

    # --- dispatch -------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path, _ = self._record()
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/graphql":
            self._github_graphql(request["variables"])
        else:
            self._send(404, {"message": "Not Found"})

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path, query = self._record()
        for prefix, handler in (
            ("/api/v3/", self._github_rest),
            ("/api/v4/", self._gitlab),
            ("/2.0/", self._bitbucket_cloud),
            ("/rest/api/1.0/", self._bitbucket_server),
            ("/api/v1/", self._gitea),
        ):
            if path.startswith(prefix):
                handler(path, path[len(prefix) :].split("/"), query)
                return
        if "/_apis/git/repositories" in path:
            self._azure(path.split("/")[1])
            return
        self._send(404, {"message": "Not Found"})

    # --- GitHub ---------------------------------------------------------
    def _github_graphql(self, variables: dict[str, Any]) -> None:
        owner = variables["owner"]
        if not self._state.data.exists(owner):
            self._send(200, {"data": {"repositoryOwner": None}})
            return
        repos = self._state.data.repos_under(owner, nested=False)
        number = int(variables.get("cursor") or "1")
        chunk, more = self._state.page(repos, number)
        nodes = [
            {
                "name": r.name,
                "url": self._state.data.clone_url(r)[: -len(".git")],
                "sshUrl": f"git@x:{r.name}",
            }
            for r in chunk
        ]
        connection = {"pageInfo": {"hasNextPage": more, "endCursor": str(number + 1)}, "nodes": nodes}
        self._send(200, {"data": {"repositoryOwner": {"repositories": connection}}})

    def _github_rest(self, path: str, parts: list[str], query: dict[str, list[str]]) -> None:
        data = self._state.data
        if parts == ["user", "memberships", "orgs"]:
            items = [
                {"organization": {"login": login}, "role": role, "state": state}
                for login, role, state in data.memberships
            ]
            self._link_paged(path, query, items)
        elif len(parts) == 3 and parts[0] in ("orgs", "users") and parts[2] == "repos":
            if not data.exists(parts[1]):
                self._send(404, {"message": "Not Found"})
                return
            repos = data.repos_under(parts[1], nested=False)
            items = [
                {"name": r.name, "clone_url": data.clone_url(r), "ssh_url": f"git@x:{r.name}"} for r in repos
            ]
            self._link_paged(path, query, items)
        elif len(parts) == 2 and parts[0] == "orgs":
            if data.exists(parts[1]):
                self._send(200, {"login": parts[1]})
            else:
                self._send(404, {"message": "Not Found"})
        elif len(parts) == 2 and parts[0] == "users":
            self._send(200, {"login": parts[1]})
        else:
            self._send(404, {"message": "Not Found"})

    # --- GitLab ---------------------------------------------------------
    def _gitlab_projects(self, path: str, query: dict[str, list[str]], repos: list[FakeRepo]) -> None:
        search = query.get("search", [""])[0].lower()
        items = [
            {
                "id": index,
                "name": r.name,
                "path": r.name,
                "namespace": {"full_path": r.owner},
                "http_url_to_repo": self._state.data.clone_url(r),
                "ssh_url_to_repo": f"git@x:{r.owner}/{r.name}.git",
            }
            for index, r in enumerate(repos)
            if search in r.name.lower()
        ]
        self._link_paged(path, query, items)

    def _gitlab(self, path: str, parts: list[str], query: dict[str, list[str]]) -> None:
        data = self._state.data
        if len(parts) == 3 and parts[0] == "groups" and parts[2] == "projects":
            if not data.exists(parts[1]):
                self._send(404, {"message": "404 Group Not Found"})
                return
            nested = query.get("include_subgroups", ["false"])[0].lower() == "true"
            self._gitlab_projects(path, query, data.repos_under(parts[1], nested=nested))
        elif parts == ["groups"]:
            minimum = int(query.get("min_access_level", ["10"])[0])
            groups = [
                {"id": i, "full_path": login}
                for i, (login, role, state) in enumerate(data.memberships)
                if state == "active" and (minimum < 50 or role == "admin")
            ]
            self._link_paged(path, query, groups)
        elif parts == ["users"]:
            # The id doubles as the username so /users/<id>/projects can be resolved.
            name = query["username"][0]
            self._send(200, [{"id": name, "username": name}] if data.repos_under(name, nested=False) else [])
        elif len(parts) == 3 and parts[0] == "users" and parts[2] == "projects":
            self._gitlab_projects(path, query, data.repos_under(parts[1], nested=False))
        else:
            self._send(404, {"message": "404 Not Found"})

    # --- Bitbucket Cloud ------------------------------------------------
    def _bitbucket_cloud(self, path: str, parts: list[str], query: dict[str, list[str]]) -> None:
        data, base = self._state.data, self._state.base_url
        if len(parts) == 2 and parts[0] == "workspaces":
            slug = parts[1]
            if not data.exists(slug):
                self._send(404, {"type": "error", "error": {"message": "not found"}})
                return
            links = {
                name: {
                    "href": f"{base}/2.0/{name}/{slug}" if name == "repositories" else f"{base}/2.0/x/{name}"
                }
                for name in ("repositories", "projects", "members")
            }
            links["self"] = {"href": f"{base}/2.0/workspaces/{slug}"}
            self._send(200, {"type": "workspace", "slug": slug, "name": slug, "links": links})
        elif len(parts) == 2 and parts[0] == "repositories":
            needle = ""
            if "q" in query:  # name ~ "radar"
                needle = query["q"][0].split('"')[1].lower()
            repos = [r for r in data.repos_under(parts[1], nested=False) if needle in r.name.lower()]
            values = [
                {
                    "type": "repository",
                    "slug": r.name,
                    "name": r.name,
                    "links": {
                        "self": {"href": f"{base}/2.0/repositories/{r.owner}/{r.name}"},
                        "clone": [
                            {"name": "https", "href": data.clone_url(r)},
                            {"name": "ssh", "href": f"git@x:{r.owner}/{r.name}.git"},
                        ],
                    },
                }
                for r in repos
            ]
            self._cloud_paged(path, query, values)
        elif parts == ["user", "workspaces"]:
            admin_only = query.get("administrator", [""])[0] == "True"
            values = [
                {"workspace": {"slug": login}, "administrator": role == "admin"}
                for login, role, _ in data.memberships
                if not admin_only or role == "admin"
            ]
            self._cloud_paged(path, query, values)
        else:
            self._send(404, {"type": "error"})

    def _cloud_paged(self, path: str, query: dict[str, list[str]], values: list[Any]) -> None:
        number = int(query.get("page", ["1"])[0])
        chunk, more = self._state.page(values, number)
        payload: dict[str, Any] = {"values": chunk, "pagelen": len(chunk), "page": number}
        if more:
            rest = {k: v[0] for k, v in query.items() if k != "page"}
            rest["page"] = str(number + 1)
            payload["next"] = f"{self._state.base_url}{path}?" + "&".join(f"{k}={v}" for k, v in rest.items())
        self._send(200, payload)

    # --- Bitbucket Server -----------------------------------------------
    def _bitbucket_server(self, path: str, parts: list[str], query: dict[str, list[str]]) -> None:
        data = self._state.data
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "repos":
            if not data.exists(parts[1]):
                self._send(404, {"errors": [{"message": "Project does not exist."}]})
                return
            repos = data.repos_under(parts[1], nested=False)
            values = [
                {
                    "slug": r.name,
                    "name": r.name,
                    "project": {"key": r.owner},
                    "links": {
                        "clone": [
                            {"name": "http", "href": data.clone_url(r)},
                            {"name": "ssh", "href": f"ssh://git@x:7999/{r.owner}/{r.name}.git"},
                        ]
                    },
                }
                for r in repos
            ]
            self._start_paged(query, values)
        elif parts == ["projects"]:
            self._start_paged(query, [{"key": login} for login, _, _ in data.memberships])
        else:
            self._send(404, {"errors": [{"message": "not found"}]})

    def _start_paged(self, query: dict[str, list[str]], values: list[Any]) -> None:
        start = int(query.get("start", ["0"])[0])
        size = self._state.data.page_size
        chunk = values[start : start + size]
        payload: dict[str, Any] = {"values": chunk, "size": len(chunk), "start": start}
        payload["isLastPage"] = start + size >= len(values)
        if not payload["isLastPage"]:
            payload["nextPageStart"] = start + size
        self._send(200, payload)

    # --- Azure DevOps ---------------------------------------------------
    def _azure(self, org: str) -> None:
        data = self._state.data
        repos = data.repos_under(org, nested=True)
        value = [
            {
                "name": r.name,
                "project": {"name": r.owner.split("/", 1)[1]},
                "remoteUrl": data.clone_url(r),
                "sshUrl": f"git@ssh.x:v3/{r.owner}/{r.name}",
            }
            for r in repos
        ]
        self._send(200, {"value": value, "count": len(value)})

    # --- Gitea ----------------------------------------------------------
    def _gitea(self, path: str, parts: list[str], query: dict[str, list[str]]) -> None:
        data = self._state.data
        if len(parts) == 3 and parts[0] in ("orgs", "users") and parts[2] == "repos":
            if not data.exists(parts[1]):
                self._send(404, {"message": "not found"})
                return
            repos = data.repos_under(parts[1], nested=False)
            items = [
                {"name": r.name, "clone_url": data.clone_url(r), "ssh_url": f"git@x:{r.name}"} for r in repos
            ]
            self._link_paged(path, query, items)
        elif parts == ["user", "orgs"]:
            self._link_paged(path, query, [{"username": login} for login, _, _ in data.memberships])
        else:
            self._send(404, {"message": "not found"})
