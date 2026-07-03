"""Pure domain layer: models and logic with no IO."""

from __future__ import annotations

from repoenv.domain.models import (
    SCHEMA_VERSION,
    Environment,
    RepoEntry,
    RepoStatus,
    RunResult,
)
from repoenv.domain.selection import SetOp, resolve_selection, set_combine
from repoenv.domain.summary import RunSummary, aggregate_exit_code

__all__ = [
    "Environment",
    "RepoEntry",
    "RepoStatus",
    "RunResult",
    "RunSummary",
    "SCHEMA_VERSION",
    "SetOp",
    "aggregate_exit_code",
    "resolve_selection",
    "set_combine",
]
