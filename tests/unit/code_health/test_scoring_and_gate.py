"""Unit tests for scoring, the gate and the CLI of the code health checker."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.code_health.analyze import score_file
from tools.code_health.cli import main
from tools.code_health.config import Config, PathRules, SmellRule, load_config
from tools.code_health.external import ToolError, _run
from tools.code_health.gate import Baseline, GateInput, evaluate
from tools.code_health.model import FileFacts, FileReport, Finding, FunctionInfo, TreeReport

REPO_CONFIG = Path(__file__).resolve().parents[3] / "code-health.toml"


def _config() -> Config:
    return Config(
        start=10.0,
        minimum=1.0,
        target=9.5,
        tolerance=0.005,
        paths=PathRules(include=("src",)),
        baseline="baseline.json",
        cli_param_factories=frozenset(),
        rules={"complex-method": SmellRule(limit=9, weight=0.6, cap=3.0)},
    )


def _tree(**scores: float) -> TreeReport:
    return TreeReport(
        files={p.replace("_", "/"): FileReport(p.replace("_", "/"), 100, s) for p, s in scores.items()}
    )


def test_score_applies_weight_cap_and_minimum() -> None:
    facts = FileFacts(
        path="a.py", loc=10, findings=[Finding("complex-method", 3, 18), Finding("complex-method", 9, 900)]
    )
    report = score_file(facts, _config())
    assert round(report.score, 2) == round(10 - 0.6 * 2 - 0.6 * 3, 2)


def test_inline_suppression_on_def_line_moves_smell_aside() -> None:
    facts = FileFacts(path="a.py", loc=10, findings=[Finding("complex-method", 4, 12)])
    facts.functions = [FunctionInfo("f", 2, 9, 8)]
    facts.suppressions = {2: (frozenset({"complex-method"}), "parser table, splitting hurts readability")}
    report = score_file(facts, _config())
    assert (report.score, len(report.suppressed)) == (10.0, 1)


def test_repo_score_is_loc_weighted() -> None:
    tree = TreeReport(files={"a": FileReport("a", 300, 10.0), "b": FileReport("b", 100, 6.0)})
    assert (tree.repo_score, tree.worst and tree.worst.path) == (9.0, "b")


@pytest.mark.parametrize(
    ("head", "base", "baseline", "violations"),
    [
        ({"src_a": 9.8}, {"src_a": 9.6}, {}, 0),
        ({"src_a": 9.2}, None, {}, 1),
        ({"src_a": 7.0}, {"src_a": 7.0}, {"src/a": 7.0}, 0),
        ({"src_a": 6.9}, {"src_a": 7.0}, {"src/a": 7.0}, 3),
        ({"src_a": 9.7}, {"src_a": 9.9}, {}, 1),  # worse file; repo still >= target
    ],
)
def test_gate(head: dict, base: dict | None, baseline: dict, violations: int) -> None:
    gate = GateInput(_tree(**head), ["src/a"], Baseline(files=baseline), _tree(**base) if base else None)
    assert len(evaluate(gate, _config()).violations) == violations


def test_repo_config_loads_every_smell() -> None:
    config = load_config(REPO_CONFIG)
    assert {"complex-method", "bumpy-road", "low-cohesion", "duplicated-assertion-block"} <= set(config.rules)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_changed_detects_regression(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(REPO_CONFIG, tmp_path / "code-health.toml")
    (tmp_path / "src").mkdir()
    module = tmp_path / "src" / "mod.py"
    module.write_text("def f(a):\n    return a\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    branches = "".join(f"    if a == {i}:\n        return {i}\n" for i in range(12))
    module.write_text(textwrap.dedent("def f(a):\n") + branches + "    return a\n")
    code = main(["--root", str(tmp_path), "--changed", "HEAD", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert (code, payload["gate"]["passed"], payload["files"][0]["smells"][0]["kind"]) == (
        1,
        False,
        "complex-method",
    )


def test_repo_may_dip_while_staying_at_target() -> None:
    base = _tree(src_a=10.0, src_b=10.0)
    head = _tree(src_a=10.0, src_b=10.0, src_c=9.6)
    gate = GateInput(head, ["src/c"], Baseline(), base)
    assert evaluate(gate, _config()).passed


def test_renamed_file_is_compared_with_its_old_path() -> None:
    gate = GateInput(_tree(src_new=9.6), ["src/new"], Baseline(), _tree(src_old=9.9), {"src/new": "src/old"})
    assert [v for v in evaluate(gate, _config()).violations if "got worse" in v] == [
        "src/new: got worse (9.90 -> 9.60)"
    ]


def test_missing_analyzer_module_is_a_tool_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError):
        _run([sys.executable, "-m", "no_such_module_for_code_health"], tmp_path)
