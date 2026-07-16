from __future__ import annotations

import json

import pytest

from repoenv.adapters import gh_adapter
from repoenv.errors import GitError


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_list_org_memberships_parses_json_and_passes_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd=None):
        captured["argv"] = argv
        payload = [
            {"login": "acme", "role": "admin", "state": "active"},
            {"login": "beta-corp", "role": "member", "state": "pending"},
        ]
        return _FakeCompleted(0, stdout=json.dumps(payload))

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    result = gh_adapter.list_org_memberships(host="github.company.com")

    assert "--hostname" in captured["argv"]
    assert "github.company.com" in captured["argv"]
    assert result == [
        gh_adapter.OrgMembership(login="acme", role="admin", state="active"),
        gh_adapter.OrgMembership(login="beta-corp", role="member", state="pending"),
    ]


def test_list_org_memberships_omits_hostname_when_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd=None):
        captured["argv"] = argv
        return _FakeCompleted(0, stdout="[]")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    assert gh_adapter.list_org_memberships() == []
    assert "--hostname" not in captured["argv"]


def test_list_org_memberships_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(argv, *, cwd=None):
        return _FakeCompleted(1, stderr="not authenticated")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    with pytest.raises(GitError, match="not authenticated"):
        gh_adapter.list_org_memberships()


def test_list_owner_repos_tries_orgs_then_users(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, *, cwd=None):
        calls.append(argv)
        if argv[1].startswith("orgs/"):
            return _FakeCompleted(1, stderr="404 Not Found")
        return _FakeCompleted(0, stdout=json.dumps(["repo-a", "repo-b"]))

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    result = gh_adapter.list_owner_repos("myself")

    assert result == ["repo-a", "repo-b"]
    assert calls[0][1] == "orgs/myself/repos"
    assert calls[1][1] == "users/myself/repos"


def test_list_owner_repos_succeeds_on_orgs_endpoint_without_trying_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, *, cwd=None):
        calls.append(argv)
        return _FakeCompleted(0, stdout=json.dumps(["repo-a"]))

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    result = gh_adapter.list_owner_repos("acme", host="github.company.com")

    assert result == ["repo-a"]
    assert len(calls) == 1
    assert "--hostname" in calls[0]


def test_list_owner_repos_raises_when_both_endpoints_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(argv, *, cwd=None):
        return _FakeCompleted(1, stderr="404 Not Found")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    with pytest.raises(GitError, match="Could not list repositories for 'ghost'"):
        gh_adapter.list_owner_repos("ghost")


def test_git_protocol_returns_gh_config_value(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd=None):
        captured["argv"] = argv
        return _FakeCompleted(0, stdout="https\n")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    assert gh_adapter.git_protocol("github.company.com") == "https"
    assert captured["argv"] == ["config", "get", "git_protocol", "-h", "github.company.com"]


def test_git_protocol_falls_back_to_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(argv, *, cwd=None):
        return _FakeCompleted(0, stdout="")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)

    assert gh_adapter.git_protocol() == "ssh"
