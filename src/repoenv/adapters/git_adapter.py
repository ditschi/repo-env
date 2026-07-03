"""Git adapter: subprocess wrappers over the git CLI.

GitPython has no real worktree API, so we shell out to ``git`` directly and
parse the porcelain output. All functions are thin and side-effect-explicit so
services can mock this module in unit tests.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from repoenv.errors import GitError


@dataclass(frozen=True)
class GitResult:
    """Result of a git invocation."""

    returncode: int
    stdout: str
    stderr: str


def _run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    result = GitResult(proc.returncode, proc.stdout, proc.stderr)
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}",
            hint="Check that the path is a git repository and the remote is reachable.",
        )
    return result


def is_git_repo(path: Path) -> bool:
    """Return True if ``path`` is inside a git working tree."""
    result = _run(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def discover_repos(source: Path) -> list[str]:
    """Return sorted names of immediate subdirectories of ``source`` that are git repos."""
    if not source.exists():
        return []
    names = [child.name for child in source.iterdir() if child.is_dir() and (child / ".git").exists()]
    return sorted(names)


def default_branch(repo: Path, remote: str = "origin") -> str:
    """Resolve the remote's default branch.

    Fallback chain: ``ls-remote --symref`` -> ``remote show`` -> error. We never
    guess ``main``/``master``.
    """
    symref = _run(["ls-remote", "--symref", remote, "HEAD"], cwd=repo, check=False)
    if symref.returncode == 0:
        for line in symref.stdout.splitlines():
            if line.startswith("ref:"):
                # Format: "ref: refs/heads/<branch>\tHEAD"
                ref = line.split()[1]
                return ref.rsplit("/", 1)[-1]

    show = _run(["remote", "show", remote], cwd=repo, check=False)
    if show.returncode == 0:
        for line in show.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("HEAD branch:"):
                return stripped.split(":", 1)[1].strip()

    raise GitError(
        f"Could not determine the default branch for remote '{remote}'.",
        hint="Pass --branch explicitly or set default_branch in the config.",
    )


def rev_parse(repo: Path, ref: str) -> str:
    """Return the resolved SHA for ``ref``."""
    return _run(["rev-parse", ref], cwd=repo).stdout.strip()


def fetch(repo: Path, remote: str = "origin") -> None:
    """Fetch updates from ``remote``."""
    _run(["fetch", "--quiet", remote], cwd=repo)


def is_clean(repo: Path) -> bool:
    """Return True if the working tree has no staged or unstaged changes."""
    result = _run(["status", "--porcelain"], cwd=repo)
    return result.stdout.strip() == ""


def add_worktree(repo: Path, worktree_path: Path, *, branch: str, base: str, create_branch: bool) -> None:
    """Create a git worktree at ``worktree_path``.

    - ``create_branch=True`` creates ``branch`` from ``base`` (``git worktree add -b``).
    - Otherwise checks out the existing ``branch``.
    """
    args = ["worktree", "add"]
    if create_branch:
        args += ["-b", branch, str(worktree_path), base]
    else:
        # Detached checkout avoids "branch already checked out" conflicts with source repos.
        args += ["--detach", str(worktree_path), base]
    _run(args, cwd=repo)


def list_worktrees(repo: Path) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into a list of records."""
    result = _run(["worktree", "list", "--porcelain"], cwd=repo)
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        records.append(current)
    return records


def remove_worktree(repo: Path, worktree_path: Path, *, force: bool = False) -> None:
    """Remove a git worktree."""
    args = ["worktree", "remove", str(worktree_path)]
    if force:
        args.append("--force")
    _run(args, cwd=repo)


def prune_worktrees(repo: Path) -> None:
    """Prune stale worktree administrative files."""
    _run(["worktree", "prune"], cwd=repo)


def current_branch(worktree: Path) -> str | None:
    """Return the checked-out branch name, or ``None`` if detached."""
    result = _run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=worktree, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def has_diff(worktree: Path, base_ref: str) -> bool:
    """Return True if the worktree HEAD differs from ``base_ref``."""
    result = _run(["rev-list", "--count", f"{base_ref}..HEAD"], cwd=worktree, check=False)
    if result.returncode != 0:
        return True
    return result.stdout.strip() not in ("", "0")


def push(worktree: Path, *, remote: str, branch: str, set_upstream: bool = True) -> None:
    """Push ``branch`` to ``remote`` from ``worktree``."""
    args = ["push"]
    if set_upstream:
        args.append("--set-upstream")
    args += [remote, branch]
    _run(args, cwd=worktree)
