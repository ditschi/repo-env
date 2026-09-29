"""End-to-end "throwaway CI environment" lifecycle.

``--preserve`` (skip fetch/update, use source as-is) and ``--json`` output on
``run``/``status`` look purpose-built for a non-interactive pipeline: check
out repos once, create an ephemeral env from them without touching the
network, run a build/test command and parse machine-readable results, then
tear the whole thing down. Nothing previously exercised that flow end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv


def test_preserve_create_json_run_then_delete_files_leaves_no_trace(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    alpha = repo_factory.make_bare_and_clone("alpha")
    beta = repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    # --preserve: no network/fetch touches the checked-out source repos.
    create = runner.invoke(app, ["create", "ci", "--preserve", "--include", "alpha,beta"])
    assert create.exit_code == 0, create.output
    assert (worktrees_dir / "ci" / "alpha").exists()
    assert (worktrees_dir / "ci" / "beta").exists()

    run = runner.invoke(app, ["run", "ci", "--json", "--", "git", "rev-parse", "HEAD"])
    assert run.exit_code == 0, run.output
    results = json.loads(run.stdout)
    assert {r["repo"] for r in results} == {"alpha", "beta"}
    assert all(r["exit_code"] == 0 for r in results)

    status = runner.invoke(app, ["status", "ci", "--json"])
    assert status.exit_code == 0, status.output
    health = json.loads(status.stdout)
    assert all(r["present"] and r["status"] == "ok" for r in health["repos"])

    rm = runner.invoke(app, ["rm", "ci", "--delete-files"])
    assert rm.exit_code == 0, rm.output
    assert not (worktrees_dir / "ci").exists()

    ls_after = runner.invoke(app, ["ls"])
    assert "ci" not in ls_after.output

    # Cleanup was via `git worktree remove`, not a raw rm -rf: the source
    # repos' own worktree metadata is clean, so recreating doesn't hit stale
    # registration errors (the original "orphaned worktree" failure mode).
    for repo_path in (alpha, beta):
        listing = run_git(["worktree", "list", "--porcelain"], cwd=repo_path).stdout
        assert str(worktrees_dir / "ci") not in listing

    recreate = runner.invoke(app, ["create", "ci", "--preserve", "--include", "alpha,beta"])
    assert recreate.exit_code == 0, recreate.output
