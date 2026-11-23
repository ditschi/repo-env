"""Raw metrics from existing OSS tools: ruff, complexipy and pylint (duplicate-code)."""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - runs fixed, local developer tools
import sys
import threading
from collections import defaultdict
from pathlib import Path

from .config import Config
from .model import Finding

# ruff rule -> smell kind and the ruff option that carries our threshold.
RUFF_RULES = {
    "C901": ("complex-method", "lint.mccabe.max-complexity"),
    "PLR0913": ("many-arguments", "lint.pylint.max-args"),
    "PLR1702": ("nested-complexity", "lint.pylint.max-nested-blocks"),
}
_VALUE_RE = re.compile(r"\((\d+) > \d+\)")
_NAME_RE = re.compile(r"`([^`]+)`")
_DUPLICATE_RE = re.compile(r"^==(.+?):\[(\d+):(\d+)\]$", re.MULTILINE)


# complexipy's native extension is not thread-safe (observed segfaults); serialize calls.
_COMPLEXIPY_LOCK = threading.Lock()


class ToolError(RuntimeError):
    """An external analyzer is missing or failed."""


def _run(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)  # nosec B603
    if proc.returncode not in (0, 1) and not proc.stdout:
        raise ToolError(f"{' '.join(args[:3])} failed: {proc.stderr.strip()[:500]}")
    return proc.stdout


def ruff_findings(root: Path, files: list[str], config: Config) -> dict[str, list[Finding]]:
    """Cyclomatic complexity, argument count and nesting depth via ruff."""
    result: dict[str, list[Finding]] = defaultdict(list)
    if not files:
        return result
    args = [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--exit-zero"]
    args += ["--output-format", "json", "--target-version", "py310", "--select", ",".join(RUFF_RULES)]
    for kind, option in RUFF_RULES.values():
        args += ["--config", f"{option}={int(config.limit(kind))}"]
    for item in json.loads(_run([*args, *files], root) or "[]"):
        kind = RUFF_RULES[item["code"]][0]
        match = _VALUE_RE.search(item["message"])
        name = _NAME_RE.search(item["message"])
        value = float(match.group(1)) if match else config.limit(kind) + 1
        detail = f"{name.group(1)}: {int(value)}" if name else f"{int(value)}"
        path = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        result[path].append(Finding(kind, item["location"]["row"], value, detail))
    return result


def cognitive_findings(root: Path, files: list[str], config: Config) -> dict[str, list[Finding]]:
    """Cognitive complexity per function via complexipy."""
    try:
        import complexipy  # pylint: disable=import-outside-toplevel
    except ImportError as exc:  # pragma: no cover - environment problem
        raise ToolError("complexipy is not installed (pip install -e '.[code-quality]')") from exc
    limit = config.limit("cognitive-complexity")
    result: dict[str, list[Finding]] = defaultdict(list)
    for path in files:
        with _COMPLEXIPY_LOCK:
            functions = complexipy.file_complexity(str(root / path)).functions
        for func in functions:
            if func.complexity > limit:
                detail = f"{func.name}: {func.complexity}"
                result[path].append(Finding("cognitive-complexity", func.line_start, func.complexity, detail))
    return result


def duplicate_findings(root: Path, files: list[str], config: Config) -> dict[str, list[Finding]]:
    """Duplicated code blocks via pylint's similarity engine (``symilar``, same as R0801)."""
    result: dict[str, list[Finding]] = defaultdict(list)
    scoped = [f for f in files if config.paths.in_duplicate_scope(f)]
    if len(scoped) < 2:
        return result
    min_lines = int(config.limit("code-duplication")) + 1
    args = [sys.executable, "-m", "pylint.checkers.symilar", "-d", str(min_lines), "--ignore-comments"]
    args += ["--ignore-docstrings", "--ignore-imports", "--ignore-signatures"]
    for chunk in _run([*args, *scoped], root).split("\n\n"):
        blocks = _DUPLICATE_RE.findall(chunk)
        for path, start, end in blocks:
            others = ", ".join(p for p, *_ in blocks if p != path) or "same file"
            lines = int(end) - int(start)
            result[path].append(
                Finding("code-duplication", int(start) + 1, lines, f"{lines} lines also in {others}")
            )
    return result
