"""Module-level AST checks: large file, many functions, low cohesion (LCOM4) per class."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from .ast_function import FunctionNode, iter_functions, walk_own
from .model import ClassInfo, Finding

LCOM_MIN_METHODS = 4


def _self_usage(method: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[set[str], set[str]]:
    """Return (attributes accessed on ``self``, methods called on ``self``)."""
    attrs: set[str] = set()
    calls: set[str] = set()
    for node in walk_own(method):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            attrs.add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func
            if isinstance(target.value, ast.Name) and target.value.id == "self":
                calls.add(target.attr)
    return attrs, calls


def _find(parent: dict[str, str], item: str) -> str:
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _is_abstract(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    names = {getattr(d, "attr", getattr(d, "id", "")) for d in method.decorator_list}
    return "abstractmethod" in names or "overload" in names


def _counts_for_cohesion(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not method.name.startswith("__") and not _is_abstract(method)


def lcom4(cls: ast.ClassDef) -> tuple[int, int]:
    """Return (LCOM4, number of methods considered) for a class.

    Methods are connected when they share an attribute of ``self`` or when one
    calls the other; dunder methods are ignored. LCOM4 is the number of
    connected components.
    """
    methods = [m for m in cls.body if isinstance(m, FunctionNode) and _counts_for_cohesion(m)]
    names = {m.name for m in methods}
    parent = {m.name: m.name for m in methods}
    owners: dict[str, str] = {}
    for method in methods:
        attrs, calls = _self_usage(method)
        for other in (calls | (attrs & names)) & names:
            parent[_find(parent, method.name)] = _find(parent, other)
        for attr in attrs - names:
            if attr in owners:
                parent[_find(parent, method.name)] = _find(parent, owners[attr])
            owners.setdefault(attr, method.name)
    return len({_find(parent, name) for name in names}), len(methods)


class ModuleAnalyzer:
    """Collects class facts and module-level findings for one module."""

    def __init__(self, code_lines: set[int], limits: dict[str, float]) -> None:
        self._code_lines = code_lines
        self._limits = limits

    def analyze(self, tree: ast.Module, loc: int) -> tuple[list[ClassInfo], list[Finding]]:
        findings = list(self._module_findings(tree, loc))
        classes: list[ClassInfo] = []
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            classes.append(self._class_info(cls))
            findings.extend(self._cohesion(cls))
        return classes, findings

    def _module_findings(self, tree: ast.Module, loc: int) -> Iterator[Finding]:
        if loc > self._limits["large-file"]:
            yield Finding("large-file", 1, loc, f"{loc} code lines")
        functions = sum(1 for _ in iter_functions(tree))
        if functions > self._limits["many-functions"]:
            yield Finding("many-functions", 1, functions, f"{functions} functions")

    def _class_info(self, cls: ast.ClassDef) -> ClassInfo:
        end = cls.end_lineno or cls.lineno
        loc = sum(1 for n in range(cls.lineno, end + 1) if n in self._code_lines)
        methods = sum(1 for n in cls.body if isinstance(n, FunctionNode))
        return ClassInfo(name=cls.name, line=cls.lineno, end_line=end, loc=loc, methods=methods)

    def _cohesion(self, cls: ast.ClassDef) -> Iterator[Finding]:
        value, methods = lcom4(cls)
        if methods >= LCOM_MIN_METHODS and value > self._limits["low-cohesion"]:
            yield Finding("low-cohesion", cls.lineno, value, f"{cls.name}: LCOM4 {value} ({methods} methods)")
