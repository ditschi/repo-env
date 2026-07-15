"""Integration tests for ``renv repair``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.domain.models import RepoStatus
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def _assert_partial_failure(result) -> None:
    assert result.exit_code != 0
    assert isinstance(result.exception, Exception)
    assert "Failed to repair" in str(result.exception)


def test_repair_restores_deleted_worktree(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "feat", "--branch", "feature/repair"]).exit_code == 0

    shutil.rmtree(worktrees_dir / "feat" / "alpha")
    repair = runner.invoke(app, ["repair", "feat"])
    assert repair.exit_code == 0, repair.output
    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()
    assert RepoFactory.current_branch(worktrees_dir / "feat" / "alpha") == "feature/repair"


def test_repair_partial_failure_retry(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    ok_clone = repo_factory.make_bare_and_clone("alpha")
    fail_clone = repo_factory.make_bare_and_clone("beta")
    _ = ok_clone
    RepoFactory.checkout_branch_in_source(fail_clone, "feature/shared")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    create = runner.invoke(
        app,
        ["create", "batch", "--branch", "feature/shared", "--on-branch-conflict", "fail"],
    )
    assert create.exit_code != 0
    assert (worktrees_dir / "batch" / "alpha" / ".git").exists()
    assert not (worktrees_dir / "batch" / "beta" / ".git").exists()

    repair = runner.invoke(app, ["repair", "batch", "--on-branch-conflict", "detach"])
    assert repair.exit_code == 0, repair.output
    assert (worktrees_dir / "batch" / "beta" / ".git").exists()


def test_repair_orphaned_worktree_metadata(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    testenv_root: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    clone = repo_factory.make_bare_and_clone("alpha")
    orphan_path = worktrees_dir / "feat" / "alpha"
    RepoFactory.simulate_orphaned_worktree(clone, orphan_path, branch="feature/orphan")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "feat", "--branch", "feature/orphan", "--include", "alpha"]).exit_code
        == 0
    )

    shutil.rmtree(orphan_path)
    repair = runner.invoke(app, ["repair", "feat"])
    assert repair.exit_code == 0, repair.output
    assert (orphan_path / ".git").exists()


def test_repair_stray_directory_clear_error(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "feat", "--branch", "feature/x", "--include", "alpha"]).exit_code == 0
    )

    shutil.rmtree(worktrees_dir / "feat" / "alpha")
    RepoFactory.leave_stray_directory(worktrees_dir / "feat" / "alpha")

    repair = runner.invoke(app, ["repair", "feat"])
    _assert_partial_failure(repair)


def test_repair_dry_run_lists_candidates(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "feat", "--include", "alpha"]).exit_code == 0

    shutil.rmtree(worktrees_dir / "feat" / "alpha")
    dry = runner.invoke(app, ["repair", "feat", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "alpha" in dry.output
    assert not (worktrees_dir / "feat" / "alpha").exists()


def test_create_reconciles_deleted_env_directory(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "ado", "--include", "alpha"]).exit_code == 0

    shutil.rmtree(worktrees_dir / "ado")
    recreate = runner.invoke(app, ["create", "ado", "--include", "alpha"])
    assert recreate.exit_code == 0, recreate.output
    assert "Reconciled" in recreate.output
    assert (worktrees_dir / "ado" / "alpha" / ".git").exists()


def test_repair_noop_when_all_worktrees_healthy(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "feat", "--include", "alpha"]).exit_code == 0

    repair = runner.invoke(app, ["repair", "feat"])
    assert repair.exit_code == 0, repair.output
    assert "No worktrees need repair" in repair.output


def test_repair_include_repairs_subset_only(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "feat", "--branch", "feature/subset"]).exit_code == 0

    shutil.rmtree(worktrees_dir / "feat" / "alpha")
    shutil.rmtree(worktrees_dir / "feat" / "beta")

    repair = runner.invoke(app, ["repair", "feat", "--include", "alpha"])
    assert repair.exit_code == 0, repair.output
    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()
    assert not (worktrees_dir / "feat" / "beta").exists()


def test_repair_status_workflow_shows_missing_then_ok(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(app, ["create", "feat", "--branch", "feature/status", "--include", "alpha"]).exit_code
        == 0
    )

    shutil.rmtree(worktrees_dir / "feat" / "alpha")

    before = runner.invoke(app, ["status", "feat", "--json"])
    assert before.exit_code == 0, before.output
    payload_before = json.loads(before.stdout)
    by_repo = {item["repo"]: item for item in payload_before["repos"]}
    assert by_repo["alpha"]["present"] is False
    assert "repair" in before.output.lower()

    repair = runner.invoke(app, ["repair", "feat"])
    assert repair.exit_code == 0, repair.output

    after = runner.invoke(app, ["status", "feat", "--json"])
    assert after.exit_code == 0, after.output
    payload_after = json.loads(after.stdout)
    by_repo_after = {item["repo"]: item for item in payload_after["repos"]}
    assert by_repo_after["alpha"]["present"] is True
    assert by_repo_after["alpha"]["status"] == RepoStatus.OK.value


def test_repair_resolves_environment_from_cwd(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "feat", "--include", "alpha"]).exit_code == 0

    shutil.rmtree(worktrees_dir / "feat" / "alpha")
    monkeypatch.chdir(worktrees_dir / "feat")

    repair = runner.invoke(app, ["repair"])
    assert repair.exit_code == 0, repair.output
    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()


def test_repair_after_partial_failure_updates_registry_status(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    ok_clone = repo_factory.make_bare_and_clone("alpha")
    fail_clone = repo_factory.make_bare_and_clone("beta")
    _ = ok_clone
    RepoFactory.checkout_branch_in_source(fail_clone, "feature/shared")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    create = runner.invoke(
        app,
        ["create", "batch", "--branch", "feature/shared", "--on-branch-conflict", "fail"],
    )
    assert create.exit_code != 0

    repair = runner.invoke(app, ["repair", "batch", "--on-branch-conflict", "detach"])
    assert repair.exit_code == 0, repair.output

    registry = state_store.load_registry()
    batch = registry.get("batch")
    assert batch is not None
    by_repo = {entry.repo: entry for entry in batch.repos}
    assert by_repo["alpha"].status == RepoStatus.OK
    assert by_repo["beta"].status == RepoStatus.OK
    assert (worktrees_dir / "batch" / "beta" / ".git").exists()
