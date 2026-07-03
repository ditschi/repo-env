"""Tests for lifecycle_service helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.services import lifecycle_service


def _env(tmp_path: Path, present: bool = True) -> Environment:
    wt = tmp_path / "env" / "r0"
    if present:
        wt.mkdir(parents=True)
    entry = RepoEntry(repo="r0", worktree_path=wt, remote="origin", base="main", branch="feature")
    return Environment(name="e", path=tmp_path / "env", source=tmp_path / "src", repos=[entry])


def test_check_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path)
    monkeypatch.setattr("repoenv.adapters.git_adapter.is_clean", lambda path: False)
    assert lifecycle_service.check_dirty(env) == ["r0"]


def test_assess_health_missing_marks_stale(tmp_path: Path) -> None:
    env = _env(tmp_path, present=False)
    health = lifecycle_service.assess_health(env)
    assert health[0].present is False
    assert env.repos[0].status == RepoStatus.STALE


def test_sync_environment_collects_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path)

    def boom(repo: Path, remote: str) -> None:
        raise RuntimeError("no network")

    monkeypatch.setattr("repoenv.adapters.git_adapter.fetch", boom)
    assert lifecycle_service.sync_environment(env) == ["r0"]
