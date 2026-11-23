"""Unit tests for the AST-based code health checks."""

from __future__ import annotations

import ast
import textwrap

import pytest

from tools.code_health.ast_function import FunctionAnalyzer, bool_operators, count_bumps
from tools.code_health.ast_module import lcom4
from tools.code_health.ast_tests import assertion_findings
from tools.code_health.source import code_lines, parse_suppressions

LIMITS = {"large-method": 70, "bumpy-road": 1, "primitive-obsession": 4, "complex-conditional": 3}


def _parse(code: str) -> ast.Module:
    return ast.parse(textwrap.dedent(code))


def _function(code: str) -> ast.FunctionDef:
    node = _parse(code).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _kinds(code: str, *, test_module: bool = False) -> list[str]:
    source = textwrap.dedent(code)
    analyzer = FunctionAnalyzer(code_lines(source), frozenset({"typer.Option"}), LIMITS)
    analyzer.is_test_module = test_module
    _, findings = analyzer.analyze(ast.parse(source))
    return [f.kind for f in findings]


BUMPY = """
def f(a, b):
    if a:
        for x in b:
            print(x)
    print("middle")
    while b:
        if a:
            break
"""

FLAT = """
def f(a, b):
    if a:
        print(a)
    for x in b:
        print(x)
"""

WRAPPED = """
def f(a, b):
    with open(a) as fh:
        if a:
            if b:
                print(fh)
        if b:
            for x in a:
                print(x)
"""


@pytest.mark.parametrize(("code", "bumps"), [(BUMPY, 2), (FLAT, 0), (WRAPPED, 2)])
def test_count_bumps(code: str, bumps: int) -> None:
    assert count_bumps(_function(code).body) == bumps


@pytest.mark.parametrize(("expr", "operators"), [("a and b", 1), ("a and (b or c) and d", 3), ("not a", 0)])
def test_bool_operators(expr: str, operators: int) -> None:
    assert bool_operators(ast.parse(expr, mode="eval").body) == operators


def test_complex_conditional_flags_four_operators() -> None:
    code = "def f(a, b, c, d, e):\n    if a and b and c or d and e:\n        return 1\n"
    assert "complex-conditional" in _kinds(code)


def test_primitive_obsession_ignores_cli_options() -> None:
    params = ", ".join(f"{name}: str = typer.Option('')" for name in "abcde")
    cli = f"def f({params}): ..."
    plain = "def f(a: str, b: int, c: str, d: bool, e: str | None): ..."
    assert (_kinds(cli), _kinds(plain)) == ([], ["primitive-obsession"])


def test_pytest_injected_params_are_counted_as_cli_params() -> None:
    source = "def test_x(a, b, c, d, e, f): ...\n"
    analyzer = FunctionAnalyzer(code_lines(source), frozenset(), LIMITS)
    analyzer.is_test_module = True
    infos, _ = analyzer.analyze(ast.parse(source))
    assert infos[0].cli_params == 6


COHESIVE = """
class A:
    def a(self):
        return self.x
    def b(self):
        return self.x + self.a()
    def c(self):
        return self.b()
    def d(self):
        self.x = 1
"""

SPLIT = """
class A:
    def a(self):
        return self.x
    def b(self):
        return self.y
    def c(self):
        return self.z
    @abstractmethod
    def d(self): ...
"""


@pytest.mark.parametrize(("code", "expected"), [(COHESIVE, (1, 4)), (SPLIT, (3, 3))])
def test_lcom4(code: str, expected: tuple[int, int]) -> None:
    cls = _parse(code).body[0]
    assert isinstance(cls, ast.ClassDef)
    assert lcom4(cls) == expected


ASSERTIONS = """
def test_one(x):
    assert x.a == 1
    assert x.b == 2
    assert x.c == 3
    assert x.d == 4

def test_two(x):
    x.run()
    assert x.a == 1
    assert x.b == 2
    assert x.c == 3
    assert x.d == 4
"""


def test_assertion_blocks_large_and_duplicated() -> None:
    kinds = sorted(f.kind for f in assertion_findings(_parse(ASSERTIONS), max_block=3))
    assert kinds == ["duplicated-assertion-block", "large-assertion-block", "large-assertion-block"]


def test_suppression_requires_reason() -> None:
    source = (
        "x = 1  # code-health: ignore[large-method] -- generated table, kept flat on purpose\n"
        "y = 2  # code-health: ignore[bumpy-road]\n"
    )
    found, warnings = parse_suppressions(source)
    assert (list(found), len(warnings)) == ([1], 1)


def test_suppression_inside_string_literal_is_not_a_comment() -> None:
    source = 'text = "# code-health: ignore[large-method]"\n'
    assert parse_suppressions(source) == ({}, [])
