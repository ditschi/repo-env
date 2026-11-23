"""Test-specific AST checks: large and duplicated assertion blocks."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from .ast_function import iter_functions
from .model import Finding

DUPLICATE_MIN_ASSERTIONS = 3


def is_assertion(stmt: ast.stmt) -> bool:
    """``assert ...`` or a call like ``mock.assert_called_once_with(...)``."""
    if isinstance(stmt, ast.Assert):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name.startswith("assert")
    return False


def _bodies(node: ast.AST) -> Iterator[list[ast.stmt]]:
    for child in ast.walk(node):
        for name in ("body", "orelse", "finalbody"):
            body = getattr(child, name, None)
            if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
                yield body


def assertion_runs(func: ast.AST) -> Iterator[list[ast.stmt]]:
    """Yield maximal runs of consecutive assertion statements."""
    for body in _bodies(func):
        run: list[ast.stmt] = []
        for stmt in [*body, None]:
            if stmt is not None and is_assertion(stmt):
                run.append(stmt)
                continue
            if run:
                yield run
            run = []


def _key(run: list[ast.stmt]) -> str:
    return "\n".join(ast.dump(stmt, include_attributes=False) for stmt in run)


def assertion_findings(tree: ast.AST, max_block: float) -> list[Finding]:
    """Large blocks (> ``max_block`` assertions) and repeated identical blocks."""
    findings: list[Finding] = []
    seen: dict[str, int] = {}
    for func in iter_functions(tree):
        if not func.name.startswith("test"):
            continue
        for run in assertion_runs(func):
            if len(run) > max_block:
                findings.append(Finding("large-assertion-block", run[0].lineno, len(run), f"{func.name}"))
            if len(run) < DUPLICATE_MIN_ASSERTIONS:
                continue
            first = seen.setdefault(_key(run), run[0].lineno)
            if first != run[0].lineno:
                detail = f"{func.name}: same {len(run)} assertions as L{first}"
                findings.append(Finding("duplicated-assertion-block", run[0].lineno, 1, detail))
    return findings
