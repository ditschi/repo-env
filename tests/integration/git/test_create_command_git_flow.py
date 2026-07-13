from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_create_creates_worktrees(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir, worktrees_dir
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "feat", "--branch", "feature/x"])
    assert result.exit_code == 0

    # Keep compatibility alias covered.
    alias_result = runner.invoke(app, ["new", "compat", "--dry-run"])
    assert alias_result.exit_code == 0

    assert (worktrees_dir / "feat" / "alpha" / ".git").exists()
    assert (worktrees_dir / "feat" / "beta" / ".git").exists()
    meta = worktrees_dir / "feat" / ".repoenv.json"
    assert meta.exists()
    meta_data = json.loads(meta.read_text(encoding="utf-8"))
    assert "environment" in meta_data
    assert meta_data["environment"]["name"] == "feat"
    assert meta_data["marker"]["kind"] == "repo-env-marker"
    assert meta_data["marker"]["environment_name"] == "feat"
    assert meta_data["marker"]["command"]["name"] == "create"
    assert "renv create feat" in meta_data["marker"]["command"]["recreate"]
