"""``renv import`` must record the real branch name, not a raw commit SHA.

Before this, ``import_command`` used ``git rev-parse HEAD`` (a commit SHA) as
the value for ``RepoEntry.branch``, so adopting a hand-made worktree checked
out on a real branch like ``feature/x`` silently mislabeled it as a 40-char
hash -- which would then leak into things like ``renv pr``'s ``{branch}``
template.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git


def test_import_records_real_branch_name_not_sha(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")

    manual_env_dir = worktrees_dir / "hand-made"
    manual_env_dir.mkdir(parents=True)
    worktree_path = manual_env_dir / "alpha"
    run_git(["worktree", "add", "-b", "feature/manual", str(worktree_path)], cwd=clone)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["import", str(manual_env_dir), "--name", "adopted", "--source", str(source_dir)],
    )
    assert result.exit_code == 0, result.output

    registry = state_store.load_registry()
    env = registry.get("adopted")
    assert env is not None
    entry = next(e for e in env.repos if e.repo == "alpha")
    assert entry.branch == "feature/manual"
    assert len(entry.source_sha or "") == 40


def test_import_detached_worktree_labels_it_clearly(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")

    manual_env_dir = worktrees_dir / "hand-made"
    manual_env_dir.mkdir(parents=True)
    worktree_path = manual_env_dir / "alpha"
    run_git(["worktree", "add", "--detach", str(worktree_path)], cwd=clone)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["import", str(manual_env_dir), "--name", "adopted", "--source", str(source_dir)],
    )
    assert result.exit_code == 0, result.output

    registry = state_store.load_registry()
    env = registry.get("adopted")
    assert env is not None
    entry = next(e for e in env.repos if e.repo == "alpha")
    assert entry.branch.startswith("detached@")
    assert entry.source_sha is not None
    assert entry.branch != entry.source_sha
