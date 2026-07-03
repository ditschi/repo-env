"""Adapter around the GitHub CLI (``gh``) for bulk pull-request operations.

All calls are explicit subprocess invocations with no shell. The adapter never
pushes; callers must push worktrees first (``renv pr --push`` handles that via
the git adapter). Host is auto-detected from ``gh`` config when not provided.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from repoenv.errors import GitError


@dataclass
class PrResult:
    """Outcome of a single ``gh pr create`` (or lookup) invocation."""

    repo: str
    url: str
    created: bool
    skipped: bool = False
    reason: str = ""


def _run(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv list, no shell
        ["gh", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def is_available() -> bool:
    """Return True when the ``gh`` binary is usable."""
    try:
        result = subprocess.run(  # noqa: S603,S607
            ["gh", "--version"], capture_output=True, text=True, check=False
        )
    except (OSError, ValueError):
        return False
    return result.returncode == 0


def existing_pr_url(worktree: Path, *, head: str) -> str | None:
    """Return the URL of an open PR for ``head`` if one exists, else ``None``."""
    result = _run(
        ["pr", "list", "--head", head, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        cwd=worktree,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def create_pr(
    worktree: Path,
    *,
    title: str,
    body: str,
    base: str | None,
    head: str,
    draft: bool,
    reviewers: list[str],
    labels: list[str],
    assignees: list[str],
) -> str:
    """Create a pull request and return its URL. Raises ``GitError`` on failure."""
    argv = ["pr", "create", "--title", title, "--body", body, "--head", head]
    if base:
        argv += ["--base", base]
    if draft:
        argv.append("--draft")
    for reviewer in reviewers:
        argv += ["--reviewer", reviewer]
    for label in labels:
        argv += ["--label", label]
    for assignee in assignees:
        argv += ["--assignee", assignee]

    result = _run(argv, cwd=worktree)
    if result.returncode != 0:
        raise GitError(
            f"gh pr create failed in {worktree.name}: {result.stderr.strip()}",
            hint="Ensure the branch is pushed and 'gh auth status' is healthy.",
        )
    return result.stdout.strip()
