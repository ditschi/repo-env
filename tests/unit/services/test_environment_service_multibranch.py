from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry
from repoenv.errors import NothingMatchedError
from repoenv.services import environment_service


def test_parse_branch_list_splits_and_dedups() -> None:
    assert environment_service.parse_branch_list(["main,develop", "release/1.0", "main"]) == [
        "main",
        "develop",
        "release/1.0",
    ]
    assert environment_service.parse_branch_list([]) == []
    assert environment_service.parse_branch_list(None) == []


def test_build_create_plan_single_from_keeps_plain_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _s: ["alpha", "beta"])

    plan = environment_service.build_create_plan(
        name="e",
        source=source,
        dest=tmp_path / "envs",
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
        from_branches=["main"],
    )

    assert [w.worktree_dir for w in plan.worktrees] == ["alpha", "beta"]
    assert all(w.base == "main" for w in plan.worktrees)


def test_build_create_plan_multi_from_postfixes_dir_and_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _s: ["alpha"])

    plan = environment_service.build_create_plan(
        name="e",
        source=source,
        dest=tmp_path / "envs",
        include=None,
        exclude=None,
        branch="feature/x",
        alias=None,
        default_branch="main",
        from_branches=["main", "develop"],
    )

    by_dir = {w.worktree_dir: w for w in plan.worktrees}
    assert set(by_dir) == {"alpha-main", "alpha-develop"}
    assert by_dir["alpha-main"].base == "main"
    assert by_dir["alpha-main"].new_branch == "feature/x-main"
    assert by_dir["alpha-develop"].new_branch == "feature/x-develop"


def test_build_create_plan_sanitizes_slash_in_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _s: ["alpha"])

    plan = environment_service.build_create_plan(
        name="e",
        source=source,
        dest=tmp_path / "envs",
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch=None,
        from_branches=["release/1.0", "release/2.0"],
    )

    assert sorted(w.worktree_dir for w in plan.worktrees) == ["alpha-release-1.0", "alpha-release-2.0"]
    # No new branch requested -> detached checkout at each base.
    assert all(w.new_branch is None for w in plan.worktrees)


def test_build_add_plan_postfixes_existing_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Environment(name="web", path=Path("/tmp/envs/web"), source=Path("/tmp/src"), base_branch="main")
    env.repos.append(
        RepoEntry(repo="alpha", worktree_path=Path("/tmp/envs/web/alpha"), base="main", branch="main")
    )
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _s: ["alpha"])

    plan = environment_service.build_add_plan(
        env=env, include=["alpha"], exclude=None, from_branches=["develop"], branch=None
    )

    assert [w.worktree_dir for w in plan.worktrees] == ["alpha-develop"]
    assert plan.worktrees[0].base == "develop"


def test_build_add_plan_skips_already_present_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    env = Environment(name="web", path=Path("/tmp/envs/web"), source=Path("/tmp/src"), base_branch="main")
    env.repos.append(
        RepoEntry(
            repo="alpha",
            worktree_path=Path("/tmp/envs/web/alpha-develop"),
            base="develop",
            branch="develop",
        )
    )
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _s: ["alpha"])

    with pytest.raises(NothingMatchedError):
        environment_service.build_add_plan(
            env=env, include=["alpha"], exclude=None, from_branches=["develop"], branch=None
        )
