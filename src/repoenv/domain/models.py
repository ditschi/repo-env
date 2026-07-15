"""Core domain models.

Identity fields use ``StrictStr`` so YAML/JSON coercions (the Norway problem,
``no`` -> ``False``, ``1.20`` -> ``1.2``) are rejected at the boundary rather
than silently mutating repo/branch/alias values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from repoenv.typing_compat import patch_typing_eval_type

SCHEMA_VERSION = 1

patch_typing_eval_type()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RepoStatus(str, Enum):
    """Per-repo state within an environment."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    STALE = "stale"
    PENDING = "pending"


class RepoEntry(BaseModel):
    """A single repository's worktree within an environment."""

    model_config = ConfigDict(extra="forbid")

    repo: StrictStr
    worktree_path: Path
    remote: StrictStr = StrictStr("origin")
    base: StrictStr
    branch: StrictStr
    branch_created: bool = False
    source_sha: StrictStr | None = None
    status: RepoStatus = RepoStatus.PENDING
    note: StrictStr | None = None


class Environment(BaseModel):
    """A named collection of git worktrees."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    name: StrictStr
    alias: StrictStr | None = None
    path: Path
    source: Path
    base_branch: StrictStr | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    repos: list[RepoEntry] = Field(default_factory=list)

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp in place."""
        self.updated_at = _utcnow()

    def repo_names(self) -> list[str]:
        """Return the repo names contained in this environment."""
        return [entry.repo for entry in self.repos]


class RunResult(BaseModel):
    """Outcome of running a command in one repository's worktree."""

    model_config = ConfigDict(extra="forbid")

    repo: StrictStr
    worktree_path: Path
    exit_code: int
    duration_s: float
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False

    @property
    def ok(self) -> bool:
        """True when the command succeeded (or the repo was skipped)."""
        return self.skipped or self.exit_code == 0
