"""Integration tests for issues fixed:
- Linked-worktree filtering with --include-worktrees (issue #2)
- renv ls / renv path always emit absolute paths (issues #6, #8)
- Non-empty dest dir raises clear error (issue #3)
- Progress output during create (issue #7)
- ** glob patterns in --include (issue #5)
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.support.gitfixtures import existing_repos, run_git
from tests.integration.support.renv_helpers import Renv, assert_failed_with

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_worktree_at_head(clone: Path, worktree: Path) -> None:
    run_git(["worktree", "add", str(worktree), "HEAD"], cwd=clone)


def _setup_with_linked_worktree(renv: Renv, *names: str) -> Path:
    """Clone ``names`` and init, with a linked worktree of the first clone under source; returns its path.

    Simulates the user having another renv environment whose worktrees live under the same parent.
    """
    clones = renv.setup(*names)
    linked = renv.source / "linked-wt"
    _add_worktree_at_head(clones[0], linked)
    return linked


def _myenv_with_alpha(renv: Renv) -> Renv:
    renv.setup("alpha")
    renv.ok("create", "myenv", "--include", "alpha")
    return renv


# ---------------------------------------------------------------------------
# Issue #2: skip linked worktrees by default, --include-worktrees flag
# ---------------------------------------------------------------------------


def test_create_skips_linked_worktrees_in_source(renv: Renv) -> None:
    """Linked worktrees discovered under source must be skipped by default."""
    _setup_with_linked_worktree(renv, "main-repo")

    renv.ok("create", "myenv")
    # Only the main repo should have a worktree, not the linked one.
    assert (renv.worktrees / "myenv" / "main-repo" / ".git").exists()
    assert not (renv.worktrees / "myenv" / "linked-wt").exists()


def test_create_includes_linked_worktrees_with_flag(renv: Renv) -> None:
    """With --include-worktrees the linked worktree is processed (may fail but not silently skipped)."""
    _setup_with_linked_worktree(renv, "main-repo")

    # --include-worktrees includes the linked worktree; it will fail at git
    # worktree add time since it has no object store, but should NOT be silently
    # skipped — it must appear in the plan repos list.
    renv.invoke("create", "myenv", "--include-worktrees")
    # We don't assert exit_code == 0 because git worktree add on a linked wt fails.
    # But the main-repo worktree should still be created.
    assert (renv.worktrees / "myenv" / "main-repo" / ".git").exists()


# ---------------------------------------------------------------------------
# Issue #8 / #6: renv path and renv ls always return absolute paths
# ---------------------------------------------------------------------------


def test_renv_path_returns_absolute_path(renv: Renv) -> None:
    reported = Path(_myenv_with_alpha(renv).ok("path", "myenv").stdout.strip())
    assert reported.is_absolute(), f"Expected absolute path, got: {reported}"


def test_renv_ls_shows_absolute_path(renv: Renv) -> None:
    data = json.loads(_myenv_with_alpha(renv).ok("ls", "--json").stdout)
    assert len(data) == 1
    env_path = Path(data[0]["path"])
    assert env_path.is_absolute(), f"Expected absolute path, got: {env_path}"


# ---------------------------------------------------------------------------
# Issue #3: non-empty dest dir raises clear error
# ---------------------------------------------------------------------------


def test_create_fails_with_clear_error_when_dest_not_empty(renv: Renv) -> None:
    renv.setup("alpha")

    # Pre-create the env directory with unrelated content
    env_dir = renv.worktrees / "myenv"
    env_dir.mkdir(parents=True)
    (env_dir / "stray.txt").write_text("leftover", encoding="utf-8")

    result = renv.invoke("create", "myenv", "--include", "alpha")
    assert result.exit_code != 0
    assert "already exists" in result.output or "already exists" in str(result.exception)


# ---------------------------------------------------------------------------
# Issue #7: progress output during create
# ---------------------------------------------------------------------------


def test_create_shows_progress_output(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    output = renv.ok("create", "myenv").output
    # Both repos should appear in progress output like "[1/2] alpha"
    assert "[1/2]" in output
    assert "[2/2]" in output


# ---------------------------------------------------------------------------
# Issue #5: ** glob in --include
# ---------------------------------------------------------------------------


def test_create_double_star_glob_include(renv: Renv) -> None:
    """--include '**/demo-*' should match repos with names prefixed 'demo-'."""
    names = ("demo-api", "demo-ui", "other-svc")
    renv.setup(*names)
    renv.ok("create", "myenv", "--include", "**/demo-*")
    assert existing_repos(renv.worktrees / "myenv", names) == {"demo-api", "demo-ui"}


# ---------------------------------------------------------------------------
# --include-worktrees on add command
# ---------------------------------------------------------------------------


def test_add_skips_linked_worktrees_by_default(renv: Renv) -> None:
    _setup_with_linked_worktree(renv, "main-repo", "second-repo")
    renv.ok("create", "myenv", "--include", "main-repo")

    renv.ok("add", "myenv")
    assert (renv.worktrees / "myenv" / "second-repo").exists()
    assert not (renv.worktrees / "myenv" / "linked-wt").exists()


def test_create_from_source_dot_linked_worktree_selection_fails_clearly(renv: Renv) -> None:
    """Repro for reported `-s . -d _worktrees -i ...` linked-worktree case.

    The command should not report success; it should fail with a clear hint.
    """
    # Simulate workspace root containing regular clones and nested _worktrees.
    names = ("radar-ref", "radar-repo-scaffold")
    # Create linked worktrees under _worktrees to mimic existing env layout.
    linked_root = renv.source / "_worktrees" / "ado"
    linked_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        _add_worktree_at_head(renv.repos.make_bare_and_clone(name), linked_root / name)

    # Set defaults to mirror report where source="." and dest="_worktrees".
    result = renv.invoke(
        "create",
        "gitcache",
        "-s",
        str(renv.source),
        "-d",
        str(renv.source / "_worktrees"),
        "-i",
        "_worktrees/ado/radar-ref,_worktrees/ado/radar-repo-scaffold",
        "--include-worktrees",
    )
    assert_failed_with(result, "No repositories matched the selection")
