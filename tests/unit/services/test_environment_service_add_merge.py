from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.domain.selection import SetOp
from repoenv.errors import GitError
from repoenv.services import environment_service


def _sha_and_status(env: Environment) -> list[tuple[str, str | None, RepoStatus]]:
    return [(entry.repo, entry.source_sha, entry.status) for entry in env.repos]


def _assert_second_repo_failed_on_default_branch(env: Environment) -> None:
    assert [entry.status for entry in env.repos] == [RepoStatus.OK, RepoStatus.FAILED]
    assert "Could not determine the default branch" in (env.repos[1].note or "")


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
        target=environment_service.MergeTarget(name="merged", dest_root=Path("/tmp/envs")),
    )
    assert plan.name == "merged"
    assert plan.repos == ["alpha", "beta"]


def _stub_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    default_branch: Callable[[Path, str], str] = lambda _repo, _remote: "main",
    rev_parse: Callable[[Path, str], str] = lambda _repo, _ref: "deadbeef",
) -> None:
    """Silence the git calls made while executing a plan; override the interesting ones."""
    monkeypatch.setattr(environment_service.git_adapter, "default_branch", default_branch)
    monkeypatch.setattr(environment_service.git_adapter, "fetch", lambda _repo, _remote: None)
    monkeypatch.setattr(environment_service.git_adapter, "is_worktree_root", lambda _path: False)
    monkeypatch.setattr(environment_service.git_adapter, "prune_worktrees", lambda _repo: None)
    monkeypatch.setattr(environment_service.git_adapter, "branch_exists", lambda _repo, _branch: False)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, _worktree_path, **_kwargs: None,
    )
    monkeypatch.setattr(environment_service.git_adapter, "rev_parse", rev_parse)


def _fail_for_beta(error: Exception, result: str) -> Callable[[Path, str], str]:
    """A git stub that raises ``error`` for the ``beta`` repo and returns ``result`` otherwise."""

    def _stub(repo: Path, _arg: str) -> str:
        if repo.name == "beta":
            raise error
        return result

    return _stub


def _execute_alpha_beta(kind: str, tmp_path: Path, base_branch: str | None) -> Environment:
    """Execute a create or add plan for the repos ``alpha`` and ``beta``."""
    source = tmp_path / "src"
    (source / "alpha").mkdir(parents=True)
    (source / "beta").mkdir()
    repos = ["alpha", "beta"]

    if kind == "create":
        plan = environment_service.CreatePlan(
            name="test",
            env_path=tmp_path / "envs" / "test",
            source=source,
            base_branch=base_branch,
            new_branch=None,
            alias=None,
            repos=repos,
        )
        return environment_service.execute_create_plan(plan)

    env_path = tmp_path / "envs" / "web"
    env = Environment(name="web", path=env_path, source=source, base_branch=base_branch)
    add_plan = environment_service.AddPlan(env_name="web", source=source, env_path=env_path, repos=repos)
    return environment_service.execute_add_plan(env, add_plan)


_PLAN_KINDS = pytest.mark.parametrize(
    ("kind", "sha"), [("create", "deadbeef"), ("add", "cafebabe")], ids=["create", "add"]
)


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
    _stub_git(monkeypatch)
    monkeypatch.setattr(
        environment_service.git_adapter,
        "add_worktree",
        lambda _repo, worktree_path, **_kwargs: calls.append(worktree_path),
    )

    env = environment_service.execute_create_plan(plan)

    assert calls == [env_root / "test" / "org-a/shared", env_root / "test" / "org-b/shared"]
    assert [entry.repo for entry in env.repos] == ["org-a/shared", "org-b/shared"]
    assert [entry.worktree_path for entry in env.repos] == calls


@_PLAN_KINDS
def test_execute_plan_continues_when_rev_parse_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, sha: str
) -> None:
    _stub_git(monkeypatch, rev_parse=_fail_for_beta(RuntimeError("corrupt repo"), sha))

    env = _execute_alpha_beta(kind, tmp_path, base_branch="main")

    assert _sha_and_status(env) == [
        ("alpha", sha, RepoStatus.OK),
        ("beta", None, RepoStatus.OK),
    ]


@_PLAN_KINDS
def test_execute_plan_marks_repo_failed_when_default_branch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str, sha: str
) -> None:
    failing = _fail_for_beta(GitError("Could not determine the default branch."), "main")
    _stub_git(monkeypatch, default_branch=failing, rev_parse=lambda _repo, _ref: sha)

    env = _execute_alpha_beta(kind, tmp_path, base_branch=None)

    _assert_second_repo_failed_on_default_branch(env)


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
        environment_service.CreateRequest(
            name="new",
            source=source,
            dest=dest,
            include=["*"],
            default_branch="main",
        )
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
        environment_service.CreateRequest(
            name="copy",
            source=source,
            dest=dest,
            include=["*"],
            default_branch="main",
        )
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
        environment_service.CreateRequest(
            name="new",
            source=source,
            dest=dest,
            include=["*"],
            default_branch="main",
            include_worktrees=True,
        )
    )

    assert plan.repos == ["alpha", "nested-renv/alpha"]
