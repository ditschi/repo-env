"""Unit tests for new environment_service features:
- Linked worktree filtering (issue #2)
- Absolute path storage (issues #6 & #8)
- Non-empty dest dir check (issue #3)
- ~ / absolute-path pattern normalisation (issue #5)
- Progress callback (issue #7)
- skipped_worktrees reported in plan (issue #2)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoStatus
from repoenv.errors import UsageError
from repoenv.services import environment_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_monkeypatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence git calls that are irrelevant to these tests."""
    monkeypatch.setattr(environment_service.git_adapter, "default_branch", lambda _r, _rem: "main")
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _r, _rem: None)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _r: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _r, _b: False)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _p: False)
    monkeypatch.setattr(environment_service.git_adapter, "add_worktree", lambda *a, **kw: None)
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", lambda _r, _ref: "abc123")
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _p: False)


# ---------------------------------------------------------------------------
# Linked-worktree filtering
# ---------------------------------------------------------------------------


def test_build_create_plan_skips_linked_worktrees_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    wt = source / "linked-wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /main/.git/worktrees/linked-wt\n")

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _: ["main-repo", "linked-wt"],
    )
    monkeypatch.setattr(
        environment_service.git_adapter,
        "is_linked_worktree",
        lambda path: path.name == "linked-wt",
    )

    plan = environment_service.build_create_plan(
        name="env",
        source=source,
        dest=tmp_path / "dest",
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
        include_worktrees=False,
    )

    assert "main-repo" in plan.repos
    assert "linked-wt" not in plan.repos
    assert "linked-wt" in plan.skipped_worktrees


def test_build_create_plan_includes_linked_worktrees_when_flag_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _: ["main-repo", "linked-wt"],
    )
    monkeypatch.setattr(
        environment_service.git_adapter,
        "is_linked_worktree",
        lambda path: path.name == "linked-wt",
    )

    plan = environment_service.build_create_plan(
        name="env",
        source=source,
        dest=tmp_path / "dest",
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
        include_worktrees=True,
    )

    assert "linked-wt" in plan.repos
    assert plan.skipped_worktrees == []


def test_execute_create_plan_marks_linked_worktree_source_as_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()

    plan = environment_service.CreatePlan(
        name="env",
        env_path=tmp_path / "dest" / "env",
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=["linked-wt"],
    )

    monkeypatch.setattr(
        environment_service.git_adapter,
        "is_linked_worktree",
        lambda p: p.name == "linked-wt",
    )
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _p: False)
    monkeypatch.setattr(environment_service.git_adapter, "default_branch", lambda _r, _rem: "main")
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", lambda _r, _ref: "abc123")

    env = environment_service.execute_create_plan(plan)

    assert env.repos[0].status is RepoStatus.FAILED
    assert env.repos[0].note is not None
    assert "linked worktree" in env.repos[0].note


def test_build_add_plan_skips_linked_worktrees_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    env = Environment(name="e", path=tmp_path / "envs" / "e", source=source)

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _: ["main-repo", "linked-wt"],
    )
    monkeypatch.setattr(
        environment_service.git_adapter,
        "is_linked_worktree",
        lambda path: path.name == "linked-wt",
    )

    plan = environment_service.build_add_plan(env=env, include=None, exclude=None)

    assert "main-repo" in plan.repos
    assert "linked-wt" not in plan.repos
    assert "linked-wt" in plan.skipped_worktrees


# ---------------------------------------------------------------------------
# Absolute paths stored in plan
# ---------------------------------------------------------------------------


