"""Tests for pr_service bulk PR creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters import config_store, gh_adapter
from repoenv.domain.models import Environment, RepoEntry
from repoenv.services import pr_service


@pytest.fixture(autouse=True)
def github_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_store, "load_config", lambda: config_store.UserConfig())
    monkeypatch.setattr(
        "repoenv.adapters.git_adapter.remote_url", lambda wt, remote: "git@github.com:o/r.git"
    )
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)


def _env(tmp_path: Path) -> Environment:
    wt = tmp_path / "env" / "r0"
    wt.mkdir(parents=True)
    entry = RepoEntry(repo="r0", worktree_path=wt, remote="origin", base="main", branch="feature")
    return Environment(name="e", path=tmp_path / "env", source=tmp_path / "src", repos=[entry])


def test_create_prs_renders_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path)
    monkeypatch.setattr("repoenv.adapters.git_adapter.current_branch", lambda wt: "feature")
    monkeypatch.setattr("repoenv.adapters.gh_adapter.existing_pr_url", lambda wt, **kwargs: None)

    captured: dict[str, str] = {}

    def fake_create(worktree, *, title, body, base, head, draft, reviewers, labels, assignees, repository):
        captured["title"] = title
        assert repository == "github.com/o/r"
        return "https://example/pr/1"

    monkeypatch.setattr("repoenv.adapters.gh_adapter.create_pr", fake_create)

    outcome = pr_service.create_prs(
        env,
        title="Fix {repo} on {env}",
        body="body",
        base=None,
        draft=False,
        reviewers=[],
        labels=[],
        assignees=[],
        push=False,
        skip_no_diff=False,
        if_exists="skip",
    )
    assert captured["title"] == "Fix r0 on e"
    assert len(outcome.created) == 1


def test_create_prs_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path)
    monkeypatch.setattr("repoenv.adapters.git_adapter.current_branch", lambda wt: "feature")
    monkeypatch.setattr("repoenv.adapters.gh_adapter.existing_pr_url", lambda wt, **kwargs: "https://x/1")

    outcome = pr_service.create_prs(
        env,
        title="t",
        body="b",
        base=None,
        draft=False,
        reviewers=[],
        labels=[],
        assignees=[],
        push=False,
        skip_no_diff=False,
        if_exists="skip",
    )
    assert outcome.created == []
    assert outcome.skipped[0].reason == "exists"


def test_create_prs_skip_no_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path)
    monkeypatch.setattr("repoenv.adapters.git_adapter.current_branch", lambda wt: "feature")
    monkeypatch.setattr("repoenv.adapters.git_adapter.has_diff", lambda wt, base_ref: False)

    outcome = pr_service.create_prs(
        env,
        title="t",
        body="b",
        base=None,
        draft=False,
        reviewers=[],
        labels=[],
        assignees=[],
        push=False,
        skip_no_diff=True,
        if_exists="skip",
    )
    assert outcome.created == []
    assert outcome.skipped[0].reason == "no diff"


def test_pr_result_dataclass() -> None:
    result = gh_adapter.PrResult("r0", "url", created=True)
    assert result.created is True
    assert result.skipped is False


def test_skip_no_diff_uses_base_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr("repoenv.adapters.git_adapter.current_branch", lambda wt: "feature")

    def has_diff(worktree, ref):
        seen.append(ref)
        return False

    monkeypatch.setattr("repoenv.adapters.git_adapter.has_diff", has_diff)
    pr_service.create_prs(
        _env(tmp_path),
        title="t",
        body="",
        base="release",
        draft=False,
        reviewers=[],
        labels=[],
        assignees=[],
        push=False,
        skip_no_diff=True,
        if_exists="skip",
    )
    assert seen == ["origin/release"]
