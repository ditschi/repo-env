"""``renv merge`` must preserve each repo's own task branch.

Before this, ``build_merge_plan`` only combined repo *names*; the merged
environment's worktrees were always freshly created detached at the default
branch, silently dropping whatever branch each source environment was
actually working on.
"""

from __future__ import annotations

from dataclasses import dataclass

from click.testing import Result

from tests.integration.support import gitfixtures
from tests.integration.support.renv_helpers import Renv, env_meta


@dataclass(frozen=True)
class _Side:
    """One source environment of the merge: its single repo and optional task branch."""

    repo: str
    branch: str | None = None

    def create_opts(self) -> tuple[str, ...]:
        branch = ("--branch", self.branch) if self.branch else ()
        return (*branch, "--include", self.repo)


def _merge(renv: Renv, left: _Side, right: _Side, *merge_opts: str) -> Result:
    """Create envs ``left`` and ``right``, then ``renv merge merged left right <merge_opts>``."""
    renv.setup(*dict.fromkeys((left.repo, right.repo)))
    renv.ok("create", "left", *left.create_opts())
    renv.ok("create", "right", *right.create_opts())
    return renv.ok("merge", "merged", "left", "right", *merge_opts)


def test_merge_union_preserves_each_sides_branch(renv: Renv) -> None:
    _merge(renv, _Side("alpha", "feature/a"), _Side("beta", "feature/b"), "--op", "union")

    assert gitfixtures.current_branch(renv.worktrees / "merged" / "alpha") == "feature/a"
    assert gitfixtures.current_branch(renv.worktrees / "merged" / "beta") == "feature/b"


def test_merge_intersect_conflicting_branch_prefers_left_and_reports(renv: Renv) -> None:
    merge = _merge(renv, _Side("alpha", "feature/left"), _Side("alpha", "feature/right"), "--op", "intersect")

    assert all(text in merge.output for text in ("branch conflict", "feature/left", "feature/right")), (
        merge.output
    )
    assert gitfixtures.current_branch(renv.worktrees / "merged" / "alpha") == "feature/left"


def test_merge_moves_branch_out_of_the_source_environment(renv: Renv) -> None:
    """Git allows one worktree per branch, so preserving the branch in ``merged``
    means the original environment's worktree loses it (goes detached)."""
    _merge(renv, _Side("alpha", "feature/a"), _Side("beta", "feature/b"), "--op", "union")

    assert gitfixtures.current_branch(renv.worktrees / "merged" / "alpha") == "feature/a"
    assert gitfixtures.is_detached(renv.worktrees / "left" / "alpha") is True


def test_merge_recreate_marker_records_on_branch_conflict(renv: Renv) -> None:
    _merge(renv, _Side("alpha"), _Side("beta"), "--op", "union", "--on-branch-conflict", "fail")

    command = env_meta(renv.worktrees / "merged")["marker"]["command"]
    assert command["options"]["on_branch_conflict"] == "fail"
    assert "--on-branch-conflict fail" in command["recreate"]


def test_merge_does_not_carry_over_plain_detached_checkout(renv: Renv) -> None:
    """A repo created without --branch (detached at default) has no 'task branch' to carry over."""
    merge = _merge(renv, _Side("alpha"), _Side("beta", "feature/b"), "--op", "union")

    assert "branch conflict" not in merge.output
    merged = renv.worktrees / "merged"
    assert (gitfixtures.is_detached(merged / "alpha"), gitfixtures.current_branch(merged / "beta")) == (
        True,
        "feature/b",
    )
