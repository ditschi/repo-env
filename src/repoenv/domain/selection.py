"""Repository selection: glob include/exclude resolution and env set operations.

Pure functions only.  ``fnmatch`` gives shell-style globbing for simple patterns.
For patterns containing ``**``, we convert to a regex so that ``**`` matches
across path separators (like ``**`` in shell extended-glob and Python 3.12+
:meth:`pathlib.PurePath.full_match`).
"""

from __future__ import annotations

import re
from enum import Enum
from fnmatch import fnmatch


class SetOp(str, Enum):
    """Set operations for combining environments in ``merge``."""

    UNION = "union"
    INTERSECT = "intersect"
    DIFFERENCE = "difference"


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
    regex_segs: list[str] = []
    for i, seg in enumerate(raw_segs):
        if i > 0 and seg.startswith("/"):
            seg = seg[1:]
        if i < len(raw_segs) - 1 and seg.endswith("/"):
            seg = seg[:-1]
        regex_segs.append(re.escape(seg).replace(r"\*", "[^/]*").replace(r"\?", "[^/]"))

    if len(regex_segs) == 1:
        body = regex_segs[0]
    else:
        # Between every pair of segments, "(?:.*/)?" allows zero or more path
        # components (the optional trailing slash keeps "org/" working too).
        body = regex_segs[0]
        for seg in regex_segs[1:]:
            body += "(?:.*/)?" + seg

    return re.compile("^" + body + "$")


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
    include = include or ["*"]
    exclude = exclude or []

    def _split_csv(values: list[str]) -> list[str]:
        parts: list[str] = []
        for raw in values:
            for item in raw.split(","):
                trimmed = item.strip()
                if trimmed:
                    parts.append(trimmed)
        return parts

    include = _split_csv(include)
    exclude = _split_csv(exclude)

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


def set_combine(left: list[str], right: list[str], op: SetOp) -> list[str]:
    """Combine two ordered name lists with a set operation, preserving order.

    Order follows ``left`` first, then any new names from ``right`` (for union).
    """
    right_set = set(right)
    left_set = set(left)

    if op is SetOp.UNION:
        ordered = list(left)
        ordered.extend(name for name in right if name not in left_set)
        return ordered
    if op is SetOp.INTERSECT:
        return [name for name in left if name in right_set]
    if op is SetOp.DIFFERENCE:
        return [name for name in left if name not in right_set]
    raise ValueError(f"unknown set operation: {op!r}")
