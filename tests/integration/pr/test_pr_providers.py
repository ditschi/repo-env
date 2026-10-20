"""Real worktrees and CLI dispatch, with only provider network calls mocked."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from repoenv.adapters import config_store, gh_adapter, git_adapter
from repoenv.adapters.scm import credentials, rest
from repoenv.adapters.scm.credentials import Credential
from repoenv.cli.app import app
from tests.integration.support.gitfixtures import run_git
from tests.integration.support.renv_helpers import init_renv


def _api_request(url, *, method, payload, headers):
    if method == "GET":
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


@pytest.mark.parametrize("push", [False, True])
def test_mixed_providers(repo_factory, repoenv_home, source_dir, worktrees_dir, monkeypatch, push):
    remotes = {
        "github": "git@github.com:o/github.git",
        "gitlab": "https://gitlab.com/group/sub/gitlab.git",
        "cloud": "git@bitbucket.org:o/cloud.git",
        "server": "https://bb.example/bitbucket/scm/PROJ/server.git",
        "azure": "git@ssh.dev.azure.com:v3/org/project/azure",
        "forgejo": "git@forge.example:o/forgejo.git",
    }
    for name in remotes:
        repo_factory.make_bare_and_clone(name)
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "env", "--branch", "feature/x"])
    assert result.exit_code == 0, result.output
    config = config_store.load_config()
    config.providers = {
        "bb.example": "bitbucket-server https://bb.example/bitbucket",
        "forge.example": "gitea",
    }
    config_store.save_config(config)
    for name, remote in remotes.items():
        source = repo_factory.clone_path(name)
        bare = str(repo_factory.remotes / f"{name}.git")
        run_git(["remote", "set-url", "origin", remote], cwd=source)
        run_git(["remote", "set-url", "--push", "origin", bare], cwd=source)
    monkeypatch.setattr(credentials, "resolve", lambda kind, host: Credential("token"))
    monkeypatch.setattr(gh_adapter, "is_available", lambda: True)
    calls = []

    def request(url, *, method, payload, headers):
        calls.append((url, method, payload))
        return _api_request(url, method=method, payload=payload, headers=headers)

    def gh_run(argv, **kwargs):
        calls.append(("gh", argv[1], None))
        assert argv[argv.index("--repo") + 1] == "github.com/o/github"
        return subprocess.CompletedProcess(
            argv, 0, "" if argv[1] == "list" else "https://github.com/pr/1", ""
        )

    monkeypatch.setattr(rest, "request", request)
    monkeypatch.setattr(gh_adapter, "_run", gh_run)
    with monkeypatch.context() as guard:
        guard.setattr(git_adapter, "push", lambda *a, **kw: pytest.fail("preflight must precede every push"))
        guard.setattr(rest, "request", lambda *a, **kw: pytest.fail("preflight must precede every API call"))
        result = runner.invoke(app, ["pr", "env", "--title", "t", "--draft", "--push"])
        assert result.exit_code != 0
        assert "does not support: --draft" in str(result.exception)
    args = ["pr", "env", "--title", "Fix {repo}", "--json"]
    if push:
        args.append("--push")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["created"]) == 6
    assert len(calls) == 12
    for name in remotes:
        exists = (
            run_git(
                [
                    "--git-dir",
                    str(repo_factory.remotes / f"{name}.git"),
                    "show-ref",
                    "--verify",
                    "refs/heads/feature/x",
                ],
                cwd=repo_factory.remotes / f"{name}.git",
                check=False,
            ).returncode
            == 0
        )
        assert exists is push

    # Fail/skip existing PRs without pushing or posting a second request.
    monkeypatch.setattr(
        gh_adapter,
        "_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "https://github.com/pr/1", ""),
    )
    for policy, expected in (("skip", 0), ("fail", 1)):
        result = runner.invoke(app, ["pr", "env", "-i", "github", "--title", "t", "--if-exists", policy])
        assert result.exit_code == expected, result.output
        assert ("exists" if policy == "skip" else "already exists") in (
            result.output + str(result.exception or "")
        )


def test_unsupported_options_prevent_push(repo_factory, repoenv_home, source_dir, worktrees_dir, monkeypatch):
    source = repo_factory.make_bare_and_clone("alpha")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "env"]).exit_code == 0
    run_git(["remote", "set-url", "origin", "git@bitbucket.org:o/r.git"], cwd=source)
    monkeypatch.setattr("repoenv.adapters.git_adapter.push", lambda *a, **kw: pytest.fail("must not push"))
    monkeypatch.setattr(rest, "request", lambda *a, **kw: pytest.fail("must not call API"))
    monkeypatch.setattr(gh_adapter, "is_available", lambda: False)
    result = runner.invoke(app, ["pr", "env", "--title", "t", "--reviewer", "alice", "--push"])
    assert result.exit_code != 0
    assert "does not support: --reviewer" in str(result.exception)
    result = runner.invoke(app, ["pr", "env", "--title", "t", "--dry-run"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("status", [201, 401])
def test_api_without_gh_and_lookup_errors(
    repo_factory, repoenv_home, source_dir, worktrees_dir, monkeypatch, status
):
    source = repo_factory.make_bare_and_clone("alpha")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "env", "--branch", "feature/x"]).exit_code == 0
    run_git(["remote", "set-url", "origin", "https://gitlab.com/o/r.git"], cwd=source)
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    monkeypatch.setattr(gh_adapter, "is_available", lambda: pytest.fail("non-GitHub must not check gh"))
    monkeypatch.setattr("repoenv.adapters.git_adapter.push", lambda *a, **kw: pytest.fail("must not push"))
    calls = []

    def request(url, *, method, payload, headers):
        calls.append(method)
        assert headers == {"PRIVATE-TOKEN": "test-token"}
        if method == "GET":
            return rest.HttpResponse(status if status == 401 else 200, {}, b"[]")
        return rest.HttpResponse(201, {}, b'{"web_url":"https://gitlab.com/pr/1"}')

    monkeypatch.setattr(rest, "request", request)
    args = ["pr", "env", "--title", "t"]
    if status == 401:
        args.append("--push")
    result = runner.invoke(app, args)
    if status == 201:
        assert result.exit_code == 0, result.output
        assert calls == ["GET", "POST"]
    else:
        assert result.exit_code != 0
        assert "HTTP 401" in str(result.exception)
        assert calls == ["GET"]
