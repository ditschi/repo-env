from __future__ import annotations

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_add_and_merge_commands(repo_factory: RepoFactory, repoenv_home, source_dir, worktrees_dir) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    repo_factory.make_bare_and_clone("gamma")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "a", "--include", "alpha"]).exit_code == 0
    assert runner.invoke(app, ["new", "b", "--include", "beta"]).exit_code == 0

    add_result = runner.invoke(app, ["add", "a", "--include", "gamma"])
    assert add_result.exit_code == 0
    assert (worktrees_dir / "a" / "gamma" / ".git").exists()

    merge_result = runner.invoke(app, ["merge", "ab", "a", "b", "--op", "union"])
    assert merge_result.exit_code == 0
    assert (worktrees_dir / "ab" / "alpha" / ".git").exists()
    assert (worktrees_dir / "ab" / "beta" / ".git").exists()
    assert (worktrees_dir / "ab" / "gamma" / ".git").exists()
