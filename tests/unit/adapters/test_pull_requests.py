from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from repoenv.adapters import gh_adapter, git_adapter
from repoenv.adapters.scm import credentials, detect, pull_requests, rest
from repoenv.adapters.scm.credentials import Credential
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError, UsageError

URL = "https://scm.example/pr/1"
API_KINDS = [kind for kind in ProviderKind if kind is not ProviderKind.GITHUB]


def _response(payload: object, status: int = 200, **headers: str) -> rest.HttpResponse:
    return rest.HttpResponse(status, headers, json.dumps(payload).encode())


def _item(kind: ProviderKind, head: str = "feature/x") -> dict:
    if kind is ProviderKind.GITLAB:
        return {"web_url": URL}
    if kind is ProviderKind.GITEA:
        return {"html_url": URL, "head": {"ref": head}}
    if kind is ProviderKind.BITBUCKET_CLOUD:
        return {"links": {"html": {"href": URL}}, "source": {"branch": {"name": head}}}
    if kind is ProviderKind.BITBUCKET_SERVER:
        return {"links": {"self": [{"href": URL}]}}
    return {"_links": {"web": {"href": URL}}}


def _client(kind: ProviderKind, tmp_path: Path) -> pull_requests.PullRequests:
    provider = detect.make_provider(kind, "scm.example", base_url=None)
    provider.credential = Credential("secret")
    return pull_requests.PullRequests(
        provider, "org/project" if kind is ProviderKind.AZURE_DEVOPS else "o", "r", tmp_path
    )


_BEARER = rest.auth_headers(Credential("secret"), token_scheme="Bearer")
_BB_REPOSITORY = {"slug": "r", "project": {"key": "o"}}
# kind -> (endpoint, payload, auth headers) for _request() with default options.
_EXPECTED_CREATION = {
    ProviderKind.GITLAB: (
        "https://scm.example/api/v4/projects/o%2Fr/merge_requests",
        {"title": "Title", "description": "Body", "source_branch": "feature/x", "target_branch": "main"},
        {"PRIVATE-TOKEN": "secret"},
    ),
    ProviderKind.BITBUCKET_CLOUD: (
        "https://scm.example/2.0/repositories/o/r/pullrequests",
        {
            "title": "Title",
            "description": "Body",
            "source": {"branch": {"name": "feature/x"}},
            "destination": {"branch": {"name": "main"}},
            "close_source_branch": False,
        },
        _BEARER,
    ),
    ProviderKind.BITBUCKET_SERVER: (
        "https://scm.example/rest/api/1.0/projects/o/repos/r/pull-requests",
        {
            "title": "Title",
            "description": "Body",
            "fromRef": {"id": "refs/heads/feature/x", "repository": _BB_REPOSITORY},
            "toRef": {"id": "refs/heads/main", "repository": _BB_REPOSITORY},
        },
        _BEARER,
    ),
    ProviderKind.AZURE_DEVOPS: (
        "https://scm.example/org/project/_apis/git/repositories/r/pullrequests?api-version=7.1",
        {
            "title": "Title",
            "description": "Body",
            "sourceRefName": "refs/heads/feature/x",
            "targetRefName": "refs/heads/main",
            "isDraft": False,
        },
        rest.auth_headers(Credential("secret"), token_scheme="Basic"),
    ),
    ProviderKind.GITEA: (
        "https://scm.example/api/v1/repos/o/r/pulls",
        {"title": "Title", "body": "Body", "head": "feature/x", "base": "main"},
        rest.auth_headers(Credential("secret"), token_scheme="token"),
    ),
}


def _request(**options: object) -> pull_requests.PrRequest:
    return pull_requests.PrRequest(
        title="Title", body="Body", base="main", head="feature/x", options=pull_requests.PrOptions(**options)
    )


