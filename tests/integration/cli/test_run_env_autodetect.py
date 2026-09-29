"""Regression tests for ``renv run`` when the ``[ENV]`` argument is omitted.

``renv run -- CMD...`` (cwd/active-environment autodetect) is the form shown
in the README quickstart. Click discards the literal ``--`` separator before
argument values reach the command callback, so a naive ``env`` + ``command``
argument pair greedily assigns the first token *after* ``--`` to ``env`` when
no env was actually given.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_run_without_env_autodetects_from_cwd(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    monkeypatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha,beta"]).exit_code == 0

    monkeypatch.chdir(worktrees_dir / "web")
    result = runner.invoke(app, ["run", "--", "git", "status"])
    assert result.exit_code == 0, result.output
    assert "No environment named or aliased" not in result.output
    assert "alpha" in result.output
    assert "beta" in result.output


def test_run_without_env_passes_flag_like_command_tokens(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    monkeypatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha"]).exit_code == 0

    monkeypatch.chdir(worktrees_dir / "web")
    result = runner.invoke(app, ["run", "--", "git", "branch", "--show-current"])
    assert result.exit_code == 0, result.output
    assert "No environment named or aliased" not in result.output


def test_run_with_explicit_env_before_dashdash_still_works(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha"]).exit_code == 0

    result = runner.invoke(app, ["run", "web", "--", "git", "status"])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
