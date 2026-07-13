from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters import git_adapter
from repoenv.errors import GitError


def test_discover_repos_recurses_and_returns_relative_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    repo_nested = source / "forge.example" / "org-core" / "repo-alpha"
    repo_top = source / "simple-repo"
    not_repo = source / "docs"

    repo_nested.mkdir(parents=True)
    repo_top.mkdir(parents=True)
    not_repo.mkdir(parents=True)

    (repo_nested / ".git").mkdir()
    (repo_top / ".git").mkdir()

    found = git_adapter.discover_repos(source)

    assert found == ["forge.example/org-core/repo-alpha", "simple-repo"]


def test_discover_repos_returns_empty_when_source_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    assert git_adapter.discover_repos(missing) == []


def test_discover_repos_includes_all_repos_for_later_selection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    repo_match = source / "forge.example" / "org-core" / "repo-alpha"
    repo_other = source / "forge.example" / "org-core" / "repo-gamma"

    repo_match.mkdir(parents=True)
    repo_other.mkdir(parents=True)
    (repo_match / ".git").mkdir()
    (repo_other / ".git").mkdir()

    found = git_adapter.discover_repos(source)

    assert found == [
        "forge.example/org-core/repo-alpha",
        "forge.example/org-core/repo-gamma",
    ]


def test_discover_repos_matches_git_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    repo = source / "forge.example" / "org-core" / "repo-link"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: /tmp/fake", encoding="utf-8")

    found = git_adapter.discover_repos(source)

    assert found == ["forge.example/org-core/repo-link"]


def test_discover_repos_collects_multiple_prefix_depths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    repo_depth_0 = source / "org-core" / "repo-a"
    repo_depth_1 = source / "forge.example" / "org-core" / "repo-b"
    repo_depth_2 = source / "sandbox" / "forge.example" / "org-core" / "repo-c"

    repo_depth_0.mkdir(parents=True)
    repo_depth_1.mkdir(parents=True)
    repo_depth_2.mkdir(parents=True)
    (repo_depth_0 / ".git").mkdir()
    (repo_depth_1 / ".git").mkdir()
    (repo_depth_2 / ".git").mkdir()

    found = git_adapter.discover_repos(source)

    assert found == [
        "forge.example/org-core/repo-b",
        "org-core/repo-a",
        "sandbox/forge.example/org-core/repo-c",
    ]


def test_default_branch_prefers_main_when_head_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def _fake_run(args, *, cwd=None, check=True):
        _ = (cwd, check)
        if args[:3] == ["ls-remote", "--symref", "origin"]:
            return git_adapter.GitResult(0, "", "")
        if args[:3] == ["remote", "show", "origin"]:
            return git_adapter.GitResult(0, "  HEAD branch: (unknown)\n", "")
        if args[:3] == ["ls-remote", "--heads", "origin"]:
            return git_adapter.GitResult(
                0,
                "\n".join(
                    [
                        "1111111111111111111111111111111111111111\trefs/heads/feature/x",
                        "2222222222222222222222222222222222222222\trefs/heads/main",
                    ]
                ),
                "",
            )
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(git_adapter, "_run", _fake_run)

    assert git_adapter.default_branch(repo, "origin") == "main"


def test_default_branch_uses_single_remote_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def _fake_run(args, *, cwd=None, check=True):
        _ = (cwd, check)
        if args[:3] == ["ls-remote", "--symref", "origin"]:
            return git_adapter.GitResult(0, "", "")
        if args[:3] == ["remote", "show", "origin"]:
            return git_adapter.GitResult(0, "  HEAD branch: (unknown)\n", "")
        if args[:3] == ["ls-remote", "--heads", "origin"]:
            return git_adapter.GitResult(
                0,
                "3333333333333333333333333333333333333333\trefs/heads/release/r1\n",
                "",
            )
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(git_adapter, "_run", _fake_run)

    assert git_adapter.default_branch(repo, "origin") == "release/r1"


def test_default_branch_raises_when_ambiguous(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def _fake_run(args, *, cwd=None, check=True):
        _ = (cwd, check)
        if args[:3] == ["ls-remote", "--symref", "origin"]:
            return git_adapter.GitResult(0, "", "")
        if args[:3] == ["remote", "show", "origin"]:
            return git_adapter.GitResult(0, "  HEAD branch: (unknown)\n", "")
        if args[:3] == ["ls-remote", "--heads", "origin"]:
            return git_adapter.GitResult(
                0,
                "\n".join(
                    [
                        "1111111111111111111111111111111111111111\trefs/heads/release/r1",
                        "2222222222222222222222222222222222222222\trefs/heads/feature/x",
                    ]
                ),
                "",
            )
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(git_adapter, "_run", _fake_run)

    with pytest.raises(GitError, match="Could not determine the default branch"):
        git_adapter.default_branch(repo, "origin")


def _init_local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git_adapter._run(["init", "-b", "main"], cwd=repo)
    git_adapter._run(["config", "user.email", "t@example.com"], cwd=repo)
    git_adapter._run(["config", "user.name", "t"], cwd=repo)
    (repo / "f").write_text("x", encoding="utf-8")
    git_adapter._run(["add", "f"], cwd=repo)
    git_adapter._run(["commit", "-m", "init"], cwd=repo)
    return repo


def test_branch_exists_and_find_worktree_for_branch(tmp_path: Path) -> None:
    repo = _init_local_repo(tmp_path)
    assert git_adapter.branch_exists(repo, "main") is True
    assert git_adapter.branch_exists(repo, "missing") is False

    git_adapter._run(["checkout", "-b", "feature/x"], cwd=repo)
    found = git_adapter.find_worktree_for_branch(repo, "feature/x")
    assert found is not None
    assert found.resolve() == repo.resolve()


def test_add_worktree_existing_branch_and_detach_checkout(tmp_path: Path) -> None:
    repo = _init_local_repo(tmp_path)
    git_adapter._run(["checkout", "-b", "feature/y"], cwd=repo)
    git_adapter._run(["checkout", "main"], cwd=repo)

    wt = tmp_path / "wt"
    git_adapter.add_worktree_existing_branch(repo, wt, "feature/y")
    assert git_adapter.current_branch(wt) == "feature/y"

    git_adapter.checkout(wt, "--detach")
    assert git_adapter.current_branch(wt) is None


def test_stash_push_and_pop(tmp_path: Path) -> None:
    repo = _init_local_repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    created = git_adapter.stash_push(repo, include_untracked=True, message="test stash")
    assert created is True
    assert git_adapter.is_clean(repo) is True
    git_adapter.stash_pop(repo)
    assert (repo / "dirty.txt").read_text(encoding="utf-8") == "dirty"


def test_is_worktree_root_distinguishes_nested_paths(tmp_path: Path) -> None:
    repo = _init_local_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    assert git_adapter.is_worktree_root(repo) is True
    assert git_adapter.is_worktree_root(nested) is False
    assert git_adapter.is_git_repo(nested) is True
