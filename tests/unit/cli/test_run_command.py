"""Regression tests for ``renv run``'s ``[ENV] -- COMMAND`` argument splitting.

Click distributes ``ENV`` (nargs=1, optional) and ``COMMAND`` (nargs=-1) by
count, not by where ``--`` appears, so omitting ``ENV`` used to make the first
command word (e.g. ``git``) get swallowed as the environment name. See
``repoenv.cli.passthrough`` for the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.cli.commands import run as run_module
from repoenv.domain.models import Environment, RepoEntry, RunResult


def _register(env: Environment) -> None:
    registry = state_store.load_registry()
    registry.add(env)
    registry.set_active(env.name)
    state_store.save_registry(registry)


def _fake_results(env: Environment) -> list[RunResult]:
    return [
        RunResult(repo=entry.repo, worktree_path=entry.worktree_path, exit_code=0, duration_s=0.0)
        for entry in env.repos
    ]


def test_run_without_env_uses_active_env_not_first_command_word(
    repoenv_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Environment(name="test", path=repoenv_home / "test", source=repoenv_home / "src")
    env.repos.append(RepoEntry(repo="repo-a", worktree_path=env.path / "repo-a", base="main", branch="main"))
    _register(env)

    captured: dict[str, object] = {}

    def _fake_run_across(environment, command, **kwargs):
        captured["environment"] = environment.name
        captured["command"] = command
        return _fake_results(environment)

    monkeypatch.setattr(run_module.runner, "run_across", _fake_run_across)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--", "git", "status"])

    assert result.exit_code == 0, result.output
    assert captured["environment"] == "test"
    assert captured["command"] == ["git", "status"]


def test_run_with_explicit_env_still_works(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = Environment(name="web", path=repoenv_home / "web", source=repoenv_home / "src")
    env.repos.append(RepoEntry(repo="repo-a", worktree_path=env.path / "repo-a", base="main", branch="main"))
    _register(env)

    captured: dict[str, object] = {}

    def _fake_run_across(environment, command, **kwargs):
        captured["environment"] = environment.name
        captured["command"] = command
        return _fake_results(environment)

    monkeypatch.setattr(run_module.runner, "run_across", _fake_run_across)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "web", "--", "git", "status"])

    assert result.exit_code == 0, result.output
    assert captured["environment"] == "web"
    assert captured["command"] == ["git", "status"]


def test_run_options_before_dashdash_are_still_parsed(
    repoenv_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Environment(name="test", path=repoenv_home / "test", source=repoenv_home / "src")
    env.repos.append(RepoEntry(repo="repo-a", worktree_path=env.path / "repo-a", base="main", branch="main"))
    _register(env)

    captured: dict[str, object] = {}

    def _fake_run_across(environment, command, *, jobs, **kwargs):
        captured["jobs"] = jobs
        captured["command"] = command
        return _fake_results(environment)

    monkeypatch.setattr(run_module.runner, "run_across", _fake_run_across)

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--jobs", "3", "--", "echo", "-x", "hi"])

    assert result.exit_code == 0, result.output
    assert captured["jobs"] == 3
    # Everything after '--' (including '-x') is passed through verbatim.
    assert captured["command"] == ["echo", "-x", "hi"]


def test_run_without_dashdash_reports_no_command_given(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run", "test"])

    assert result.exit_code != 0
    assert "No command given" in str(result.exception)
