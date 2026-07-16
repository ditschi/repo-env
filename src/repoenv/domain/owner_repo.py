"""``owner/repo`` glob patterns for ``renv clone``'s ``--include``/``--exclude``.

Patterns select which remote repositories to clone by matching the combined
``owner/repo`` pair, e.g. ``myself/test-*``, ``owner/repo2``, or
``prefix-*/*``. Unlike ``renv create``/``add``'s include/exclude (which match
a single relative path with ``fnmatch``, where ``*`` already crosses ``/``),
here ``*`` is scoped to *one side* of the pair -- ``prefix-*/*`` must not
accidentally match repos under an unrelated owner just because ``*`` also
matches literal slashes. So each pattern is required to contain exactly one
``/`` splitting an owner-glob from a repo-glob, matched independently.

The one exception is the literal string ``**``, a shorthand for "match
everything" (``*/*``) -- convenient when combined with ``--role`` to say
"give me every repo in every org I have access to" without spelling out
``*/*``.
"""

from __future__ import annotations

from fnmatch import fnmatch

from repoenv.domain.selection import split_csv
from repoenv.errors import UsageError

MATCH_ALL_PATTERN = "**"


def validate_owner_repo_pattern(pattern: str) -> tuple[str, str]:
    """Split ``pattern`` into ``(owner_glob, repo_glob)``, or raise ``UsageError``.

    Rules:
    - ``"**"`` is shorthand for ``("*", "*")`` (match everything).
    - Any other pattern must contain exactly one ``/``, with a non-empty glob
      on each side.
    """
    if pattern == MATCH_ALL_PATTERN:
        return "*", "*"

    if pattern.count("/") != 1:
        raise UsageError(
            f"Invalid owner/repo pattern '{pattern}'.",
            hint=(
                "Patterns must be 'owner/repo' with exactly one '/' "
                "(globs allowed on either side), e.g. 'myorg/*', 'owner/repo', "
                "or 'prefix-*/*'. Use '**' to match every repo in every "
                "reachable owner."
            ),
        )

    owner_glob, _, repo_glob = pattern.partition("/")
    if not owner_glob or not repo_glob:
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


def match_owner_repo(owner: str, repo: str, patterns: list[tuple[str, str]]) -> bool:
    """Return True if ``owner/repo`` matches any of the ``(owner_glob, repo_glob)`` pairs."""
    return any(fnmatch(owner, owner_glob) and fnmatch(repo, repo_glob) for owner_glob, repo_glob in patterns)
