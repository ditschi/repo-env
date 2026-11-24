"""Collect raw findings for a source tree and turn them into scored file reports."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import external
from .ast_function import FunctionAnalyzer
from .ast_module import ModuleAnalyzer
from .ast_tests import assertion_findings
from .config import Config
from .model import FileFacts, FileReport, Finding, Smell, TreeReport
from .source import code_lines, docstring_lines, parse_suppressions


def discover(root: Path, config: Config) -> list[str]:
    """All Python files under the configured include paths, relative to ``root``."""
    found: set[str] = set()
    for entry in config.paths.include:
        base = root / entry
        candidates = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in candidates:
            rel = path.relative_to(root).as_posix()
            if path.suffix == ".py" and not config.paths.is_excluded(rel):
                found.add(rel)
    return sorted(found)


def file_facts(root: Path, path: str, config: Config) -> FileFacts:
    """Run all AST analyzers on one file."""
    source = (root / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    lines = code_lines(source) - docstring_lines(tree)
    limits = {kind: rule.limit for kind, rule in config.rules.items()}
    suppressions, warnings = parse_suppressions(source)
    for line, (kinds, _) in suppressions.items():
        warnings.extend(
            f"L{line}: unknown smell '{kind}' in suppression" for kind in sorted(kinds - set(config.rules))
        )
    facts = FileFacts(path=path, loc=len(lines), suppressions=suppressions)
    functions = FunctionAnalyzer(lines, config.cli_param_factories, limits)
    functions.is_test_module = config.paths.is_test(path)
    facts.functions, function_findings = functions.analyze(tree)
    facts.classes, module_findings = ModuleAnalyzer(lines, limits).analyze(tree, facts.loc)
    facts.findings = [*function_findings, *module_findings]
    if config.paths.is_test(path):
        facts.findings.extend(assertion_findings(tree, limits["large-assertion-block"]))
    facts.findings.extend(Finding("suppression", 0, 0, w) for w in warnings)
    return facts


def _external(root: Path, files: list[str], config: Config) -> list[dict[str, list[Finding]]]:
    runners = (external.ruff_findings, external.cognitive_findings, external.duplicate_findings)
    with ThreadPoolExecutor(max_workers=len(runners)) as pool:
        futures = [pool.submit(runner, root, files, config) for runner in runners]
        return [future.result() for future in futures]


def _drop_cli_arguments(facts: FileFacts, config: Config) -> None:
    """Do not count framework-declared CLI options as function arguments."""
    by_line = {f.line: f for f in facts.functions}
    limit = config.limit("many-arguments")
    kept = []
    for finding in facts.findings:
        func = by_line.get(finding.line)
        if finding.kind == "many-arguments" and func is not None:
            value = finding.value - func.cli_params
            if value <= limit:
                continue
            finding = Finding(finding.kind, finding.line, value, f"{func.name}: {int(value)} arguments")
        kept.append(finding)
    facts.findings = kept


def _derive_brain_smells(facts: FileFacts, config: Config) -> None:
    kinds_by_line: dict[int, set[str]] = {}
    for finding in facts.findings:
        kinds_by_line.setdefault(finding.line, set()).add(finding.kind)
    brain_lines = [
        line for line, kinds in kinds_by_line.items() if {"complex-method", "large-method"} <= kinds
    ]
    facts.findings.extend(Finding("brain-method", line, 1, "large and complex") for line in brain_lines)
    for cls in facts.classes:
        big = cls.methods >= 15 or cls.loc > 300
        if big and any(cls.line <= line <= cls.end_line for line in brain_lines):
            facts.findings.append(Finding("brain-class", cls.line, 1, f"{cls.name}: {cls.methods} methods"))


def _suppressed(facts: FileFacts, finding: Finding) -> bool:
    anchors = {finding.line, finding.line - 1}
    anchors.update(f.line for f in facts.functions if f.line <= finding.line <= f.end_line)
    for line in anchors:
        kinds, _ = facts.suppressions.get(line, (frozenset(), ""))
        if finding.kind in kinds:
            return True
    return False


def score_file(facts: FileFacts, config: Config) -> FileReport:
    """Apply suppressions and weights to the findings of one file."""
    report = FileReport(path=facts.path, loc=facts.loc, score=config.start)
    for finding in sorted(facts.findings, key=lambda f: (f.line, f.kind)):
        if finding.kind == "suppression":
            report.warnings.append(finding.detail)
            continue
        rule = config.rule(finding.kind)
        smell = Smell(
            finding.kind,
            finding.line,
            finding.value,
            rule.limit,
            finding.detail,
            rule.deduction(finding.value),
        )
        (report.suppressed if _suppressed(facts, finding) else report.smells).append(smell)
    deductions = sum(s.deduction for s in report.smells)
    report.score = max(config.minimum, config.start - deductions)
    return report


def analyze_tree(root: Path, config: Config) -> TreeReport:
    """Score every configured file below ``root``."""
    files = discover(root, config)
    facts = {path: file_facts(root, path, config) for path in files}
    for per_tool in _external(root, files, config):
        for path, findings in per_tool.items():
            if path in facts:
                facts[path].findings.extend(findings)
    for item in facts.values():
        _drop_cli_arguments(item, config)
        _derive_brain_smells(item, config)
    return TreeReport(files={path: score_file(item, config) for path, item in facts.items()})
