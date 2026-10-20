from __future__ import annotations

import json
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


@pytest.mark.parametrize("kind", API_KINDS)
def test_creation_payload_and_auth(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return _response(_item(kind), 201)

    monkeypatch.setattr(rest, "request", request)
    assert (
        client.create(
            title="Title",
            body="Body",
            base="main",
            head="feature/x",
            draft=False,
            reviewers=[],
            labels=[],
            assignees=[],
        )
        == URL
    )
    url, kwargs = calls[0]
    assert kwargs["method"] == "POST"
    payload = kwargs["payload"]
    assert payload["title"] == "Title"
    if kind is ProviderKind.GITLAB:
        assert url == "https://scm.example/api/v4/projects/o%2Fr/merge_requests"
        assert payload == {
            "title": "Title",
            "description": "Body",
            "source_branch": "feature/x",
            "target_branch": "main",
        }
        assert kwargs["headers"] == {"PRIVATE-TOKEN": "secret"}
    elif kind is ProviderKind.BITBUCKET_CLOUD:
        assert url.endswith("/2.0/repositories/o/r/pullrequests")
        assert payload["source"]["branch"]["name"] == "feature/x"
        assert payload["destination"]["branch"]["name"] == "main"
        assert payload["close_source_branch"] is False
    elif kind is ProviderKind.BITBUCKET_SERVER:
        assert url.endswith("/rest/api/1.0/projects/o/repos/r/pull-requests")
        assert payload["fromRef"] == {
            "id": "refs/heads/feature/x",
            "repository": {"slug": "r", "project": {"key": "o"}},
        }
        assert payload["toRef"]["id"] == "refs/heads/main"
    elif kind is ProviderKind.AZURE_DEVOPS:
        assert url == "https://scm.example/org/project/_apis/git/repositories/r/pullrequests?api-version=7.1"
        assert payload["sourceRefName"] == "refs/heads/feature/x"
        assert payload["targetRefName"] == "refs/heads/main"
        assert payload["isDraft"] is False
        assert kwargs["headers"] == rest.auth_headers(Credential("secret"), token_scheme="Basic")
    else:
        assert url.endswith("/api/v1/repos/o/r/pulls")
        assert payload == {"title": "Title", "body": "Body", "head": "feature/x", "base": "main"}
        assert kwargs["headers"] == rest.auth_headers(Credential("secret"), token_scheme="token")


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
    options = dict(draft=False, reviewers=[], labels=[], assignees=[])
    options[flag] = True if flag == "draft" else ["user"]
    client = _client(kind, tmp_path)
    if flag == "draft" and kind in (ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS):
        client.validate_options(**options)
    else:
        with pytest.raises(UsageError, match="does not support"):
            client.validate_options(**options)


@pytest.mark.parametrize("kind", [ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS])
def test_draft_payload(kind, tmp_path, monkeypatch):
    client = _client(kind, tmp_path)
    payloads = []

    def request(url, **kwargs):
        payloads.append(kwargs["payload"])
        return _response(_item(kind))

    monkeypatch.setattr(rest, "request", request)
    client.create(
        title="Title", body="", base="main", head="f", draft=True, reviewers=[], labels=[], assignees=[]
    )
    assert payloads[0].get("isDraft", payloads[0]["title"] == "Draft: Title") is True


@pytest.mark.parametrize("kind", API_KINDS)
@pytest.mark.parametrize(
    "status,payload", [(401, {"message": "secret"}), (500, {}), (200, None), (200, "bad")]
)
def test_api_errors_are_not_absence(kind, status, payload, tmp_path, monkeypatch):
    monkeypatch.setattr(rest, "request", lambda *a, **kw: _response(payload, status))
    with pytest.raises(GitError, match=f"HTTP {status}") as exc:
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
        client.create(
            title="t", body="", base="main", head="f", draft=False, reviewers=[], labels=[], assignees=[]
        )


@pytest.mark.parametrize(
    "raw,setting,kind,owner,repo",
    [
        ("git@github.com:o/r.git", None, ProviderKind.GITHUB, "o", "r"),
        ("ssh://git@ghe.example/o/r.git", "github", ProviderKind.GITHUB, "o", "r"),
        ("https://gitlab.com/group/sub/r.git", None, ProviderKind.GITLAB, "group/sub", "r"),
        ("git@bitbucket.org:o/r.git", None, ProviderKind.BITBUCKET_CLOUD, "o", "r"),
        (
            "ssh://git@bb.example:7999/PROJ/r.git",
            "bitbucket-server",
            ProviderKind.BITBUCKET_SERVER,
            "PROJ",
            "r",
        ),
        (
            "https://bb.example/bitbucket/scm/PROJ/r.git",
            "bitbucket-server https://bb.example/bitbucket",
            ProviderKind.BITBUCKET_SERVER,
            "PROJ",
            "r",
        ),
        ("https://dev.azure.com/org/project/_git/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"),
        ("git@ssh.dev.azure.com:v3/org/project/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"),
        ("https://org.visualstudio.com/project/_git/r", None, ProviderKind.AZURE_DEVOPS, "org/project", "r"),
        (
            "https://tfs.example/tfs/collection/project/_git/r",
            "azure-devops https://tfs.example/tfs",
            ProviderKind.AZURE_DEVOPS,
            "collection/project",
            "r",
        ),
        ("git@codeberg.org:o/r.git", None, ProviderKind.GITEA, "o", "r"),
        (
            "https://forge.example/forge/o/r.git",
            "gitea https://forge.example/forge",
            ProviderKind.GITEA,
            "o",
            "r",
        ),
    ],
)
def test_remote_resolution(raw, setting, kind, owner, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_adapter,
        "remote_url",
        lambda wt, remote: raw if remote == "upstream" else pytest.fail("wrong remote"),
    )
    monkeypatch.setattr(credentials, "resolve", lambda *a: pytest.fail("not needed for resolution"))
    settings = {pull_requests.url_host(raw): setting} if setting else {}
    client = pull_requests.for_worktree(tmp_path, "upstream", settings=settings)
    assert (client.provider.kind, client.owner, client.repo) == (kind, owner, repo)


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
    assert rest.request("https://scm.example/api", method="POST", payload={"title": "t"}).status == 201
    assert seen[0].method == "POST"
    assert json.loads(seen[0].data) == {"title": "t"}
    assert seen[0].get_header("Content-type") == "application/json"
    assert rest._NoRedirect().redirect_request() is None


def test_github_creation_preserves_optional_flags(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(gh_adapter, "is_available", lambda: True)

    def run(argv, **kwargs):
        captured.append(argv)
        return gh_adapter.subprocess.CompletedProcess(argv, 0, URL, "")

    monkeypatch.setattr(gh_adapter, "_run", run)
    assert (
        _client(ProviderKind.GITHUB, tmp_path).create(
            title="t",
            body="b",
            base="main",
            head="f",
            draft=True,
            reviewers=["alice"],
            labels=["bug"],
            assignees=["bob"],
        )
        == URL
    )
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