@pytest.mark.parametrize("kind", API_KINDS)
def test_creation_payload_and_auth(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return _response(_item(kind), 201)

    monkeypatch.setattr(rest, "request", request)
    assert client.create(_request()) == URL
    url, kwargs = calls[0]
    actual = (url, kwargs["method"], kwargs["payload"], kwargs["headers"])
    endpoint, payload, headers = _EXPECTED_CREATION[kind]
    assert actual == (endpoint, "POST", payload, headers)


@pytest.mark.parametrize("kind", API_KINDS)
def test_existing_and_empty(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)

    def listing(items):
        if kind in (ProviderKind.GITLAB, ProviderKind.GITEA):
            return items
        return {"value" if kind is ProviderKind.AZURE_DEVOPS else "values": items, "isLastPage": True}

    replies = iter([_response(listing([_item(kind)])), _response(listing([]))])
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return next(replies)

    monkeypatch.setattr(rest, "request", request)
    assert client.existing_url(head="feature/x") == URL
    assert client.existing_url(head="feature/x") is None
    query = parse_qs(urlsplit(calls[0]).query)
    if kind is ProviderKind.GITLAB:
        assert query["source_branch"] == ["feature/x"]
    if kind is ProviderKind.AZURE_DEVOPS:
        assert query["searchCriteria.sourceRefName"] == ["refs/heads/feature/x"]
    if kind is ProviderKind.BITBUCKET_SERVER:
        assert query["at"] == ["refs/heads/feature/x"]


@pytest.mark.parametrize("kind", API_KINDS)
@pytest.mark.parametrize("flag", ["reviewers", "labels", "assignees", "draft"])
def test_capabilities(kind, flag, tmp_path):
    options = pull_requests.PrOptions(**{flag: True if flag == "draft" else ["user"]})
    client = _client(kind, tmp_path)
    if flag == "draft" and kind in (ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS):
        client.validate_options(options)
    else:
        with pytest.raises(UsageError, match="does not support"):
            client.validate_options(options)


@pytest.mark.parametrize("kind", [ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS])
def test_draft_payload(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    payloads = []

    def request(url, **kwargs):
        payloads.append(kwargs["payload"])
        return _response(_item(kind))

    monkeypatch.setattr(rest, "request", request)
    client.create(_request(draft=True))
    assert payloads[0].get("isDraft", payloads[0]["title"] == "Draft: Title") is True


@pytest.mark.parametrize("kind", API_KINDS)
@pytest.mark.parametrize(
    "response",
    [
        _response({"message": "secret"}, 401),
        _response({}, 500),
        _response(None, 200),
        _response("bad", 200),
    ],
    ids=["401-secret", "500-empty", "200-null", "200-string"],
)
def test_api_errors_are_not_absence(kind, response, tmp_path, monkeypatch):
    monkeypatch.setattr(rest, "request", lambda *a, **kw: response)
    with pytest.raises(GitError, match=f"HTTP {response.status}") as exc:
        _client(kind, tmp_path).existing_url(head="f")
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("kind", API_KINDS)
def test_missing_credentials_and_creation_url(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    client.provider.credential = None
    monkeypatch.setattr(rest, "request", lambda *a, **kw: pytest.fail("no unauthenticated request"))
    with pytest.raises(GitError, match="require authentication"):
        client.existing_url(head="f")
    client.provider.credential = Credential("secret")
    monkeypatch.setattr(rest, "request", lambda *a, **kw: _response({}))
    with pytest.raises(GitError, match="no valid web URL"):
        client.create(_request())


@dataclass(frozen=True)
class _RemoteCase:
    raw: str
    setting: str | None
    kind: ProviderKind
    owner: str
    repo: str


@pytest.mark.parametrize(
    "case",
    [
        _RemoteCase("git@github.com:o/r.git", None, ProviderKind.GITHUB, "o", "r"),
        _RemoteCase("ssh://git@ghe.example/o/r.git", "github", ProviderKind.GITHUB, "o", "r"),
        _RemoteCase("https://gitlab.com/group/sub/r.git", None, ProviderKind.GITLAB, "group/sub", "r"),
        _RemoteCase("git@bitbucket.org:o/r.git", None, ProviderKind.BITBUCKET_CLOUD, "o", "r"),
        _RemoteCase(
            "ssh://git@bb.example:7999/PROJ/r.git",
            "bitbucket-server",
            ProviderKind.BITBUCKET_SERVER,
            "PROJ",
            "r",
        ),
        _RemoteCase(
            "https://bb.example/bitbucket/scm/PROJ/r.git",
            "bitbucket-server https://bb.example/bitbucket",
            ProviderKind.BITBUCKET_SERVER,
            "PROJ",
            "r",
        ),
        _RemoteCase(
            "https://dev.azure.com/org/project/_git/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"
        ),
        _RemoteCase(
            "git@ssh.dev.azure.com:v3/org/project/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"
        ),
        _RemoteCase(
            "https://org.visualstudio.com/project/_git/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"
        ),
        _RemoteCase(
            "https://tfs.example/tfs/collection/project/_git/r",
            "azure-devops https://tfs.example/tfs",
            ProviderKind.AZURE_DEVOPS,
            "collection/project",
            "r",
        ),
        _RemoteCase("git@codeberg.org:o/r.git", None, ProviderKind.GITEA, "o", "r"),
        _RemoteCase(
            "https://forge.example/forge/o/r.git",
            "gitea https://forge.example/forge",
            ProviderKind.GITEA,
            "o",
            "r",
        ),
    ],
    ids=lambda case: case.raw,
)
def test_remote_resolution(case, tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_adapter,
        "remote_url",
        lambda wt, remote: case.raw if remote == "upstream" else pytest.fail("wrong remote"),
    )
    monkeypatch.setattr(credentials, "resolve", lambda *a: pytest.fail("not needed for resolution"))
    settings = {pull_requests.url_host(case.raw): case.setting} if case.setting else {}
    client = pull_requests.for_worktree(tmp_path, "upstream", settings=settings)
    assert (client.provider.kind, client.owner, client.repo) == (case.kind, case.owner, case.repo)


@pytest.mark.parametrize("kind", [ProviderKind.GITEA, ProviderKind.BITBUCKET_CLOUD])
def test_lookup_paginates_and_filters_head(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        item = _item(kind, "other" if page == 1 else "feature/x")
        return _response(
            [item] if kind is ProviderKind.GITEA else {"values": [item], "next": "https://evil.example/steal"}
        )

    monkeypatch.setattr(rest, "request", request)
    assert client.existing_url(head="feature/x") == URL
    assert len(calls) == 2
    assert all(url.startswith("https://scm.example/") for url in calls)


def test_github_uses_selected_repository_and_surfaces_lookup_failure(tmp_path, monkeypatch):
    client = _client(ProviderKind.GITHUB, tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return gh_adapter.subprocess.CompletedProcess(argv, 1, "", "auth failed")

    monkeypatch.setattr(gh_adapter, "_run", run)
    with pytest.raises(GitError, match="auth failed"):
        client.existing_url(head="f")
    assert calls[0][-2:] == ["--repo", "scm.example/o/r"]


def test_rest_json_write(monkeypatch):
    seen = []

    class Response:
        status = 201
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok":true}'

    def open_request(request, **kwargs):
        seen.append(request)
        return Response()

    monkeypatch.setattr(rest._OPENER, "open", open_request)
    response = rest.request("https://scm.example/api", method="POST", payload={"title": "t"})
    sent = seen[0]
    actual = (response.status, sent.method, json.loads(sent.data), sent.get_header("Content-type"))
    assert actual == (201, "POST", {"title": "t"}, "application/json")
    assert rest._NoRedirect().redirect_request() is None


def test_github_creation_preserves_optional_flags(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(gh_adapter, "is_available", lambda: True)

    def run(argv, **kwargs):
        captured.append(argv)
        return gh_adapter.subprocess.CompletedProcess(argv, 0, URL, "")

    monkeypatch.setattr(gh_adapter, "_run", run)
    request = _request(draft=True, reviewers=["alice"], labels=["bug"], assignees=["bob"])
    assert _client(ProviderKind.GITHUB, tmp_path).create(request) == URL
    argv = captured[0]
    assert "--draft" in argv
    for flag, value in (
        ("--reviewer", "alice"),
        ("--label", "bug"),
        ("--assignee", "bob"),
        ("--repo", "scm.example/o/r"),
    ):
        assert argv[argv.index(flag) + 1] == value


def test_unknown_provider_is_explicit_error(tmp_path, monkeypatch):
    monkeypatch.setattr(git_adapter, "remote_url", lambda *a: "https://scm.example/o/r")
    monkeypatch.setattr(detect, "probe", lambda *a: None)
    with pytest.raises(UsageError, match="Could not determine"):
        pull_requests.for_worktree(tmp_path, "origin", settings={})


@pytest.mark.parametrize("kind", API_KINDS)
def test_malformed_listing(kind, tmp_path, monkeypatch):
    monkeypatch.setattr(rest, "request", lambda *a, **kw: _response({"unexpected": []}))
    with pytest.raises(GitError, match="invalid listing"):
        _client(kind, tmp_path).existing_url(head="f")


@pytest.mark.parametrize("kind", API_KINDS)
def test_malformed_url(kind, tmp_path):
    with pytest.raises(GitError, match="no valid web URL"):
        _client(kind, tmp_path)._url({"links": None, "_links": None, "html_url": []})
