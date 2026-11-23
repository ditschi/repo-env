from __future__ import annotations

from tests.integration.support.renv_helpers import Renv


def test_add_and_merge_commands(renv: Renv) -> None:
    renv.setup("alpha", "beta", "gamma")
    renv.ok("create", "a", "--include", "alpha")
    renv.ok("new", "b", "--include", "beta")

    renv.ok("add", "a", "--include", "gamma")
    assert (renv.worktrees / "a" / "gamma" / ".git").exists()

    renv.ok("merge", "ab", "a", "b", "--op", "union")
    merged = renv.worktrees / "ab"
    assert (merged / "alpha" / ".git").exists()
    assert (merged / "beta" / ".git").exists()
    assert (merged / "gamma" / ".git").exists()
