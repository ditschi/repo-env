from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp
from repoenv.errors import GitError
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
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
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


def test_execute_create_plan_continues_when_rev_parse_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    env_root = tmp_path / "envs"
    source.mkdir()
    (source / "alpha").mkdir()
    (source / "beta").mkdir()

    plan = environment_service.CreatePlan(
        name="test",
        env_path=env_root / "test",
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=["alpha", "beta"],
    )

    monkeypatch.setattr(environment_service.git_adapter, "default_branch", lambda _repo, _remote: "main")
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _path: False)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _repo, _branch: False)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, _worktree_path, **_kwargs: None,
    )

    def _rev_parse(repo: Path, _ref: str) -> str:
        if repo.name == "beta":
            raise RuntimeError("corrupt repo")
        return "deadbeef"

    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", _rev_parse)

    env = environment_service.execute_create_plan(plan)

    assert [entry.repo for entry in env.repos] == ["alpha", "beta"]
    assert env.repos[0].source_sha == "deadbeef"
    assert env.repos[0].status == RepoStatus.OK
    assert env.repos[1].source_sha is None
    assert env.repos[1].status == RepoStatus.OK


def test_execute_create_plan_marks_repo_failed_when_default_branch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    env_root = tmp_path / "envs"
    source.mkdir()
    (source / "alpha").mkdir()
    (source / "beta").mkdir()

    plan = environment_service.CreatePlan(
        name="test",
        env_path=env_root / "test",
        source=source,
        base_branch=None,
        new_branch=None,
        alias=None,
        repos=["alpha", "beta"],
    )

    def _default_branch(repo: Path, _remote: str) -> str:
        if repo.name == "beta":
            raise GitError("Could not determine the default branch.")
        return "main"

    monkeypatch.setattr(environment_service.git_adapter, "default_branch", _default_branch)
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _path: False)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _repo, _branch: False)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, _worktree_path, **_kwargs: None,
    )
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", lambda _repo, _ref: "deadbeef")

    env = environment_service.execute_create_plan(plan)

    assert env.repos[0].status == RepoStatus.OK
    assert env.repos[1].status == RepoStatus.FAILED
    assert env.repos[1].note is not None
    assert "Could not determine the default branch" in env.repos[1].note


def test_execute_add_plan_marks_repo_failed_when_default_branch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    env_path = tmp_path / "envs" / "web"
    source.mkdir(parents=True)
    (source / "alpha").mkdir()
    (source / "beta").mkdir()

    env = Environment(name="web", path=env_path, source=source, base_branch=None)
    plan = environment_service.AddPlan(
        env_name="web", source=source, env_path=env_path, repos=["alpha", "beta"]
    )

    def _default_branch(repo: Path, _remote: str) -> str:
        if repo.name == "beta":
            raise GitError("Could not determine the default branch.")
        return "main"

    monkeypatch.setattr(environment_service.git_adapter, "default_branch", _default_branch)
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _path: False)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _repo, _branch: False)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, _worktree_path, **_kwargs: None,
    )
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", lambda _repo, _ref: "cafebabe")

    result = environment_service.execute_add_plan(env, plan)

    assert result.repos[0].status == RepoStatus.OK
    assert result.repos[1].status == RepoStatus.FAILED
    assert result.repos[1].note is not None
    assert "Could not determine the default branch" in result.repos[1].note


def test_execute_add_plan_continues_when_rev_parse_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    env_path = tmp_path / "envs" / "web"
    source.mkdir(parents=True)
    (source / "alpha").mkdir()
    (source / "beta").mkdir()

    env = Environment(name="web", path=env_path, source=source, base_branch="main")
    plan = environment_service.AddPlan(
        env_name="web", source=source, env_path=env_path, repos=["alpha", "beta"]
    )

    monkeypatch.setattr(environment_service.git_adapter, "default_branch", lambda _repo, _remote: "main")
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _path: False)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _repo, _branch: False)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, _worktree_path, **_kwargs: None,
    )

    def _rev_parse(repo: Path, _ref: str) -> str:
        if repo.name == "beta":
            raise RuntimeError("corrupt repo")
        return "cafebabe"

    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", _rev_parse)

    result = environment_service.execute_add_plan(env, plan)

    assert [entry.repo for entry in result.repos] == ["alpha", "beta"]
    assert result.repos[0].source_sha == "cafebabe"
    assert result.repos[0].status == RepoStatus.OK
    assert result.repos[1].source_sha is None
    assert result.repos[1].status == RepoStatus.OK


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


def test_build_create_plan_include_worktrees_overrides_default_exclusion(
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
    # No linked worktrees in this test
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _: False)

    plan = environment_service.build_create_plan(
        name="new",
        source=source,
        dest=dest,
        include=["*"],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
        include_worktrees=True,
    )

    assert plan.repos == ["alpha", "nested-renv/alpha"]
