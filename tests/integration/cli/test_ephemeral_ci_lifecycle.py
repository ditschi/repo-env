"""End-to-end "throwaway CI environment" lifecycle.

``--preserve`` (skip fetch/update, use source as-is) and ``--json`` output on
``run``/``status`` look purpose-built for a non-interactive pipeline: check
out repos once, create an ephemeral env from them without touching the
network, run a build/test command and parse machine-readable results, then
tear the whole thing down. Nothing previously exercised that flow end-to-end.
"""

from __future__ import annotations

import json

from tests.integration.support.gitfixtures import worktree_listing
from tests.integration.support.renv_helpers import Renv


def test_preserve_create_json_run_then_delete_files_leaves_no_trace(renv: Renv) -> None:
    clones = renv.setup("alpha", "beta")
    ci = renv.worktrees / "ci"

    # --preserve: no network/fetch touches the checked-out source repos.
    renv.ok("create", "ci", "--preserve", "--include", "alpha,beta")
    assert (ci / "alpha").exists()
    assert (ci / "beta").exists()

    results = json.loads(renv.ok("run", "ci", "--json", "--", "git", "rev-parse", "HEAD").stdout)
    assert {r["repo"] for r in results} == {"alpha", "beta"}
    assert all(r["exit_code"] == 0 for r in results)

    health = renv.status("ci")
    assert all(r["present"] and r["status"] == "ok" for r in health.values())

    renv.ok("rm", "ci")
    assert not ci.exists()
    assert "ci" not in renv.invoke("ls").output

    # Cleanup was via `git worktree remove`, not a raw rm -rf: the source
    # repos' own worktree metadata is clean, so recreating doesn't hit stale
    # registration errors (the original "orphaned worktree" failure mode).
    for repo_path in clones:
        assert str(ci) not in worktree_listing(repo_path)

    renv.ok("create", "ci", "--preserve", "--include", "alpha,beta")
