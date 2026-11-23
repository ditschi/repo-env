"""Function-level AST checks: large method, bumpy road, complex conditional, primitive obsession."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from .model import Finding, FunctionInfo

FunctionNode = (ast.FunctionDef, ast.AsyncFunctionDef)
_BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)
_WRAPPERS = (ast.With, ast.AsyncWith)
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes"})
BUMP_DEPTH = 2


def iter_functions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, FunctionNode):
            yield node


def _child_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    if isinstance(stmt, ast.Match):
        return [case.body for case in stmt.cases]
    bodies = [getattr(stmt, name, None) for name in ("body", "orelse", "finalbody")]
    result = [b for b in bodies if isinstance(b, list) and b and isinstance(b[0], ast.stmt)]
    result.extend(handler.body for handler in getattr(stmt, "handlers", []))
    return result


def branch_depth(stmt: ast.stmt) -> int:
    """Depth of branching statements (if/for/while/try/match) rooted at ``stmt``."""
    if isinstance(stmt, (*FunctionNode, ast.ClassDef)):
        return 0
    inner = max((branch_depth(s) for body in _child_bodies(stmt) for s in body), default=0)
    return inner + (1 if isinstance(stmt, _BRANCHING) else 0)


def count_bumps(body: list[ast.stmt]) -> int:
    """Count separate blocks nested >= BUMP_DEPTH deep, descending through single wrappers."""
    statements = body
    while len(statements) == 1 and isinstance(statements[0], (*_WRAPPERS, ast.Try)):
        statements = [s for b in _child_bodies(statements[0]) for s in b]
    return sum(1 for stmt in statements if branch_depth(stmt) >= BUMP_DEPTH)


def bool_operators(expr: ast.AST | None) -> int:
    """Number of ``and``/``or`` operators inside an expression."""
    if expr is None:
        return 0
    return sum(len(n.values) - 1 for n in ast.walk(expr) if isinstance(n, ast.BoolOp))


def walk_own(func: ast.AST) -> Iterator[ast.AST]:
    """Like ``ast.walk`` but without descending into nested functions or classes."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*FunctionNode, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def _conditions(func: ast.AST) -> Iterator[ast.expr]:
    for node in walk_own(func):
        if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
            yield node.test
        elif isinstance(node, ast.comprehension):
            yield from node.ifs
        elif isinstance(node, ast.match_case) and node.guard is not None:
            yield node.guard


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _is_cli_param(annotation: ast.expr | None, default: ast.expr | None, factories: frozenset[str]) -> bool:
    candidates: list[ast.AST] = [default] if default is not None else []
    if isinstance(annotation, ast.Subscript) and _dotted(annotation.value).endswith("Annotated"):
        slice_ = annotation.slice
        candidates.extend(slice_.elts[1:] if isinstance(slice_, ast.Tuple) else [])
    return any(isinstance(c, ast.Call) and _dotted(c.func) in factories for c in candidates)


def _is_primitive(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    names = {n.id for n in ast.walk(annotation) if isinstance(n, ast.Name)}
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        names = {part.strip() for part in annotation.value.replace("|", ",").split(",")}
    names -= {"None", "Optional"}
    return bool(names) and names <= _PRIMITIVES


def _params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.arg, ast.expr | None]]:
    args = func.args
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    pairs = list(zip(positional, defaults))
    pairs.extend(zip(args.kwonlyargs, args.kw_defaults))
    return [(a, d) for a, d in pairs if a.arg not in {"self", "cls"}]


def is_pytest_injected(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Test functions and fixtures receive their parameters from pytest."""
    if func.name.startswith("test"):
        return True
    return any(
        _dotted(d.func if isinstance(d, ast.Call) else d).endswith("fixture") for d in func.decorator_list
    )


class FunctionAnalyzer:
    """Collects function facts and AST-based function findings for one module."""

    def __init__(self, code_lines: set[int], factories: frozenset[str], limits: dict[str, float]) -> None:
        self._code_lines = code_lines
        self._factories = factories
        self._limits = limits
        self.is_test_module = False

    def analyze(self, tree: ast.AST) -> tuple[list[FunctionInfo], list[Finding]]:
        infos: list[FunctionInfo] = []
        findings: list[Finding] = []
        for func in iter_functions(tree):
            info = self._info(func)
            infos.append(info)
            findings.extend(self._findings(func, info))
        return infos, findings

    def _info(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
        end = func.end_lineno or func.lineno
        loc = sum(1 for n in range(func.lineno, end + 1) if n in self._code_lines)
        params = _params(func)
        injected = self.is_test_module and is_pytest_injected(func)
        cli = sum(1 for a, d in params if injected or _is_cli_param(a.annotation, d, self._factories))
        return FunctionInfo(name=func.name, line=func.lineno, end_line=end, loc=loc, cli_params=cli)

    def _findings(
        self, func: ast.FunctionDef | ast.AsyncFunctionDef, info: FunctionInfo
    ) -> Iterator[Finding]:
        if info.loc > self._limits["large-method"]:
            yield Finding("large-method", func.lineno, info.loc, f"{func.name}: {info.loc} lines")
        bumps = count_bumps(func.body)
        if bumps > self._limits["bumpy-road"]:
            yield Finding("bumpy-road", func.lineno, bumps, f"{func.name}: {bumps} bumps")
        primitives = sum(
            1
            for arg, default in _params(func)
            if _is_primitive(arg.annotation) and not _is_cli_param(arg.annotation, default, self._factories)
        )
        if primitives > self._limits["primitive-obsession"]:
            yield Finding(
                "primitive-obsession", func.lineno, primitives, f"{func.name}: {primitives} primitives"
            )
        yield from self._conditional_findings(func)

    def _conditional_findings(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[Finding]:
        for condition in _conditions(func):
            operators = bool_operators(condition)
            if operators > self._limits["complex-conditional"]:
                yield Finding(
                    "complex-conditional", condition.lineno, operators, f"{func.name}: {operators} operators"
                )
