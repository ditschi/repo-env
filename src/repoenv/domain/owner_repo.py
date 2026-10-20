"""``owner/repo`` glob patterns for ``renv clone``'s ``--include``/``--exclude``.

Patterns select which remote repositories to clone by matching the combined
``owner/repo`` pair, e.g. ``myself/test-*``, ``owner/repo2``, or
``prefix-*/*``. Unlike ``renv create``/``add``'s include/exclude (which match
a single relative path with ``fnmatch``, where ``*`` already crosses ``/``),
here ``*`` is scoped to *one side* of the pair -- ``prefix-*/*`` must not
accidentally match repos under an unrelated owner just because ``*`` also
matches literal slashes. So each pattern is split at its *last* ``/`` into an
owner-glob and a repo-glob, matched independently. The owner side may itself
contain ``/`` for providers with nested owners: GitLab subgroups
(``group/sub/repo-*``, ``group/*/repo-*``) and Azure DevOps
(``organization/project/repo``).

The one exception is the literal string ``**``, a shorthand for "match
everything" (``*/*``) -- convenient when combined with ``--role`` to say
"give me every repo in every org I have access to" without spelling out
``*/*``.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch

from repoenv.domain.selection import split_csv
from repoenv.errors import UsageError

MATCH_ALL_PATTERN = "**"


def validate_owner_repo_pattern(pattern: str) -> tuple[str, str]:
    """Split ``pattern`` into ``(owner_glob, repo_glob)``, or raise ``UsageError``.

    Rules:
    - ``"**"`` is shorthand for ``("*", "*")`` (match everything).
    - Any other pattern must contain at least one ``/``; it is split at the
      last one, with a non-empty glob on each side.
    """
    if pattern == MATCH_ALL_PATTERN:
        return "*", "*"

    if "/" not in pattern:
        raise UsageError(
            f"Invalid owner/repo pattern '{pattern}'.",
            hint=(
                "Patterns must be 'owner/repo' (globs allowed on either side), e.g. "
                "'myorg/*', 'owner/repo', 'prefix-*/*', or 'group/subgroup/repo-*' for "
                "nested owners. Use '**' to match every repo in every reachable owner."
            ),
        )

    owner_glob, _, repo_glob = pattern.rpartition("/")
    if not owner_glob or not repo_glob or "" in owner_glob.split("/"):
        raise UsageError(
            f"Invalid owner/repo pattern '{pattern}'.",
            hint="Both the owner and repo side of the pattern must be non-empty.",
        )
    return owner_glob, repo_glob


def expand_owner_repo_patterns(patterns: list[str]) -> list[tuple[str, str]]:
    """Split CSV/repeatable ``patterns`` into validated ``(owner_glob, repo_glob)`` pairs."""
    return [validate_owner_repo_pattern(pattern) for pattern in split_csv(patterns)]


def has_wildcard(glob: str) -> bool:
    """Return True if ``glob`` contains any ``fnmatch`` wildcard character."""
    return any(char in glob for char in "*?[")


def root_owner(owner: str) -> str:
    """Top-level owner of a (possibly nested) owner path/glob: ``group/sub`` -> ``group``."""
    return owner.split("/", 1)[0]


_HINT_BREAKS = re.compile(r"\[[^\]]*\]|[*?\[\]\-_. /]")


def search_hint(glob: str, *, min_length: int = 3) -> str | None:
    """Longest alphanumeric literal in ``glob`` -- a server-side pre-filter, never the final match.

    ``radar-*`` -> ``radar``. Separators are excluded because providers search
    the display name, which may differ from the slug (``Radar Tools`` vs
    ``radar-tools``). Returns ``None`` when no run reaches ``min_length``
    (short terms are rejected or exact-matched by some provider search APIs).
    """
    longest = max(_HINT_BREAKS.split(glob), key=len)
    return longest if len(longest) >= min_length else None


def match_owner_repo(owner: str, repo: str, patterns: list[tuple[str, str]]) -> bool:
    """Return True if ``owner/repo`` matches any of the ``(owner_glob, repo_glob)`` pairs."""
    return any(fnmatch(owner, owner_glob) and fnmatch(repo, repo_glob) for owner_glob, repo_glob in patterns)
