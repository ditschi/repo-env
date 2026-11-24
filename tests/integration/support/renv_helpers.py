"""Helpers for driving the renv CLI in integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typer.testing import CliRunner, Result

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, checkout_branch_in_source


@dataclass
class Renv:
    """The renv CLI bound to one test's ``.testenv/<test>/`` layout."""

    repos: RepoFactory
    runner: CliRunner = field(default_factory=CliRunner)

    @property
    def source(self) -> Path:
        return self.repos.source

    @property
    def worktrees(self) -> Path:
        return self.repos.worktrees

    def setup(self, *names: str) -> list[Path]:
        """Create a source clone per name, then run ``renv init`` on the standard layout."""
        clones = [self.repos.make_bare_and_clone(name) for name in names]
        self.ok("init", "-y", "--source", str(self.source), "--dest", str(self.worktrees))
        return clones

    def invoke(self, *args: str) -> Result:
        return self.runner.invoke(app, list(args))

    def ok(self, *args: str) -> Result:
        """Invoke ``renv`` and assert it succeeded."""
        result = self.invoke(*args)
        assert result.exit_code == 0, result.output
        return result

    def status(self, env: str) -> dict[str, dict[str, Any]]:
        """``renv status <env> --json``, keyed by repo name."""
        return repos_by_name(self.ok("status", env, "--json"))


def assert_failed_with(result: Result, message: str) -> None:
    """Assert the command failed with an exception whose text contains ``message``."""
    assert result.exit_code != 0
    assert isinstance(result.exception, Exception)
    assert message in str(result.exception)


def repos_by_name(status_result: Result) -> dict[str, dict[str, Any]]:
    """The ``repos`` of a ``renv status --json`` result, keyed by repo name."""
    return {item["repo"]: item for item in json.loads(status_result.stdout)["repos"]}


def env_meta(env_dir: Path) -> dict[str, Any]:
    """Parse the ``.repoenv.json`` marker of an environment directory."""
    return json.loads((env_dir / ".repoenv.json").read_text(encoding="utf-8"))


def create_batch_with_branch_conflict(renv: Renv) -> Result:
    """Create env ``batch`` on ``feature/shared`` while ``beta``'s source clone has that branch checked out.

    With ``--on-branch-conflict fail`` only ``alpha`` gets a worktree, so the create partially fails.
    """
    _, beta = renv.setup("alpha", "beta")
    checkout_branch_in_source(beta, "feature/shared")
    return renv.invoke("create", "batch", "--branch", "feature/shared", "--on-branch-conflict", "fail")
