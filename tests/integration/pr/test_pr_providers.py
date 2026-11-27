"""Real worktrees and CLI dispatch, with only provider network calls mocked."""

from __future__ import annotations

import json
import subprocess

import pytest

from repoenv.adapters import config_store, gh_adapter, git_adapter
from repoenv.adapters.scm import credentials, rest
from repoenv.adapters.scm.credentials import Credential
from tests.integration.support.gitfixtures import run_git
from tests.integration.support.renv_helpers import Renv


def _api_request(request):
    url, payload = request.url, request.payload
    if request.method == "GET":
        data = [] if "/api/v" in url else {"values": [], "value": []}
    elif "gitlab.com" in url:
        assert payload["source_branch"] == "feature/x"
        assert payload["target_branch"] == "main"
        data = {"web_url": "https://gitlab.com/mr/1"}
    elif "api.bitbucket.org" in url:
        data = {"links": {"html": {"href": "https://bitbucket.org/pr/1"}}}
    elif "bb.example" in url:
        data = {"links": {"self": [{"href": "https://bb.example/pr/1"}]}}
    elif "dev.azure.com" in url:
        data = {"pullRequestId": 1}
    else:
        data = {"html_url": "https://forge.example/pr/1"}
    return rest.HttpResponse(200, {}, json.dumps(data).encode())


_REMOTES = {
    "github": "git@github.com:o/github.git",
    "gitlab": "https://gitlab.com/group/sub/gitlab.git",
    "cloud": "git@bitbucket.org:o/cloud.git",
    "server": "https://bb.example/bitbucket/scm/PROJ/server.git",
    "azure": "git@ssh.dev.azure.com:v3/org/project/azure",
    "forgejo": "git@forge.example:o/forgejo.git",
}


def _mixed_provider_env(renv: Renv) -> None:
    """Create env 'env' on feature/x with one repo per provider; pushes land in local bare repos."""
    clones = renv.setup(*_REMOTES)
    renv.ok("create", "env", "--branch", "feature/x")
    config = config_store.load_config()
    config.providers = {
        "bb.example": "bitbucket-server https://bb.example/bitbucket",
        "forge.example": "gitea",
    }
    config_store.save_config(config)
    for source, remote in zip(clones, _REMOTES.values()):
        bare = str(renv.repos.remotes / f"{source.name}.git")
        run_git(["remote", "set-url", "origin", remote], cwd=source)
        run_git(["remote", "set-url", "--push", "origin", bare], cwd=source)


def _alpha_env_with_origin(renv: Renv, origin: str, *create_opts: str) -> None:
    """Create env 'env' holding ``alpha``, whose source clone's origin then points at ``origin``."""
    (source,) = renv.setup("alpha")
    renv.ok("create", "env", *create_opts)
    run_git(["remote", "set-url", "origin", origin], cwd=source)


def _branch_pushed(renv: Renv, name: str) -> bool:
    bare = renv.repos.remotes / f"{name}.git"
    argv = ["--git-dir", str(bare), "show-ref", "--verify", "refs/heads/feature/x"]
    return run_git(argv, cwd=bare, check=False).returncode == 0


def _forbid_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repoenv.adapters.git_adapter.push", lambda *a, **kw: pytest.fail("must not push"))


