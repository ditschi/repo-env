"""Git adapter: subprocess wrappers over the git CLI.

GitPython has no real worktree API, so we shell out to ``git`` directly and
parse the porcelain output. All functions are thin and side-effect-explicit so
services can mock this module in unit tests.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repoenv.errors import GitError


def _parse_remote_head_names(ls_remote_output: str) -> list[str]:
    """Extract head branch names from ``git ls-remote --heads`` output."""
    names: list[str] = []
    prefix = "refs/heads/"
    for line in ls_remote_output.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        if not ref.startswith(prefix):
            continue
        branch = ref[len(prefix) :]
        if branch:
            names.append(branch)
    return names


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


def worktree_root(path: Path) -> Path | None:
    """Return the resolved root of the worktree containing ``path``, if any."""
    if not path.exists():
        return None
    result = _run(["rev-parse", "--show-toplevel"], cwd=path, check=False)
    if result.returncode != 0:
        return None
    top = Path(result.stdout.strip())
    return top.resolve() if top.exists() else None


def is_worktree_root(path: Path) -> bool:
    """Return True when ``path`` is itself a git worktree root (not merely nested in one)."""
    if not path.is_dir():
        return False
    root = worktree_root(path)
    return root is not None and root == path.resolve()


def discover_repos(source: Path) -> list[str]:
    """Return sorted relative paths of git repos discovered recursively under ``source``."""
    if not source.exists():
        return []

    names: set[str] = set()
    ignored_dirs = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}

    for root, dirs, files in os.walk(source):
        root_path = Path(root)

        if ".git" in dirs or ".git" in files:
            rel = root_path.relative_to(source)
            if rel != Path("."):
                names.add(rel.as_posix())
            # Repository root found; don't scan nested internals.
            dirs[:] = []
            continue

        dirs[:] = [d for d in dirs if d not in ignored_dirs]

    return sorted(names)


def _default_branch_from_symref(repo: Path, remote: str) -> str | None:
    symref = _run(["ls-remote", "--symref", remote, "HEAD"], cwd=repo, check=False)
    if symref.returncode != 0:
        return None
    for line in symref.stdout.splitlines():
        if not line.startswith("ref:"):
            continue
        # Format: "ref: refs/heads/<branch>\tHEAD"
        parts = line.split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        branch = ref.rsplit("/", 1)[-1]
        if branch and branch != "(unknown)":
            return branch
    return None


def _default_branch_from_remote_show(repo: Path, remote: str) -> str | None:
    show = _run(["remote", "show", remote], cwd=repo, check=False)
    if show.returncode != 0:
        return None
    for line in show.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("HEAD branch:"):
            continue
        branch = stripped.split(":", 1)[1].strip()
        if branch and branch != "(unknown)":
            return branch
    return None


def _default_branch_from_heads(repo: Path, remote: str) -> str | None:
    heads = _run(["ls-remote", "--heads", remote], cwd=repo, check=False)
    if heads.returncode != 0:
        return None
    names = _parse_remote_head_names(heads.stdout)
    for preferred in ("main", "develop", "master"):
        if preferred in names:
            return preferred
    unique_names = sorted(set(names))
    if len(unique_names) == 1:
        return unique_names[0]
    return None


def default_branch(repo: Path, remote: str = "origin") -> str:
    """Resolve the remote's default branch.

    Fallback chain:
    1) ``ls-remote --symref``
    2) ``remote show``
    3) ``ls-remote --heads`` heuristic: prefer ``main`` -> ``develop`` -> ``master``
    4) if remote exposes exactly one head branch, use it
    5) error
    """
    branch = _default_branch_from_symref(repo, remote)
    if branch:
        return branch

    branch = _default_branch_from_remote_show(repo, remote)
    if branch:
        return branch

    branch = _default_branch_from_heads(repo, remote)
    if branch:
        return branch

    raise GitError(
        f"Could not determine the default branch for remote '{remote}'.",
        hint="Pass --branch explicitly, set default_branch in config, or ensure remote HEAD is published.",
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
    - Otherwise creates a detached checkout at ``base``.
    """
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add"]
    if create_branch:
        args += ["-b", branch, str(worktree_path), base]
    else:
        # Detached checkout avoids "branch already checked out" conflicts with source repos.
        args += ["--detach", str(worktree_path), base]
    _run(args, cwd=repo)


def branch_exists(repo: Path, branch: str) -> bool:
    """Return True if a local branch ``branch`` exists in ``repo``."""
    result = _run(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo, check=False)
    return result.returncode == 0


def add_worktree_existing_branch(repo: Path, worktree_path: Path, branch: str) -> None:
    """Create a worktree that checks out an existing local branch."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["worktree", "add", str(worktree_path), branch], cwd=repo)


def find_worktree_for_branch(repo: Path, branch: str) -> Path | None:
    """Return the worktree path currently checking out ``branch`` (if any)."""
    target_ref = f"refs/heads/{branch}"
    for record in list_worktrees(repo):
        if record.get("branch") == target_ref:
            path = record.get("worktree")
            if path:
                return Path(path)
    return None


def checkout(worktree: Path, ref: str) -> None:
    """Check out ``ref`` in an existing working tree/worktree."""
    _run(["checkout", ref], cwd=worktree)


def stash_push(worktree: Path, *, include_untracked: bool = True, message: str | None = None) -> bool:
    """Stash local changes in ``worktree``. Return True if a stash was created."""
    before = _run(["stash", "list"], cwd=worktree, check=False).stdout.strip()
    args = ["stash", "push"]
    if include_untracked:
        args.append("-u")
    if message:
        args += ["-m", message]
    result = _run(args, cwd=worktree, check=False)
    if result.returncode != 0:
        return False
    after = _run(["stash", "list"], cwd=worktree, check=False).stdout.strip()
    return after != before


def stash_pop(worktree: Path) -> None:
    """Pop the most recent stash in ``worktree`` (fails if conflicts occur)."""
    _run(["stash", "pop"], cwd=worktree)


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
