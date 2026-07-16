"""CLI tests for ``renv clone``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from repoenv.cli.commands import clone as clone_module
from repoenv.services.clone_service import Action, ResolvedRepo


def test_clone_dry_run_with_fully_qualified_url(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = repoenv_home / "src"
    source.mkdir()
    monkeypatch.setattr(
        clone_module.config_store,
        "load_config",
        lambda: clone_module.config_store.UserConfig(source=source),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["clone", "-u", "https://github.com/owner/repo", "--dry-run", "--protocol", "ssh"],
    )

    assert result.exit_code == 0, result.output
    assert "github.com/owner/repo" in result.stderr
    assert "Dry run" in result.stderr
    assert not (source / "github.com" / "owner" / "repo").exists()


def test_clone_requires_url(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = repoenv_home / "src"
    source.mkdir()
    monkeypatch.setattr(
        clone_module.config_store,
        "load_config",
        lambda: clone_module.config_store.UserConfig(source=source),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["clone", "--dry-run"])

    assert result.exit_code != 0
    assert "At least one --url is required" in str(result.exception)


def test_clone_rejects_invalid_include_pattern(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = repoenv_home / "src"
    source.mkdir()
    monkeypatch.setattr(
        clone_module.config_store,
        "load_config",
        lambda: clone_module.config_store.UserConfig(source=source),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["clone", "-u", "https://github.com", "-i", "no-slash", "--dry-run"],
    )

    assert result.exit_code != 0
    assert "Invalid owner/repo pattern" in str(result.exception)


def test_clone_executes_plan(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = repoenv_home / "src"
    source.mkdir()
    monkeypatch.setattr(
        clone_module.config_store,
        "load_config",
        lambda: clone_module.config_store.UserConfig(source=source),
    )

    repo = ResolvedRepo(
        host="github.com",
        owner="owner",
        repo="repo",
        clone_url="git@github.com:owner/repo.git",
    )

    def _fake_resolve(**kwargs):
        return clone_module.clone_service.ResolveResult(repos=[repo], warnings=[])

    captured: dict[str, object] = {}

    def _fake_execute(repos, *, source, update, reset_default, force, jobs):
        captured["source"] = source
        captured["repos"] = repos
        return [clone_module.clone_service.CloneOutcome(repo, Action.CLONED)]

    monkeypatch.setattr(clone_module.clone_service, "resolve_clone_targets", _fake_resolve)
    monkeypatch.setattr(clone_module.clone_service, "execute_clone_plan", _fake_execute)

    runner = CliRunner()
    result = runner.invoke(app, ["clone", "-u", "https://github.com/owner/repo"])

    assert result.exit_code == 0, result.output
    assert captured["source"] == source
    assert captured["repos"] == [repo]
    assert "cloned" in result.stderr
