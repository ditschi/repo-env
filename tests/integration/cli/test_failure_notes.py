"""Per-repo failure reasons must be visible without passing ``--json``.

``RepoEntry.note`` already captures *why* a worktree failed (e.g. "could not
determine the default branch"), but ``create``/``add``'s human-readable error
summary and ``renv status``'s default output used to only say a repo
"failed" / was "MISSING" with no reason, so a real failure looked identical
to nothing having happened at all.
"""

from __future__ import annotations

from tests.integration.support.gitfixtures import run_git
from tests.integration.support.renv_helpers import Renv


def test_create_failure_reason_shown_without_json(renv: Renv) -> None:
    (broken,) = renv.setup("broken")
    run_git(["remote", "remove", "origin"], cwd=broken)

    result = renv.invoke("create", "env", "--include", "broken")

    assert result.exit_code != 0
    assert result.exception is not None
    assert "default branch" in getattr(result.exception, "message", str(result.exception))

    assert "default branch" in renv.invoke("status", "env").output
