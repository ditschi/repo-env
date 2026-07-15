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


def test_list_repair_candidates_missing_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path, present=False)
    monkeypatch.setattr("repoenv.adapters.git_adapter.is_worktree_root", lambda _path: False)
    assert lifecycle_service.list_repair_candidates(env) == ["r0"]


def test_list_repair_candidates_skips_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path, present=True)
    monkeypatch.setattr("repoenv.adapters.git_adapter.is_worktree_root", lambda _path: True)
    assert lifecycle_service.list_repair_candidates(env) == []


def test_repair_environment_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path, present=False)
    src = tmp_path / "src" / "r0"
    src.mkdir(parents=True)

    monkeypatch.setattr("repoenv.adapters.git_adapter.is_worktree_root", lambda _path: False)
    monkeypatch.setattr(
        "repoenv.services.environment_service._ensure_worktree_path_is_clean", lambda _path: None
    )
    monkeypatch.setattr(
        "repoenv.services.environment_service._create_or_attach_worktree",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "repoenv.services.environment_service._resolve_source_sha",
        lambda *_args, **_kwargs: "abc123",
    )

    repaired, failed = lifecycle_service.repair_environment(env)
    assert repaired == ["r0"]
    assert failed == []
    assert env.repos[0].status == RepoStatus.OK
    assert env.repos[0].source_sha == "abc123"


def test_repair_environment_stray_dir_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path, present=True)
    wt = env.repos[0].worktree_path
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "stray.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr("repoenv.adapters.git_adapter.is_worktree_root", lambda _path: False)

    def boom(_path: Path) -> None:
        from repoenv.errors import UsageError

        raise UsageError("not a git repo")

    monkeypatch.setattr("repoenv.services.environment_service._ensure_worktree_path_is_clean", boom)

    repaired, failed = lifecycle_service.repair_environment(env)
    assert repaired == []
    assert failed == ["r0"]
    assert env.repos[0].status == RepoStatus.FAILED
