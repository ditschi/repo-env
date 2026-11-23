"""Source-text helpers: code-line counting and inline suppressions."""

from __future__ import annotations

import ast
import io
import re
import tokenize

_NON_CODE_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}

# ``# code-health: ignore[kind-a, kind-b] -- reason why this is acceptable``
SUPPRESSION_RE = re.compile(r"#\s*code-health:\s*ignore\[([a-z0-9_,\- ]+)\]\s*(?:--|:)?\s*(.*)$")
MIN_REASON_LENGTH = 10


def code_lines(source: str) -> set[int]:
    """Return line numbers that contain code tokens (no blank/comment-only lines)."""
    lines: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type in _NON_CODE_TOKENS:
            continue
        lines.update(range(token.start[0], token.end[0] + 1))
    return lines


def docstring_lines(tree: ast.AST) -> set[int]:
    """Return line numbers occupied by module, class and function docstrings."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def parse_suppressions(source: str) -> tuple[dict[int, tuple[frozenset[str], str]], list[str]]:
    """Return ``{line: (kinds, reason)}`` plus warnings for suppressions without a reason."""
    found: dict[int, tuple[frozenset[str], str]] = {}
    warnings: list[str] = []
    for number, text in enumerate(source.splitlines(), start=1):
        match = SUPPRESSION_RE.search(text)
        if not match:
            continue
        kinds = frozenset(k.strip() for k in match.group(1).split(",") if k.strip())
        reason = match.group(2).strip()
        if len(reason) < MIN_REASON_LENGTH:
            warnings.append(
                f"L{number}: suppression ignored, a reason (>= {MIN_REASON_LENGTH} chars) is required"
            )
            continue
        found[number] = (kinds, reason)
    return found, warnings
