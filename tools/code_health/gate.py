"""Quality gate: changed files, comparison with a git base and the ratchet baseline."""

from __future__ import annotations

import io
import json
import subprocess  # nosec B404 - runs git only
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .model import TreeReport

DEFAULT_BASES = ("origin/main", "main")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )  # nosec B603 B607
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def resolve_base(root: Path, base: str | None) -> str:
    """Use ``base`` or the merge-base with the default branch (falls back to HEAD)."""
    if base:
        return _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    for candidate in DEFAULT_BASES:
        try:
            return _git(root, "merge-base", "HEAD", candidate).strip()
        except RuntimeError:
            continue
    return _git(root, "rev-parse", "HEAD").strip()


def changed_files(root: Path, base: str, scored: set[str]) -> list[str]:
    """Scored files that differ from ``base`` in the working tree (incl. untracked)."""
    diff = _git(root, "diff", "--name-only", "--diff-filter=ACMR", base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path for path in (*diff, *untracked) if path in scored})


def export_tree(root: Path, base: str, target: Path, config: Config) -> None:
    """Write the configured paths of commit ``base`` into ``target``."""
    names = set(_git(root, "ls-tree", "--name-only", base).splitlines())
    paths = [p for p in config.paths.include if p.split("/")[0] in names]
    archive = subprocess.run(  # nosec B603 B607
        ["git", "archive", "--format=tar", base, *paths], cwd=root, capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(target)
    (target / Path(config.baseline).name).unlink(missing_ok=True)


@dataclass(frozen=True)
class Baseline:
    """Grandfathered file scores and the repo score recorded with them."""

    files: dict[str, float] = field(default_factory=dict)
    repo_score: float = 1.0


def load_baseline(path: Path) -> Baseline:
    if not path.exists():
        return Baseline()
    data = json.loads(path.read_text(encoding="utf-8"))
    files = {str(k): float(v) for k, v in data.get("files", {}).items()}
    return Baseline(files=files, repo_score=float(data.get("repo_score", 1.0)))


def write_baseline(path: Path, report: TreeReport, config: Config) -> None:
    """Grandfather every file below target with its current score."""
    files = {p: round(r.score, 2) for p, r in sorted(report.files.items()) if r.score < config.target}
    payload = {
        "comment": "Ratchet baseline for `nox -s code-health` (regenerate with --update-baseline); "
        "scores may only go up.",
        "repo_score": round(report.repo_score, 2),
        "files": files,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass
class GateResult:
    """Outcome of a gate evaluation."""

    checked: list[str]
    violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "checked": self.checked, "violations": self.violations}


@dataclass(frozen=True)
class GateInput:
    """Everything the gate compares: current tree, optional base tree and baseline."""

    head: TreeReport
    files: list[str]
    baseline: Baseline
    base: TreeReport | None = None


def evaluate(gate: GateInput, config: Config) -> GateResult:
    """Each checked file must reach target (or its baseline) and not get worse; repo must not drop."""
    result = GateResult(checked=gate.files)
    tol = config.tolerance
    for path in gate.files:
        score = gate.head.files[path].score
        floor = min(config.target, gate.baseline.files.get(path, config.target))
        if score < floor - tol:
            result.violations.append(f"{path}: {score:.2f} < required {floor:.2f}")
        previous = gate.base.files.get(path) if gate.base else None
        if previous is not None and score < previous.score - tol:
            result.violations.append(f"{path}: got worse ({previous.score:.2f} -> {score:.2f})")
    reference = gate.base.repo_score if gate.base is not None else gate.baseline.repo_score
    if gate.head.repo_score < reference - tol:
        result.violations.append(f"repo score dropped ({reference:.2f} -> {gate.head.repo_score:.2f})")
    return result
