"""Verify the standard ``.testenv/`` directory layout."""

from __future__ import annotations

from pathlib import Path

from tests.integration.support.gitfixtures import RepoFactory


def test_testenv_has_source_and_worktrees(
    testenv_root: Path,
    repo_factory: RepoFactory,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    assert source_dir == testenv_root / "source"
    assert worktrees_dir == testenv_root / "worktrees"
    assert repo_factory.remotes == testenv_root / "remotes"
    assert source_dir.is_dir()
    assert worktrees_dir.is_dir()

    repo_factory.make_bare_and_clone("sample")
    assert (source_dir / "sample" / ".git").exists()
    assert list(worktrees_dir.iterdir()) == []
