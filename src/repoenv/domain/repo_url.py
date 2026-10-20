"""Parsing/building of git remote URLs for ``renv clone``.

Supports the handful of forms ``--url`` accepts:

- A bare host: ``https://github.com``, ``https://gitlab.company.com`` --
  used together with ``--include``/``--exclude`` to discover repos.
- A host + owner: ``https://github.com/my-org`` -- same, but pre-scopes
  discovery to one owner.
- A full repo URL: ``https://github.com/owner/repo``,
  ``git@github.com:owner/repo.git``, ``ssh://git@github.com/owner/repo.git``
  -- cloned directly, no discovery needed.

Provider-specific layouts are understood when the provider kind is known:
GitLab subgroups (``group/sub/repo``), Bitbucket Server
(``/scm/PROJ/repo.git``, ``/projects/PROJ/repos/repo``) and Azure DevOps
(``org/project/_git/repo``, ``*.visualstudio.com``, ``ssh.dev.azure.com:v3/...``).
The owner of nested layouts keeps its ``/`` (e.g. ``group/sub``, ``org/project``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from repoenv.domain.scm import ProviderKind
from repoenv.errors import UsageError


@dataclass(frozen=True)
class UrlSpec:
    """A parsed ``--url`` entry."""

    host: str
    owner: str | None = None
    repo: str | None = None

    @property
    def is_fully_qualified(self) -> bool:
        """True when both ``owner`` and ``repo`` are known -- no discovery needed."""
        return self.owner is not None and self.repo is not None


_OwnerRepo = tuple[str | None, str | None]

_SCP_LIKE = re.compile(r"^(?:[\w.-]+@)?(?P<host>[\w.-]+):(?P<path>.+)$")
_AZURE_SSH_HOST = "ssh.dev.azure.com"
_AZURE_HOST = "dev.azure.com"


def _strip_git_suffix(path: str) -> str:
    return path[: -len(".git")] if path.endswith(".git") else path


def _split(raw: str) -> tuple[str, list[str]]:
    raw = raw.strip()
    if not raw:
        raise UsageError("Empty --url value.")

    if "://" in raw:
        parts = urlsplit(raw)
        if not parts.hostname:
            raise UsageError(f"Invalid --url '{raw}': no host found.")
        host, path = parts.hostname, parts.path
    else:
        match = _SCP_LIKE.match(raw)
        if not match:
            raise UsageError(
                f"Invalid --url '{raw}'.",
                hint="Use a host URL (https://github.com), an owner URL "
                "(https://github.com/org), a full repo URL "
                "(https://github.com/owner/repo), or scp-like syntax "
                "(git@github.com:owner/repo.git).",
            )
        host, path = match.group("host"), match.group("path")

    segments = [unquote(segment) for segment in _strip_git_suffix(path.strip("/")).split("/") if segment]
    host = host.lower()
    if host == _AZURE_SSH_HOST:
        return _AZURE_HOST, segments[1:] if segments[:1] == ["v3"] else segments
    if host.endswith(".visualstudio.com"):
        return _AZURE_HOST, [host.split(".", 1)[0], *segments]
    return host, segments


def url_host(raw: str) -> str:
    """Return the (normalized) host of a ``--url`` entry."""
    return _split(raw)[0]


def _azure_segments(raw: str, segments: list[str]) -> _OwnerRepo:
    segments = [segment for segment in segments if segment != "_git"]
    if len(segments) > 3:
        raise UsageError(f"Invalid --url '{raw}': expected 'organization/project/repo'.")
    if len(segments) == 3:
        return "/".join(segments[:2]), segments[2]
    return "/".join(segments) or None, None


def _gitlab_segments(segments: list[str]) -> _OwnerRepo:
    if "-" in segments:  # web UI paths: group/repo/-/tree/main
        segments = segments[: segments.index("-")]
    if len(segments) >= 2:
        return "/".join(segments[:-1]), segments[-1]
    return (segments[0] if segments else None), None


def _bitbucket_server_segments(raw: str, segments: list[str]) -> _OwnerRepo:
    head = segments[:1]
    if head in (["projects"], ["users"]):
        owner = segments[1] if len(segments) > 1 else None
        if owner and head == ["users"]:
            owner = f"~{owner}"
        repo = segments[3] if len(segments) > 3 and segments[2] == "repos" else None
        return owner, repo
    if head == ["scm"]:
        segments = segments[1:]
    if len(segments) > 2:
        raise UsageError(f"Invalid --url '{raw}': expected '/scm/PROJECT/repo' or '/projects/PROJECT'.")
    return (segments[0] if segments else None), (segments[1] if len(segments) == 2 else None)


def _github_style_segments(raw: str, segments: list[str]) -> _OwnerRepo:
    if len(segments) > 2:
        raise UsageError(
            f"Invalid --url '{raw}': expected at most 'host/owner/repo', got {len(segments)} path segments."
        )
    return (segments[0] if segments else None), (segments[1] if len(segments) == 2 else None)


def parse_url(raw: str, kind: ProviderKind | None = None) -> UrlSpec:
    """Parse a ``--url`` entry into a host and, if present, an owner/repo.

    ``kind`` selects provider-specific path layouts; ``None`` (unknown provider)
    and the GitHub-style providers accept at most ``owner/repo``.
    Raises ``UsageError`` for input that isn't a recognizable git remote URL.
    """
    host, segments = _split(raw)
    if host == _AZURE_HOST:
        kind = ProviderKind.AZURE_DEVOPS

    if kind is ProviderKind.AZURE_DEVOPS:
        owner, repo = _azure_segments(raw, segments)
    elif kind is ProviderKind.BITBUCKET_SERVER:
        owner, repo = _bitbucket_server_segments(raw, segments)
    elif kind is ProviderKind.GITLAB:
        owner, repo = _gitlab_segments(segments)
    else:
        owner, repo = _github_style_segments(raw, segments)
    return UrlSpec(host=host, owner=owner, repo=repo)


def build_clone_url(
    host: str, owner: str, repo: str, *, protocol: str, kind: ProviderKind | None = None
) -> str:
    """Build a clone URL for ``owner/repo`` on ``host`` using ``protocol`` ('ssh' or 'https').

    Used for repos named literally (no API call). Discovered repos use the
    clone URLs reported by the provider API instead.
    """
    if protocol not in ("ssh", "https"):
        raise UsageError(f"Unknown protocol '{protocol}'.", hint="Use 'ssh' or 'https'.")

    if kind is ProviderKind.AZURE_DEVOPS:
        org_project = "/".join(quote(part) for part in owner.split("/", 1))
        if protocol == "https":
            return f"https://{host}/{org_project}/_git/{quote(repo)}"
        if host == _AZURE_HOST:
            return f"git@{_AZURE_SSH_HOST}:v3/{org_project}/{quote(repo)}"
        return f"ssh://{host}:22/{org_project}/_git/{quote(repo)}"

    if kind is ProviderKind.BITBUCKET_SERVER:
        if protocol == "https":
            return f"https://{host}/scm/{owner}/{repo}.git"
        return f"ssh://git@{host}:7999/{owner}/{repo}.git"

    if protocol == "ssh":
        return f"git@{host}:{owner}/{repo}.git"
    return f"https://{host}/{owner}/{repo}.git"
