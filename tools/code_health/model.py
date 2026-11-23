"""Data model shared by analyzers, scoring, gate and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    """A raw metric violation reported by one analyzer, before scoring."""

    kind: str
    line: int
    value: float
    detail: str = ""


@dataclass(frozen=True)
class Smell:
    """A scored finding: ``deduction`` is subtracted from the file score."""

    kind: str
    line: int
    value: float
    limit: float
    detail: str
    deduction: float

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "line": self.line,
            "value": self.value,
            "max": self.limit,
            "detail": self.detail,
            "deduction": round(self.deduction, 3),
        }


@dataclass(frozen=True)
class FunctionInfo:
    """Static facts about one function, used to merge findings of several tools."""

    name: str
    line: int
    end_line: int
    loc: int
    cli_params: int = 0


@dataclass(frozen=True)
class ClassInfo:
    """Static facts about one class (line range and method count)."""

    name: str
    line: int
    end_line: int
    loc: int
    methods: int


@dataclass
class FileFacts:
    """Everything the analyzers learned about one file."""

    path: str
    loc: int
    findings: list[Finding] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    suppressions: dict[int, tuple[frozenset[str], str]] = field(default_factory=dict)


@dataclass
class FileReport:
    """Final per-file result."""

    path: str
    loc: int
    score: float
    smells: list[Smell] = field(default_factory=list)
    suppressed: list[Smell] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "loc": self.loc,
            "score": round(self.score, 2),
            "smells": [s.to_dict() for s in self.smells],
            "suppressed": [s.to_dict() for s in self.suppressed],
            "warnings": self.warnings,
        }


@dataclass
class TreeReport:
    """Result for a whole source tree."""

    files: dict[str, FileReport]

    @property
    def repo_score(self) -> float:
        total_loc = sum(max(r.loc, 1) for r in self.files.values())
        if not total_loc:
            return 10.0
        return sum(r.score * max(r.loc, 1) for r in self.files.values()) / total_loc

    @property
    def worst(self) -> FileReport | None:
        return min(self.files.values(), key=lambda r: (r.score, r.path), default=None)
