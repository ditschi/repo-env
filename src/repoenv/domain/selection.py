"""Repository selection: glob include/exclude resolution and env set operations.

Pure functions only.  ``fnmatch`` gives shell-style globbing for simple patterns.
For patterns containing ``**``, we convert to a regex so that ``**`` matches
across path separators (like ``**`` in shell extended-glob and Python 3.12+
:meth:`pathlib.PurePath.full_match`).
"""

# aihealth: disable=primitive_obsession -- glob matching/set ops work on plain repo-name strings

from __future__ import annotations

import re
from collections.abc import Callable
from enum import Enum
from fnmatch import fnmatch


class SetOp(str, Enum):
    """Set operations for combining environments in ``merge``."""

    UNION = "union"
    INTERSECT = "intersect"
    DIFFERENCE = "difference"


def split_csv(values: list[str]) -> list[str]:
    """Flatten repeatable ``--flag a --flag b,c`` options into ``["a", "b", "c"]``.

    Every glob-taking option in the CLI (``--include``, ``--exclude``, and
    ``renv clone``'s ``--url``/``--include``/``--exclude``) accepts both a
    repeated flag and comma-separated values within one occurrence; this is
    the single place that flattening happens.
    """
    parts: list[str] = []
    for raw in values:
        for item in raw.split(","):
            trimmed = item.strip()
            if trimmed:
                parts.append(trimmed)
    return parts


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern (with ``**`` support) to a compiled regex.

    Rules:
    * ``**`` matches any sequence of characters including ``/`` — including
      zero characters so ``**/foo`` matches both ``foo`` and ``org/sub/foo``.
    * ``*``  matches any sequence of characters except ``/``.
    * ``?``  matches any single character except ``/``.
    * All other regex-special characters are escaped.
    """
    # Split on **; adjacent / around ** are stripped so "a/**/b", "**/b", and
    # "a/**" all produce clean segments to join.
    raw_segs = re.split(r"\*\*", pattern)
    last = len(raw_segs) - 1
    regex_segs = [
        _segment_to_regex(seg, strip_start=i > 0, strip_end=i < last) for i, seg in enumerate(raw_segs)
    ]
    # Between every pair of segments, "(?:.*/)?" allows zero or more path
    # components (the optional trailing slash keeps "org/" working too).
    body = "(?:.*/)?".join(regex_segs)
    return re.compile("^" + body + "$")


def _segment_to_regex(seg: str, *, strip_start: bool, strip_end: bool) -> str:
    """Translate one ``**``-free glob segment, trimming the ``/`` that touches a ``**``."""
    if strip_start and seg.startswith("/"):
        seg = seg[1:]
    if strip_end and seg.endswith("/"):
        seg = seg[:-1]
    return re.escape(seg).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")


def _match_pattern(name: str, pattern: str) -> bool:
    """Match *name* against *pattern*, supporting ``**`` multi-level globs."""
    if "**" in pattern:
        return bool(_glob_to_regex(pattern).match(name))
    return fnmatch(name, pattern)


def resolve_selection(
    candidates: list[str],
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Resolve a selection of names from ``candidates``.

    - ``include`` globs are OR-ed; if omitted, all candidates are included.
    - ``exclude`` globs are applied after include and take precedence.
    - Order is preserved from ``candidates``; duplicates are removed.
    - Patterns may contain ``**`` to match across path separators.
    - Comma-separated values within a single pattern string are split.
    """
    include = split_csv(include or ["*"])
    exclude = split_csv(exclude or [])

    seen: set[str] = set()
    result: list[str] = []
    for name in candidates:
        if name in seen:
            continue
        if not any(_match_pattern(name, pat) for pat in include):
            continue
        if any(_match_pattern(name, pat) for pat in exclude):
            continue
        seen.add(name)
        result.append(name)
    return result


def _union(left: list[str], right: list[str]) -> list[str]:
    left_set = set(left)
    return [*left, *(name for name in right if name not in left_set)]


def _intersect(left: list[str], right: list[str]) -> list[str]:
    right_set = set(right)
    return [name for name in left if name in right_set]


def _difference(left: list[str], right: list[str]) -> list[str]:
    right_set = set(right)
    return [name for name in left if name not in right_set]


_SET_OPERATIONS: dict[SetOp, Callable[[list[str], list[str]], list[str]]] = {
    SetOp.UNION: _union,
    SetOp.INTERSECT: _intersect,
    SetOp.DIFFERENCE: _difference,
}


def set_combine(left: list[str], right: list[str], op: SetOp) -> list[str]:
    """Combine two ordered name lists with a set operation, preserving order.

    Order follows ``left`` first, then any new names from ``right`` (for union).
    """
    operation = _SET_OPERATIONS.get(op)
    if operation is None:
        raise ValueError(f"unknown set operation: {op!r}")
    return operation(left, right)
