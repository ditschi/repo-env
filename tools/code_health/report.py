"""Human-readable table and JSON output."""

from __future__ import annotations

import json

from .config import Config
from .gate import GateResult
from .model import FileReport, TreeReport


def _smell_lines(report: FileReport) -> list[str]:
    lines = [
        f"      L{s.line:<5} {s.kind:<27} {s.detail} (max {s.limit:g}, -{s.deduction:.2f})"
        for s in report.smells
    ]
    lines.extend(f"      L{s.line:<5} {s.kind:<27} suppressed: {s.detail}" for s in report.suppressed)
    lines.extend(f"      warning: {w}" for w in report.warnings)
    return lines


def render_table(tree: TreeReport, config: Config, paths: list[str] | None, gate: GateResult | None) -> str:
    """Files sorted by score (worst first), each with its smells and line numbers."""
    selected = [tree.files[p] for p in paths] if paths is not None else list(tree.files.values())
    rows = sorted(
        (r for r in selected if r.smells or r.suppressed or r.warnings), key=lambda r: (r.score, r.path)
    )
    out = [f"{'Score':>6}  {'LOC':>5}  File", f"{'-' * 6}  {'-' * 5}  {'-' * 50}"]
    for report in rows:
        marker = "!" if report.score < config.target else " "
        out.append(f"{report.score:>5.2f}{marker}  {report.loc:>5}  {report.path}")
        out.extend(_smell_lines(report))
    healthy = len(selected) - len(rows)
    out.append(f"\n{len(selected)} file(s) shown, {healthy} without smells.")
    worst = tree.worst
    if worst is not None:
        summary = f"Repo score: {tree.repo_score:.2f} (target {config.target:g})"
        out.append(f"{summary}; worst: {worst.path} {worst.score:.2f}")
    if gate is not None:
        out.append(_gate_text(gate))
    return "\n".join(out)


def _gate_text(gate: GateResult) -> str:
    if gate.passed:
        return f"Gate: PASSED ({len(gate.checked)} file(s) checked)"
    return "Gate: FAILED\n" + "\n".join(f"  - {v}" for v in gate.violations)


def render_json(tree: TreeReport, config: Config, paths: list[str] | None, gate: GateResult | None) -> str:
    """Machine-readable output for agents and CI."""
    selected = paths if paths is not None else sorted(tree.files)
    worst = tree.worst
    payload = {
        "target": config.target,
        "repo_score": round(tree.repo_score, 2),
        "worst_file": {"path": worst.path, "score": round(worst.score, 2)} if worst else None,
        "files": [tree.files[p].to_dict() for p in selected],
        "gate": gate.to_dict() if gate else None,
    }
    return json.dumps(payload, indent=2)
