"""Adapter around the GitHub CLI (``gh``) for bulk pull-request operations.

All calls are explicit subprocess invocations with no shell. The adapter never
pushes; callers must push worktrees first (``renv pr --push`` handles that via
the git adapter). Host is auto-detected from ``gh`` config when not provided.
Repository discovery for ``renv clone`` lives in ``adapters.scm`` instead.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from repoenv.errors import GitError


@dataclass
class PrResult:
    """Outcome of one provider's pull-request creation or lookup."""

    repo: str
    url: str
    created: bool
    skipped: bool = False
    reason: str = ""


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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


def existing_pr_url(worktree: Path, *, head: str, repository: str | None = None) -> str | None:
    """Return the URL of an open PR for ``head`` if one exists, else ``None``."""
    argv = ["pr", "list", "--head", head, "--state", "open", "--json", "url", "--jq", ".[0].url"]
    if repository:
        argv += ["--repo", repository]
    result = _run(argv, cwd=worktree)
    if result.returncode != 0:
        raise GitError(
            f"gh pr list failed in {worktree.name}: {result.stderr.strip()}",
            hint="Ensure 'gh auth status' is healthy.",
        )
    url = result.stdout.strip()
    return url or None


@dataclass(frozen=True)
class GhPullRequest:
    """Arguments for ``gh pr create``."""

    title: str
    body: str
    head: str
    base: str | None = None
    draft: bool = False
    reviewers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)

    def argv(self) -> list[str]:
        argv = ["pr", "create", "--title", self.title, "--body", self.body, "--head", self.head]
        if self.base:
            argv += ["--base", self.base]
        if self.draft:
            argv.append("--draft")
        for flag, values in (
            ("--reviewer", self.reviewers),
            ("--label", self.labels),
            ("--assignee", self.assignees),
        ):
            for value in values:
                argv += [flag, value]
        return argv


def create_pr(worktree: Path, pull_request: GhPullRequest, *, repository: str | None = None) -> str:
    """Create a pull request and return its URL. Raises ``GitError`` on failure."""
    argv = pull_request.argv()
    if repository:
        argv += ["--repo", repository]

    result = _run(argv, cwd=worktree)
    if result.returncode != 0:
        raise GitError(
            f"gh pr create failed in {worktree.name}: {result.stderr.strip()}",
            hint="Ensure the branch is pushed and 'gh auth status' is healthy.",
        )
    return result.stdout.strip()


def git_protocol(host: str | None = None) -> str:
    """Return the git protocol ``gh`` is configured to use ('ssh' or 'https').

    Falls back to ``'ssh'`` if ``gh`` has no opinion (e.g. never configured).
    """
    argv = ["config", "get", "git_protocol"]
    if host:
        argv += ["-h", host]
    result = _run(argv)
    value = result.stdout.strip()
    return value if value in ("ssh", "https") else "ssh"