def _assert_preflight_blocks_unsupported_draft(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as guard:
        guard.setattr(git_adapter, "push", lambda *a, **kw: pytest.fail("preflight must precede every push"))
        guard.setattr(rest, "send", lambda *a, **kw: pytest.fail("preflight must precede every API call"))
        result = renv.invoke("pr", "env", "--title", "t", "--draft", "--push")
        assert result.exit_code != 0
        assert "does not support: --draft" in str(result.exception)


def _assert_existing_pr_policies(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail/skip existing PRs without pushing or posting a second request."""
    monkeypatch.setattr(
        gh_adapter,
        "_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "https://github.com/pr/1", ""),
    )
    for policy, expected, text in (("skip", 0, "exists"), ("fail", 1, "already exists")):
        result = renv.invoke("pr", "env", "-i", "github", "--title", "t", "--if-exists", policy)
        assert result.exit_code == expected, result.output
        assert text in result.output + str(result.exception or "")


@pytest.mark.parametrize("push", [False, True])
def test_mixed_providers(renv: Renv, monkeypatch: pytest.MonkeyPatch, push: bool) -> None:
    _mixed_provider_env(renv)
    monkeypatch.setattr(credentials, "resolve", lambda kind, host: Credential("token"))
    monkeypatch.setattr(gh_adapter, "is_available", lambda: True)
    calls = []

    def request(sent):
        calls.append((sent.url, sent.method, sent.payload))
        return _api_request(sent)

    def gh_run(argv, **kwargs):
        calls.append(("gh", argv[1], None))
        assert argv[argv.index("--repo") + 1] == "github.com/o/github"
        return subprocess.CompletedProcess(
            argv, 0, "" if argv[1] == "list" else "https://github.com/pr/1", ""
        )

    monkeypatch.setattr(rest, "send", request)
    monkeypatch.setattr(gh_adapter, "_run", gh_run)
    _assert_preflight_blocks_unsupported_draft(renv, monkeypatch)
    push_opts = ["--push"] if push else []
    result = renv.ok("pr", "env", "--title", "Fix {repo}", "--json", *push_opts)
    assert (len(json.loads(result.stdout)["created"]), len(calls)) == (6, 12)
    assert {name: _branch_pushed(renv, name) for name in _REMOTES} == dict.fromkeys(_REMOTES, push)
    _assert_existing_pr_policies(renv, monkeypatch)


def test_unsupported_options_prevent_push(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    _alpha_env_with_origin(renv, "git@bitbucket.org:o/r.git")
    _forbid_push(monkeypatch)
    monkeypatch.setattr(rest, "send", lambda *a, **kw: pytest.fail("must not call API"))
    monkeypatch.setattr(gh_adapter, "is_available", lambda: False)
    result = renv.invoke("pr", "env", "--title", "t", "--reviewer", "alice", "--push")
    assert result.exit_code != 0
    assert "does not support: --reviewer" in str(result.exception)
    renv.ok("pr", "env", "--title", "t", "--dry-run")


def _gitlab_without_gh(renv: Renv, monkeypatch: pytest.MonkeyPatch, lookup_status: int) -> list[str]:
    """Env on a GitLab origin with a token, gh forbidden; the MR lookup answers ``lookup_status``.

    Returns the list that records each API call's HTTP method.
    """
    _alpha_env_with_origin(renv, "https://gitlab.com/o/r.git", "--branch", "feature/x")
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    monkeypatch.setattr(gh_adapter, "is_available", lambda: pytest.fail("non-GitHub must not check gh"))
    _forbid_push(monkeypatch)
    calls: list[str] = []

    def request(sent):
        calls.append(sent.method)
        assert sent.headers == {"PRIVATE-TOKEN": "test-token"}
        if sent.method == "GET":
            return rest.HttpResponse(lookup_status, {}, b"[]")
        return rest.HttpResponse(201, {}, b'{"web_url":"https://gitlab.com/pr/1"}')

    monkeypatch.setattr(rest, "send", request)
    return calls


def test_api_without_gh_creates_merge_request(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _gitlab_without_gh(renv, monkeypatch, lookup_status=200)
    renv.ok("pr", "env", "--title", "t")
    assert calls == ["GET", "POST"]


def test_api_lookup_error_stops_before_push(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _gitlab_without_gh(renv, monkeypatch, lookup_status=401)
    result = renv.invoke("pr", "env", "--title", "t", "--push")
    assert result.exit_code != 0
    assert "HTTP 401" in str(result.exception)
    assert calls == ["GET"]
