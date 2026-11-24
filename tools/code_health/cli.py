"""Command line entry point: ``code-health [--changed [BASE]] [--json] [--update-baseline]``."""

from __future__ import annotations

import argparse
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import gate as gate_mod
from .analyze import analyze_tree, discover
from .config import CONFIG_NAME, Config, load_config
from .external import ToolError
from .model import TreeReport
from .report import render_json, render_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-health", description="CodeScene-style code health score (1-10)."
    )
    parser.add_argument(
        "--changed",
        nargs="?",
        const="",
        default=None,
        metavar="BASE",
        help="only check files changed vs BASE (default: merge-base with origin/main, else HEAD)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--update-baseline", action="store_true", help="rewrite the ratchet baseline file")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)")
    parser.add_argument(
        "--config", type=Path, default=None, help=f"config file (default: <root>/{CONFIG_NAME})"
    )
    return parser


def _base_report(root: Path, base: str, config: Config) -> TreeReport:
    with tempfile.TemporaryDirectory(prefix="code-health-") as tmp:
        gate_mod.export_tree(root, base, Path(tmp), config)
        return analyze_tree(Path(tmp), config)


def _gate_input(args: argparse.Namespace, root: Path, config: Config) -> gate_mod.GateInput:
    """Analyze the working tree (and the base tree in parallel when ``--changed``)."""
    if args.update_baseline or args.changed is None:
        head = analyze_tree(root, config)
        if args.update_baseline:
            gate_mod.write_baseline(root / config.baseline, head, config)
    baseline = gate_mod.load_baseline(root / config.baseline)
    if args.changed is None:
        return gate_mod.GateInput(head, sorted(head.files), baseline)
    base = gate_mod.resolve_base(root, args.changed or None)
    files, renames = gate_mod.changed_files(root, base, set(discover(root, config)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        base_future = pool.submit(_base_report, root, base, config) if files else None
        head = analyze_tree(root, config)
        base_report = base_future.result() if base_future else None
    return gate_mod.GateInput(head, files, baseline, base_report, renames)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        config = load_config(args.config or root / CONFIG_NAME)
        gate = _gate_input(args, root, config)
        result = gate_mod.evaluate(gate, config)
    except (ToolError, RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"code-health: {exc}", file=sys.stderr)
        return 2
    paths = result.checked if args.changed is not None else None
    render = render_json if args.json else render_table
    print(render(gate.head, config, paths, result))
    return 0 if result.passed else 1
