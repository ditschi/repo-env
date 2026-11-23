"""Load and validate ``code-health.toml``."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib  # type: ignore[import-not-found,no-redef,unused-ignore]

CONFIG_NAME = "code-health.toml"


@dataclass(frozen=True)
class SmellRule:
    """Threshold and weight of one smell kind."""

    limit: float
    weight: float
    cap: float

    def deduction(self, value: float) -> float:
        ratio = value / self.limit if self.limit else 1.0
        return self.weight * min(self.cap, ratio)


@dataclass(frozen=True)
class PathRules:
    """Which files are scored, which count as tests and which are compared for duplicates."""

    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    duplicate_scope: tuple[str, ...] = ()

    def is_test(self, path: str) -> bool:
        return any(fnmatch(path, pattern) for pattern in self.tests)

    def is_excluded(self, path: str) -> bool:
        return any(fnmatch(path, pattern) for pattern in self.exclude)

    def in_duplicate_scope(self, path: str) -> bool:
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in self.duplicate_scope)


@dataclass(frozen=True)
class Config:
    """Typed view of the TOML configuration."""

    start: float
    minimum: float
    target: float
    tolerance: float
    paths: PathRules
    baseline: str
    cli_param_factories: frozenset[str]
    rules: dict[str, SmellRule]

    def rule(self, kind: str) -> SmellRule:
        return self.rules[kind]

    def limit(self, kind: str) -> float:
        return self.rules[kind].limit


def load_config(path: Path) -> Config:
    """Parse the config file at ``path``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    score = data["score"]
    paths = data["paths"]
    rules = {
        kind: SmellRule(limit=float(raw["max"]), weight=float(raw["weight"]), cap=float(raw["cap"]))
        for kind, raw in data["smells"].items()
    }
    return Config(
        start=float(score["start"]),
        minimum=float(score["minimum"]),
        target=float(score["target"]),
        tolerance=float(score["tolerance"]),
        paths=PathRules(
            include=tuple(paths["include"]),
            exclude=tuple(paths.get("exclude", ())),
            tests=tuple(paths.get("tests", ())),
            duplicate_scope=tuple(paths.get("duplicate_scope", ())),
        ),
        baseline=str(paths["baseline"]),
        cli_param_factories=frozenset(data.get("cli", {}).get("param_factories", ())),
        rules=rules,
    )
