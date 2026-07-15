"""Integration tests for --on-branch-conflict worktree handling."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.domain.models import RepoStatus
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def _assert_partial_failure(result) -> None:
    assert result.exit_code != 0
    assert isinstance(result.exception, Exception)
    assert "Some repositories failed" in str(result.exception)


def _load_env_meta(worktrees: Path, name: str) -> dict:
    return json.loads((worktrees / name / ".repoenv.json").read_text(encoding="utf-8"))


def test_create_no_conflict_new_branch(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "feat", "--branch", "feature/new"])
    assert result.exit_code == 0, result.output
    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()
    assert RepoFactory.current_branch(worktrees_dir / "feat" / "alpha") == "feature/new"


def test_create_attaches_existing_unused_branch(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    RepoFactory.create_local_branch(clone, "feature/exists", checkout=False)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "feat", "--branch", "feature/exists", "--include", "alpha"])
    assert result.exit_code == 0, result.output
    wt = worktrees_dir / "feat" / "alpha"
    assert RepoFactory.current_branch(wt) == "feature/exists"
    assert RepoFactory.is_detached(wt) is False


def test_create_branch_checked_out_in_source_detach_default(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    RepoFactory.checkout_branch_in_source(clone, "feature/in-source")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        ["create", "feat", "--branch", "feature/in-source", "--include", "alpha"],
    )
    assert result.exit_code == 0, result.output
    wt = worktrees_dir / "feat" / "alpha"
    assert wt.exists()
    assert RepoFactory.is_detached(wt) is True

    meta = _load_env_meta(worktrees_dir, "feat")
    note = meta["environment"]["repos"][0]["note"]
    assert note is not None
    assert "detached worktree" in note


def test_create_branch_checked_out_in_source_fail(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    RepoFactory.checkout_branch_in_source(clone, "feature/in-source")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        [
            "create",
            "feat",
            "--branch",
            "feature/in-source",
            "--include",
            "alpha",
            "--on-branch-conflict",
            "fail",
        ],
    )
    _assert_partial_failure(result)


def test_create_branch_checked_out_in_source_move_with_dirty_file(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    RepoFactory.checkout_branch_in_source(clone, "feature/move")
    RepoFactory.write_file(clone, "local-only.txt", "keep-me")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        [
            "create",
            "feat",
            "--branch",
            "feature/move",
            "--include",
            "alpha",
            "--on-branch-conflict",
            "move",
        ],
    )
    assert result.exit_code == 0, result.output
    wt = worktrees_dir / "feat" / "alpha"
    assert RepoFactory.current_branch(wt) == "feature/move"
    assert (wt / "local-only.txt").read_text(encoding="utf-8") == "keep-me"
    assert RepoFactory.current_branch(clone) == "main"


def test_create_branch_checked_out_in_foreign_worktree_move(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    testenv_root: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    foreign = testenv_root / "foreign" / "alpha"
    RepoFactory.create_foreign_worktree(clone, foreign, "feature/foreign")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        [
            "create",
            "feat",
            "--branch",
            "feature/foreign",
            "--include",
            "alpha",
            "--on-branch-conflict",
            "move",
        ],
    )
    assert result.exit_code == 0, result.output
    wt = worktrees_dir / "feat" / "alpha"
    assert RepoFactory.current_branch(wt) == "feature/foreign"
    assert RepoFactory.is_detached(foreign) is True


def test_create_orphaned_worktree_auto_heals(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    testenv_root: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    orphan_path = testenv_root / "orphan" / "alpha"
    RepoFactory.simulate_orphaned_worktree(clone, orphan_path, branch="feature/orphan")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        ["create", "feat", "--branch", "feature/orphan", "--include", "alpha"],
    )
    assert result.exit_code == 0, result.output
    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()


def test_create_stray_directory_clear_error(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    RepoFactory.leave_stray_directory(worktrees_dir / "feat" / "alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        ["create", "feat", "--branch", "feature/x", "--include", "alpha"],
    )
    _assert_partial_failure(result)


def test_add_branch_conflict_detach(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    RepoFactory.checkout_branch_in_source(clone, "feature/add")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "env", "--include", "beta"]).exit_code == 0

    result = runner.invoke(
        app,
        ["add", "env", "--include", "alpha", "--branch", "feature/add"],
    )
    assert result.exit_code == 0, result.output
    wt = worktrees_dir / "env" / "alpha"
    assert wt.exists()
    assert RepoFactory.is_detached(wt) is True


def test_partial_failure_saves_env_and_status_shows_note(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    ok_clone = repo_factory.make_bare_and_clone("alpha")
    fail_clone = repo_factory.make_bare_and_clone("beta")
    _ = ok_clone
    RepoFactory.checkout_branch_in_source(fail_clone, "feature/shared")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(
        app,
        [
            "create",
            "batch",
            "--branch",
            "feature/shared",
            "--on-branch-conflict",
            "fail",
        ],
    )
    _assert_partial_failure(result)
    assert (worktrees_dir / "batch" / "alpha" / ".git").exists()
    assert not (worktrees_dir / "batch" / "beta" / ".git").exists()

    registry = state_store.load_registry()
    assert "batch" in registry

    status = runner.invoke(app, ["status", "batch", "--json"])
    assert status.exit_code == 0
    payload = json.loads(status.stdout)
    by_repo = {item["repo"]: item for item in payload["repos"]}
    assert by_repo["alpha"]["present"] is True
    assert by_repo["beta"]["status"] == RepoStatus.FAILED.value
    assert by_repo["beta"]["note"] is not None
    assert "failed" in by_repo["beta"]["note"].lower()
