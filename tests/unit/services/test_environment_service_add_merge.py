from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry
from repoenv.domain.selection import SetOp
from repoenv.services import environment_service


def test_build_add_plan_skips_existing_and_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Environment(name="web", path=Path("/tmp/envs/web"), source=Path("/tmp/src"))
    env.repos.append(
        RepoEntry(repo="alpha", worktree_path=Path("/tmp/envs/web/alpha"), base="main", branch="main")
    )

    monkeypatch.setattr(
        environment_service.git_adapter, "discover_repos", lambda _: ["alpha", "beta", "gamma"]
    )
    monkeypatch.setattr(
        environment_service.git_adapter,
        "is_clean",
        lambda repo: repo.name != "gamma",
    )

    plan = environment_service.build_add_plan(env=env, include=["*"], exclude=None, force=False)
    assert plan.repos == ["beta"]
    assert plan.skipped["alpha"] == "already present in environment"
    assert plan.skipped["gamma"] == "source has uncommitted changes"


def test_build_merge_plan_union(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    left = Environment(name="a", path=Path("/tmp/envs/a"), source=source, base_branch="main")
    right = Environment(name="b", path=Path("/tmp/envs/b"), source=source, base_branch="main")
    left.repos.append(RepoEntry(repo="alpha", worktree_path=left.path / "alpha", base="main", branch="main"))
    right.repos.append(RepoEntry(repo="beta", worktree_path=right.path / "beta", base="main", branch="main"))

    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _: ["alpha", "beta"])
    monkeypatch.setattr(environment_service.git_adapter, "is_clean", lambda _: True)

    plan = environment_service.build_merge_plan(
        left=left,
        right=right,
        op=SetOp.UNION,
        dest_name="merged",
        dest_root=Path("/tmp/envs"),
        alias=None,
    )
    assert plan.name == "merged"
    assert plan.repos == ["alpha", "beta"]
