"""Adapter around the GitHub CLI (``gh``) for bulk pull-request and clone operations.

All calls are explicit subprocess invocations with no shell. The adapter never
pushes; callers must push worktrees first (``renv pr --push`` handles that via
the git adapter). Host is auto-detected from ``gh`` config when not provided.
"""

from __future__ import annotations

import json
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


@dataclass(frozen=True)
class OrgMembership:
    """One organization the authenticated ``gh`` user belongs to."""

    login: str
    role: str  # raw GitHub API role: "admin" or "member"
    state: str  # "active" or "pending"


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv list, no shell
        ["gh", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _host_args(host: str | None) -> list[str]:
    return ["--hostname", host] if host else []


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


def list_org_memberships(host: str | None = None) -> list[OrgMembership]:
    """Return every org the authenticated ``gh`` user belongs to, active or pending.

    Role/state filtering (the ``--role`` semantics for ``renv clone``) is left
    to the caller -- see ``services.clone_service``.
    """
    argv = [
        "api",
        "user/memberships/orgs",
        "--paginate",
        *_host_args(host),
        "--jq",
        "[.[] | {login: .organization.login, role: .role, state: .state}]",
    ]
    result = _run(argv)
    if result.returncode != 0:
        raise GitError(
            f"gh api user/memberships/orgs failed: {result.stderr.strip()}",
            hint="Run 'gh auth status' (and 'gh auth login --hostname <host>' for enterprise hosts).",
        )
    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [OrgMembership(login=item["login"], role=item["role"], state=item["state"]) for item in raw]


def list_owner_repos(owner: str, *, host: str | None = None) -> list[str]:
    """Return every repo name owned by ``owner`` (organization or user account).

    Tries the organization endpoint first (the common case), then falls back
    to the user endpoint for personal accounts.
    """
    last_error = ""
    for kind in ("orgs", "users"):
        argv = [
            "api",
            f"{kind}/{owner}/repos",
            "--paginate",
            *_host_args(host),
            "--jq",
            "[.[].name]",
        ]
        result = _run(argv)
        if result.returncode == 0:
            try:
                names: list[str] = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return []
            return names
        last_error = result.stderr.strip()

    raise GitError(
        f"Could not list repositories for '{owner}' on {host or 'github.com'}: {last_error}",
        hint="Check the owner name and that 'gh auth status' is healthy.",
    )
