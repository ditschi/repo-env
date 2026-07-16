"""Repository selection: glob include/exclude resolution and env set operations.

Pure functions only. ``fnmatch`` gives shell-style globbing that matches the
UX users expect from ``rsync --exclude`` and shell wildcards.
"""

from __future__ import annotations

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
    """
    include = split_csv(include or ["*"])
    exclude = split_csv(exclude or [])

    seen: set[str] = set()
    result: list[str] = []
    for name in candidates:
        if name in seen:
            continue
        if not any(fnmatch(name, pat) for pat in include):
            continue
        if any(fnmatch(name, pat) for pat in exclude):
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
