"""Reusable local git repo fixtures for integration tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run_git(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd``."""
    return subprocess.run(
        ["git", *cmd],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


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

    def make_bare_and_clone(self, name: str, *, default_branch: str = "main") -> Path:
        """Create a bare remote, clone it under ``source/``, seed with an initial commit."""
        bare = self.remotes / f"{name}.git"
        run_git(["init", "--bare", str(bare)], cwd=self.root)
        clone = self.source / name
        run_git(["clone", str(bare), str(clone)], cwd=self.root)
        run_git(["config", "user.email", "test@example.com"], cwd=clone)
        run_git(["config", "user.name", "Test User"], cwd=clone)
        (clone / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        run_git(["add", "README.md"], cwd=clone)
        run_git(["commit", "-m", "init"], cwd=clone)
        run_git(["push", "origin", f"HEAD:{default_branch}"], cwd=clone)
        return clone

    def clone_path(self, name: str) -> Path:
        """Return the source clone path for ``name``."""
        return self.source / name

    @staticmethod
    def write_file(repo: Path, relpath: str, content: str) -> None:
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def commit_all(repo: Path, message: str) -> None:
        run_git(["add", "-A"], cwd=repo)
        run_git(["commit", "-m", message], cwd=repo)

    @staticmethod
    def create_local_branch(repo: Path, branch: str, *, checkout: bool = True) -> None:
        if checkout:
            run_git(["checkout", "-b", branch], cwd=repo)
        else:
            run_git(["branch", branch], cwd=repo)

    @staticmethod
    def checkout_branch(repo: Path, branch: str) -> None:
        run_git(["checkout", branch], cwd=repo)

    @staticmethod
    def checkout_branch_in_source(repo: Path, branch: str) -> None:
        """Ensure ``branch`` exists and is checked out in the source clone."""
        result = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo, check=False)
        if result.returncode != 0:
            run_git(["checkout", "-b", branch], cwd=repo)
        else:
            run_git(["checkout", branch], cwd=repo)

    @staticmethod
    def create_foreign_worktree(repo: Path, worktree_path: Path, branch: str) -> Path:
        """Add a worktree outside renv control, checking out ``branch``."""
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        exists = (
            run_git(
                ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                cwd=repo,
                check=False,
            ).returncode
            == 0
        )
        if exists:
            run_git(["worktree", "add", str(worktree_path), branch], cwd=repo)
        else:
            run_git(["worktree", "add", "-b", branch, str(worktree_path), "HEAD"], cwd=repo)
        return worktree_path

    @staticmethod
    def simulate_orphaned_worktree(repo: Path, worktree_path: Path, *, branch: str = "orphan-branch") -> None:
        """Create a worktree then delete its directory without ``git worktree remove``."""
        RepoFactory.create_foreign_worktree(repo, worktree_path, branch)
        shutil.rmtree(worktree_path)

    @staticmethod
    def leave_stray_directory(path: Path) -> None:
        """Create a plain non-git directory at a would-be worktree path."""
        path.mkdir(parents=True, exist_ok=True)
        (path / "not-a-git-repo.txt").write_text("stray", encoding="utf-8")

    @staticmethod
    def current_branch(worktree: Path) -> str | None:
        result = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=worktree, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    @staticmethod
    def is_detached(worktree: Path) -> bool:
        return RepoFactory.current_branch(worktree) is None

    @staticmethod
    def latest_commit_message(worktree: Path) -> str:
        return run_git(["log", "-1", "--pretty=%s"], cwd=worktree).stdout.strip()
