from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry
from repoenv.domain.selection import SetOp
from repoenv.services import environment_service


def test_build_add_plan_skips_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Environment(name="web", path=Path("/tmp/envs/web"), source=Path("/tmp/src"))
    env.repos.append(
        RepoEntry(repo="alpha", worktree_path=Path("/tmp/envs/web/alpha"), base="main", branch="main")
    )

    monkeypatch.setattr(
        environment_service.git_adapter, "discover_repos", lambda _: ["alpha", "beta", "gamma"]
    )

    plan = environment_service.build_add_plan(env=env, include=["*"], exclude=None)
    assert plan.repos == ["beta", "gamma"]
    assert plan.skipped["alpha"] == "already present in environment"


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


def test_execute_create_plan_preserves_nested_repo_structure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    env_root = tmp_path / "envs"
    source.mkdir()

    plan = environment_service.CreatePlan(
        name="test",
        env_path=env_root / "test",
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=["org-a/shared", "org-b/shared"],
    )

    calls: list[Path] = []
    monkeypatch.setattr(environment_service.git_adapter, "default_branch", lambda _repo, _remote: "main")
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, worktree_path, **_kwargs: calls.append(worktree_path),
    )
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", lambda _repo, _ref: "deadbeef")

    env = environment_service.execute_create_plan(plan)

    assert calls == [env_root / "test" / "org-a/shared", env_root / "test" / "org-b/shared"]
    assert [entry.repo for entry in env.repos] == ["org-a/shared", "org-b/shared"]
    assert [entry.worktree_path for entry in env.repos] == calls


def test_build_create_plan_excludes_nested_renv_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    dest = source / "envs"
    source.mkdir(parents=True)
    renv_root = source / "envs" / "existing"
    renv_root.mkdir(parents=True)
    (renv_root / ".repoenv.marker.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _source: ["alpha", "envs/existing/alpha"],
    )

    plan = environment_service.build_create_plan(
        name="new",
        source=source,
        dest=dest,
        include=["*"],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.repos == ["alpha"]


def test_build_create_plan_keeps_repos_when_source_is_renv_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "envs" / "existing"
    dest = tmp_path / "output"
    source.mkdir(parents=True)
    (source / ".repoenv.marker.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _source: ["alpha", "beta"])

    plan = environment_service.build_create_plan(
        name="copy",
        source=source,
        dest=dest,
        include=["*"],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.repos == ["alpha", "beta"]


def test_build_create_plan_include_renv_overrides_default_exclusion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir(parents=True)
    renv_root = source / "nested-renv"
    renv_root.mkdir(parents=True)
    (renv_root / ".repoenv.marker.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _source: ["alpha", "nested-renv/alpha"],
    )

    plan = environment_service.build_create_plan(
        name="new",
        source=source,
        dest=dest,
        include=["*"],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
        include_renv=True,
    )

    assert plan.repos == ["alpha", "nested-renv/alpha"]
