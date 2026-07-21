"""Unit tests for git_adapter.is_linked_worktree."""

from __future__ import annotations

from pathlib import Path

from repoenv.adapters.git_adapter import is_linked_worktree


def test_returns_false_when_path_does_not_exist(tmp_path: Path) -> None:
    assert is_linked_worktree(tmp_path / "no-such-dir") is False


def test_returns_false_when_dot_git_is_directory(tmp_path: Path) -> None:
    repo = tmp_path / "main-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    assert is_linked_worktree(repo) is False


def test_returns_true_when_dot_git_is_gitdir_file(tmp_path: Path) -> None:
    wt = tmp_path / "linked"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /some/main/.git/worktrees/linked\n", encoding="utf-8")
    assert is_linked_worktree(wt) is True


def test_returns_false_when_dot_git_file_does_not_start_with_gitdir(tmp_path: Path) -> None:
    wt = tmp_path / "other"
    wt.mkdir()
    (wt / ".git").write_text("# not a gitdir pointer\n", encoding="utf-8")
    assert is_linked_worktree(wt) is False


def test_returns_false_when_no_dot_git(tmp_path: Path) -> None:
    d = tmp_path / "plain-dir"
    d.mkdir()
    assert is_linked_worktree(d) is False
