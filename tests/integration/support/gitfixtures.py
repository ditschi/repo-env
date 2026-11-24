"""Reusable local git repo fixtures for integration tests."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

DEFAULT_BRANCH = "main"


def run_git(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd``."""
    return subprocess.run(
        ["git", *cmd],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


def existing_repos(env_dir: Path, names: Iterable[str]) -> set[str]:
    """Return the subset of ``names`` that exist as entries under ``env_dir``."""
    return {name for name in names if (env_dir / name).exists()}


def checkout_branch_in_source(repo: Path, branch: str) -> None:
    """Create the new branch ``branch`` and check it out in the source clone."""
    run_git(["checkout", "-b", branch], cwd=repo)


def create_foreign_worktree(repo: Path, worktree_path: Path, branch: str) -> Path:
    """Add a worktree outside renv control on the new branch ``branch`` (from ``HEAD``)."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(["worktree", "add", "-b", branch, str(worktree_path), "HEAD"], cwd=repo)
    return worktree_path


def simulate_orphaned_worktree(repo: Path, worktree_path: Path, *, branch: str = "orphan-branch") -> None:
    """Create a worktree then delete its directory without ``git worktree remove``."""
    create_foreign_worktree(repo, worktree_path, branch)
    shutil.rmtree(worktree_path)


def leave_stray_directory(path: Path) -> None:
    """Create a plain non-git directory at a would-be worktree path."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "not-a-git-repo.txt").write_text("stray", encoding="utf-8")


def current_branch(worktree: Path) -> str | None:
    result = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=worktree, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_detached(worktree: Path) -> bool:
    return current_branch(worktree) is None


def head_sha(worktree: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()


def worktree_listing(repo: Path) -> str:
    """``git worktree list --porcelain`` of ``repo``."""
    return run_git(["worktree", "list", "--porcelain"], cwd=repo).stdout


def latest_commit_message(worktree: Path) -> str:
    return run_git(["log", "-1", "--pretty=%s"], cwd=worktree).stdout.strip()


class RepoFactory:
    """Build git fixtures under a standard ``.testenv/<test>/`` layout.

    Layout::

        <root>/
          source/      clones used as renv --source input
          worktrees/   renv --dest output (created environments)
          remotes/     bare repos backing the source clones
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.remotes = self.root / "remotes"
        self.source = self.root / "source"
        self.worktrees = self.root / "worktrees"
        self.remotes.mkdir(exist_ok=True)
        self.source.mkdir(exist_ok=True)
        self.worktrees.mkdir(exist_ok=True)

    def make_bare_and_clone(self, name: str) -> Path:
        """Create a bare remote, clone it under ``source/``, seed with an initial commit."""
        bare = self.remotes / f"{name}.git"
        # Pin the bare repo's HEAD so fresh clones check out ``DEFAULT_BRANCH``
        # regardless of the machine's ``init.defaultBranch`` (git defaults to
        # ``master``, e.g. on CI runners).
        run_git(["init", "--bare", f"--initial-branch={DEFAULT_BRANCH}", str(bare)], cwd=self.root)
        clone = self.source / name
        run_git(["clone", str(bare), str(clone)], cwd=self.root)
        run_git(["config", "user.email", "test@example.com"], cwd=clone)
        run_git(["config", "user.name", "Test User"], cwd=clone)
        (clone / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        run_git(["add", "README.md"], cwd=clone)
        run_git(["commit", "-m", "init"], cwd=clone)
        run_git(["push", "origin", f"HEAD:{DEFAULT_BRANCH}"], cwd=clone)
        return clone
