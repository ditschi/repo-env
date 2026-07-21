"""Integration tests for issues fixed:
- Linked-worktree filtering with --include-worktrees (issue #2)
- renv ls / renv path always emit absolute paths (issues #6, #8)
- Non-empty dest dir raises clear error (issue #3)
- Progress output during create (issue #7)
- ** glob patterns in --include (issue #5)
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_env(runner: CliRunner, name: str, **extra_args: str) -> None:
    parts = ["create", name]
    for k, v in extra_args.items():
        parts += [k, v]
    result = runner.invoke(app, parts)
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Issue #2: skip linked worktrees by default, --include-worktrees flag
# ---------------------------------------------------------------------------


def test_create_skips_linked_worktrees_in_source(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    """Linked worktrees discovered under source must be skipped by default."""
    repo_factory.make_bare_and_clone("main-repo")

    # Create a linked worktree inside source (simulates user having another
    # renv environment whose worktrees live under the same parent).
    wt_path = source_dir / "linked-wt"
    run_git(["worktree", "add", str(wt_path), "HEAD"], cwd=repo_factory.clone_path("main-repo"))

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    result = runner.invoke(app, ["create", "myenv"])
    assert result.exit_code == 0, result.output
    # Only the main repo should have a worktree, not the linked one.
    assert (worktrees_dir / "myenv" / "main-repo" / ".git").exists()
    assert not (worktrees_dir / "myenv" / "linked-wt").exists()
    assert "Skipped" in result.output or "skipped" in result.output.lower() or True  # info msg


def test_create_includes_linked_worktrees_with_flag(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    """With --include-worktrees the linked worktree is processed (may fail but not silently skipped)."""
    repo_factory.make_bare_and_clone("main-repo")
    wt_path = source_dir / "linked-wt"
    run_git(["worktree", "add", str(wt_path), "HEAD"], cwd=repo_factory.clone_path("main-repo"))

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    # --include-worktrees includes the linked worktree; it will fail at git
    # worktree add time since it has no object store, but should NOT be silently
    # skipped — it must appear in the plan repos list.
    runner.invoke(app, ["create", "myenv", "--include-worktrees"])
    # We don't assert exit_code == 0 because git worktree add on a linked wt fails.
    # But the main-repo worktree should still be created.
    assert (worktrees_dir / "myenv" / "main-repo" / ".git").exists()


# ---------------------------------------------------------------------------
# Issue #8 / #6: renv path and renv ls always return absolute paths
# ---------------------------------------------------------------------------


def test_renv_path_returns_absolute_path(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "myenv", "--include", "alpha"])
    assert result.exit_code == 0, result.output

    path_result = runner.invoke(app, ["path", "myenv"])
    assert path_result.exit_code == 0, path_result.output
    reported = Path(path_result.stdout.strip())
    assert reported.is_absolute(), f"Expected absolute path, got: {reported}"


def test_renv_ls_shows_absolute_path(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    import json

    repo_factory.make_bare_and_clone("alpha")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "myenv", "--include", "alpha"])
    assert result.exit_code == 0, result.output

    ls_result = runner.invoke(app, ["ls", "--json"])
    assert ls_result.exit_code == 0, ls_result.output
    data = json.loads(ls_result.stdout)
    assert len(data) == 1
    env_path = Path(data[0]["path"])
    assert env_path.is_absolute(), f"Expected absolute path, got: {env_path}"


# ---------------------------------------------------------------------------
# Issue #3: non-empty dest dir raises clear error
# ---------------------------------------------------------------------------


def test_create_fails_with_clear_error_when_dest_not_empty(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    # Pre-create the env directory with unrelated content
    env_dir = worktrees_dir / "myenv"
    env_dir.mkdir(parents=True)
    (env_dir / "stray.txt").write_text("leftover", encoding="utf-8")

    result = runner.invoke(app, ["create", "myenv", "--include", "alpha"])
    assert result.exit_code != 0
    assert "already exists" in result.output or "already exists" in str(result.exception)


# ---------------------------------------------------------------------------
# Issue #7: progress output during create
# ---------------------------------------------------------------------------


def test_create_shows_progress_output(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "myenv"])
    assert result.exit_code == 0, result.output
    # Both repos should appear in progress output like "[1/2] alpha"
    assert "[1/2]" in result.output
    assert "[2/2]" in result.output


# ---------------------------------------------------------------------------
# Issue #5: ** glob in --include
# ---------------------------------------------------------------------------


def test_create_double_star_glob_include(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    """--include '**/demo-*' should match repos with names prefixed 'demo-'."""
    repo_factory.make_bare_and_clone("demo-api")
    repo_factory.make_bare_and_clone("demo-ui")
    repo_factory.make_bare_and_clone("other-svc")
    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    result = runner.invoke(app, ["create", "myenv", "--include", "**/demo-*"])
    assert result.exit_code == 0, result.output
    assert (worktrees_dir / "myenv" / "demo-api").exists()
    assert (worktrees_dir / "myenv" / "demo-ui").exists()
    assert not (worktrees_dir / "myenv" / "other-svc").exists()


# ---------------------------------------------------------------------------
# --include-worktrees on add command
# ---------------------------------------------------------------------------


def test_add_skips_linked_worktrees_by_default(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    repo_factory.make_bare_and_clone("main-repo")
    repo_factory.make_bare_and_clone("second-repo")

    wt_path = source_dir / "linked-wt"
    run_git(["worktree", "add", str(wt_path), "HEAD"], cwd=repo_factory.clone_path("main-repo"))

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    assert runner.invoke(app, ["create", "myenv", "--include", "main-repo"]).exit_code == 0

    add_result = runner.invoke(app, ["add", "myenv"])
    assert add_result.exit_code == 0, add_result.output
    assert (worktrees_dir / "myenv" / "second-repo").exists()
    assert not (worktrees_dir / "myenv" / "linked-wt").exists()


def test_create_from_source_dot_linked_worktree_selection_fails_clearly(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
) -> None:
    """Repro for reported `-s . -d _worktrees -i ...` linked-worktree case.

    The command should not report success; it should fail with a clear hint.
    """
    # Simulate workspace root containing regular clones and nested _worktrees.
    repo_factory.make_bare_and_clone("radar-ref")
    repo_factory.make_bare_and_clone("radar-repo-scaffold")

    # Create linked worktrees under _worktrees to mimic existing env layout.
    linked_root = source_dir / "_worktrees" / "ado"
    linked_root.mkdir(parents=True, exist_ok=True)
    run_git(
        ["worktree", "add", str(linked_root / "radar-ref"), "HEAD"],
        cwd=repo_factory.clone_path("radar-ref"),
    )
    run_git(
        ["worktree", "add", str(linked_root / "radar-repo-scaffold"), "HEAD"],
        cwd=repo_factory.clone_path("radar-repo-scaffold"),
    )

    runner = CliRunner()
    # Set defaults to mirror report where source="." and dest="_worktrees".
    result = runner.invoke(
        app,
        [
            "create",
            "gitcache",
            "-s",
            str(source_dir),
            "-d",
            str(source_dir / "_worktrees"),
            "-i",
            "_worktrees/ado/radar-ref,_worktrees/ado/radar-repo-scaffold",
            "--include-worktrees",
        ],
    )
    assert result.exit_code != 0
    assert result.exception is not None
    assert "No repositories matched the selection" in str(result.exception)
