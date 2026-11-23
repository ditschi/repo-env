from __future__ import annotations

import pytest

from repoenv.adapters import gh_adapter


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def test_create_pr_builds_gh_argv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd=None):
        captured["argv"] = argv
        return _FakeCompleted(0, stdout="https://example/pr/7\n")

    monkeypatch.setattr(gh_adapter, "_run", _fake_run)
    pull_request = gh_adapter.GhPullRequest(
        title="T",
        body="B",
        head="feat",
        base="main",
        draft=True,
        reviewers=["r"],
        labels=["l"],
        assignees=["a"],
    )

    url = gh_adapter.create_pr(tmp_path, pull_request, repository="github.com/o/r")

    assert url == "https://example/pr/7"
    assert captured["argv"] == [
        *("pr", "create", "--title", "T", "--body", "B", "--head", "feat", "--base", "main", "--draft"),
        *("--reviewer", "r", "--label", "l", "--assignee", "a", "--repo", "github.com/o/r"),
    ]
