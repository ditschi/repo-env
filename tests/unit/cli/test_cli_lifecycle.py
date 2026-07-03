"""Tests for rm/rename/sync/status/prune/import/pr/completion commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.domain.models import Environment, RepoEntry, RepoStatus


def _register(repoenv_home: Path, name: str = "demo", *, repos: int = 1) -> Environment:
    env_path = repoenv_home / "envs" / name
    src = repoenv_home / "src"
    entries = []
    for i in range(repos):
        wt = env_path / f"r{i}"
        wt.mkdir(parents=True)
        entries.append(
            RepoEntry(
                repo=f"r{i}",
                worktree_path=wt,
                remote="origin",
                base="main",
                branch="feature",
                status=RepoStatus.OK,
            )
        )
    env = Environment(name=name, path=env_path, source=src, repos=entries)
    registry = state_store.load_registry()
    registry.add(env)
    state_store.save_registry(registry)
    return env


def test_rm_registry_only(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.services.lifecycle_service.check_dirty", lambda env: [])
    runner = CliRunner()
    result = runner.invoke(app, ["rm", "demo"])
    assert result.exit_code == 0
    assert "demo" not in state_store.load_registry()


def test_rm_dry_run_keeps_registry(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.services.lifecycle_service.check_dirty", lambda env: [])
    runner = CliRunner()
    result = runner.invoke(app, ["rm", "demo", "--dry-run"])
    assert result.exit_code == 0
    assert "demo" in state_store.load_registry()


def test_rm_refuses_dirty(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.services.lifecycle_service.check_dirty", lambda env: ["r0"])
    runner = CliRunner()
    result = runner.invoke(app, ["rm", "demo"])
    assert result.exit_code != 0
    assert "demo" in state_store.load_registry()


def test_rename(repoenv_home: Path) -> None:
    _register(repoenv_home)
    runner = CliRunner()
    result = runner.invoke(app, ["rename", "demo", "prod"])
    assert result.exit_code == 0
    registry = state_store.load_registry()
    assert "demo" not in registry
    assert "prod" in registry


def test_rename_conflict(repoenv_home: Path) -> None:
    _register(repoenv_home, "a")
    _register(repoenv_home, "b")
    runner = CliRunner()
    result = runner.invoke(app, ["rename", "a", "b"])
    assert result.exit_code != 0


def test_sync_reports_failures(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home, repos=2)
    monkeypatch.setattr("repoenv.services.lifecycle_service.sync_environment", lambda env: ["r1"])
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "demo"])
    assert result.exit_code != 0


def test_status_json(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.adapters.git_adapter.is_clean", lambda path: True)
    runner = CliRunner()
    result = runner.invoke(app, ["status", "demo", "--json"])
    assert result.exit_code == 0
    assert '"environment": "demo"' in result.stdout


def test_prune(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.services.lifecycle_service.prune_environment", lambda env: 1)
    runner = CliRunner()
    result = runner.invoke(app, ["prune", "demo"])
    assert result.exit_code == 0


def test_import_no_repos(repoenv_home: Path) -> None:
    directory = repoenv_home / "ondisk"
    directory.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["import", str(directory)])
    assert result.exit_code != 0


def test_completion_unsupported_shell(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["completion", "powershell"])
    assert result.exit_code != 0


def test_pr_requires_gh(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: False)
    runner = CliRunner()
    result = runner.invoke(app, ["pr", "demo", "--title", "x"])
    assert result.exit_code != 0


def test_pr_dry_run(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)
    runner = CliRunner()
    result = runner.invoke(app, ["pr", "demo", "--title", "Fix {repo}", "--dry-run"])
    assert result.exit_code == 0


def test_pr_bad_if_exists(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(repoenv_home)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)
    runner = CliRunner()
    result = runner.invoke(app, ["pr", "demo", "--title", "x", "--if-exists", "bogus"])
    assert result.exit_code != 0
