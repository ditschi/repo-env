"""CLI tests for ``renv clone``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from repoenv.cli.commands import clone as clone_module
from repoenv.services.clone_service import Action, ResolvedRepo


@pytest.fixture
def source(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configured source directory (``renv init`` equivalent)."""
    source = repoenv_home / "src"
    source.mkdir()
    monkeypatch.setattr(
        clone_module.config_store,
        "load_config",
        lambda: clone_module.config_store.UserConfig(source=source),
    )
    return source


def test_clone_dry_run_with_fully_qualified_url(source: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["clone", "-u", "https://github.com/owner/repo", "--dry-run", "--protocol", "ssh"],
    )

    assert result.exit_code == 0, result.output
    assert [text for text in ("github.com/owner/repo", "Dry run") if text not in result.stderr] == []
    assert not (source / "github.com" / "owner" / "repo").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["clone", "--dry-run"], "At least one --url is required"),
        (["clone", "-u", "https://github.com", "-i", "no-slash", "--dry-run"], "Invalid owner/repo pattern"),
    ],
)
def test_clone_rejects_invalid_arguments(source: Path, args: list[str], message: str) -> None:
    runner = CliRunner()
    result = runner.invoke(app, args)

    assert result.exit_code != 0
    assert message in str(result.exception)


def test_clone_executes_plan(source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = ResolvedRepo(
        host="github.com",
        owner="owner",
        repo="repo",
        clone_url="git@github.com:owner/repo.git",
    )

    def _fake_resolve(query, **kwargs):
        return clone_module.clone_service.ResolveResult(repos=[repo], warnings=[])

    captured: dict[str, object] = {}

    def _fake_execute(repos, *, source, sync, jobs):
        captured.update(source=source, repos=repos)
        return [clone_module.clone_service.CloneOutcome(repo, Action.CLONED)]

    monkeypatch.setattr(clone_module.clone_service, "resolve_clone_targets", _fake_resolve)
    monkeypatch.setattr(clone_module.clone_service, "execute_clone_plan", _fake_execute)

    runner = CliRunner()
    result = runner.invoke(app, ["clone", "-u", "https://github.com/owner/repo"])

    assert result.exit_code == 0, result.output
    assert captured == {"source": source, "repos": [repo]}
    assert "cloned" in result.stderr
