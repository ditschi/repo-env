"""Parsing/building of git remote URLs for ``renv clone``.

Supports the handful of forms ``--url`` accepts:

- A bare host: ``https://github.com``, ``https://github.company.com`` --
  used together with ``--include``/``--exclude`` to discover repos.
- A host + owner: ``https://github.com/my-org`` -- same, but pre-scopes
  discovery to one owner.
- A full repo URL: ``https://github.com/owner/repo``,
  ``git@github.com:owner/repo.git``, ``ssh://git@github.com/owner/repo.git``
  -- cloned directly, no discovery needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

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


_SCP_LIKE = re.compile(r"^(?:[\w.-]+@)?(?P<host>[\w.-]+):(?P<path>.+)$")


def _strip_git_suffix(path: str) -> str:
    return path[: -len(".git")] if path.endswith(".git") else path


def parse_url(raw: str) -> UrlSpec:
    """Parse a ``--url`` entry into a host and, if present, an owner/repo.

    Raises ``UsageError`` for input that isn't a recognizable git remote URL.
    """
    raw = raw.strip()
    if not raw:
        raise UsageError("Empty --url value.")

    if "://" in raw:
        parts = urlsplit(raw)
        if not parts.hostname:
            raise UsageError(f"Invalid --url '{raw}': no host found.")
        host = parts.hostname
        path = _strip_git_suffix(parts.path.strip("/"))
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
        host = match.group("host")
        path = _strip_git_suffix(match.group("path").strip("/"))

    if not path:
        return UrlSpec(host=host)

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) == 1:
        return UrlSpec(host=host, owner=segments[0])
    if len(segments) == 2:
        return UrlSpec(host=host, owner=segments[0], repo=segments[1])
    raise UsageError(
        f"Invalid --url '{raw}': expected at most 'host/owner/repo', got {len(segments)} path segments."
    )


def build_clone_url(host: str, owner: str, repo: str, *, protocol: str) -> str:
    """Build a clone URL for ``owner/repo`` on ``host`` using ``protocol`` ('ssh' or 'https')."""
    if protocol == "ssh":
        return f"git@{host}:{owner}/{repo}.git"
    if protocol == "https":
        return f"https://{host}/{owner}/{repo}.git"
    raise UsageError(f"Unknown protocol '{protocol}'.", hint="Use 'ssh' or 'https'.")