def test_build_create_plan_stores_absolute_env_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _: ["repo-a"])
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _: False)

    plan = environment_service.build_create_plan(
        name="myenv",
        source=source,
        dest=tmp_path / "dest",
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.env_path.is_absolute()
    assert plan.source.is_absolute()


def test_build_create_plan_resolves_relative_dest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Even if dest is given as a relative path, plan.env_path must be absolute."""
    source = tmp_path / "source"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()

    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _: ["repo-a"])
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _: False)

    # Use a real Path — resolve() inside build_create_plan makes it absolute.
    plan = environment_service.build_create_plan(
        name="myenv",
        source=source,
        dest=dest,
        include=None,
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.env_path.is_absolute()
    assert plan.env_path == (dest / "myenv").resolve()


# ---------------------------------------------------------------------------
# Non-empty dest dir raises UsageError
# ---------------------------------------------------------------------------


def test_execute_create_plan_raises_when_dest_exists_with_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    env_path = tmp_path / "envs" / "myenv"
    env_path.mkdir(parents=True)
    (env_path / "stray-file.txt").write_text("leftover", encoding="utf-8")

    plan = environment_service.CreatePlan(
        name="myenv",
        env_path=env_path,
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=["repo-a"],
    )

    with pytest.raises(UsageError, match="already exists and is not empty"):
        environment_service.execute_create_plan(plan)


def test_execute_create_plan_does_not_raise_when_dest_has_renv_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A directory that already has a .repoenv.json is a resumed env, not a conflict."""
    source = tmp_path / "source"
    env_path = tmp_path / "envs" / "myenv"
    env_path.mkdir(parents=True)
    (env_path / ".repoenv.json").write_text("{}", encoding="utf-8")

    plan = environment_service.CreatePlan(
        name="myenv",
        env_path=env_path,
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=[],  # nothing to do
    )

    _base_monkeypatches(monkeypatch)
    env = environment_service.execute_create_plan(plan)
    assert env.name == "myenv"


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


def test_execute_create_plan_calls_progress_callback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    env_path = tmp_path / "envs" / "myenv"

    plan = environment_service.CreatePlan(
        name="myenv",
        env_path=env_path,
        source=source,
        base_branch="main",
        new_branch=None,
        alias=None,
        repos=["alpha", "beta"],
    )

    _base_monkeypatches(monkeypatch)
    calls: list[tuple[str, int, int]] = []
    environment_service.execute_create_plan(
        plan, on_repo_start=lambda name, cur, tot: calls.append((name, cur, tot))
    )

    assert calls == [("alpha", 1, 2), ("beta", 2, 2)]


def test_execute_add_plan_calls_progress_callback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    env_path = tmp_path / "envs" / "myenv"
    env = Environment(name="myenv", path=env_path, source=source, base_branch="main")
    plan = environment_service.AddPlan(
        env_name="myenv", source=source, env_path=env_path, repos=["gamma", "delta"]
    )

    _base_monkeypatches(monkeypatch)
    calls: list[tuple[str, int, int]] = []
    environment_service.execute_add_plan(
        env, plan, on_repo_start=lambda name, cur, tot: calls.append((name, cur, tot))
    )

    assert calls == [("gamma", 1, 2), ("delta", 2, 2)]


# ---------------------------------------------------------------------------
# Pattern normalisation: ~ expansion
# ---------------------------------------------------------------------------


def test_build_create_plan_expands_tilde_in_include(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A pattern starting with ~ must be expanded and made relative to source."""
    source = tmp_path / "source"
    source.mkdir()

    # Fake home so ~ → tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))

    # discover_repos returns paths RELATIVE to source
    monkeypatch.setattr(environment_service.git_adapter, "discover_repos", lambda _: ["demo-repo", "other"])
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _: False)

    # Pattern: ~/source/demo-*  →  after ~ expansion: tmp_path/source/demo-*
    # After relativising to source (tmp_path/source): demo-*
    pattern = "~/source/demo-*"
    plan = environment_service.build_create_plan(
        name="env",
        source=source,
        dest=tmp_path / "dest",
        include=[pattern],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.repos == ["demo-repo"]


# ---------------------------------------------------------------------------
# Pattern normalisation: ** glob in include
# ---------------------------------------------------------------------------


def test_build_create_plan_double_star_include(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    monkeypatch.setattr(
        environment_service.git_adapter,
        "discover_repos",
        lambda _: ["org/demo-api", "org/demo-ui", "org/other"],
    )
    monkeypatch.setattr(environment_service.git_adapter, "is_linked_worktree", lambda _: False)

    plan = environment_service.build_create_plan(
        name="env",
        source=source,
        dest=tmp_path / "dest",
        include=["**/demo-*"],
        exclude=None,
        branch=None,
        alias=None,
        default_branch="main",
    )

    assert plan.repos == ["org/demo-api", "org/demo-ui"]
    assert "org/other" not in plan.repos
