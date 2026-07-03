"""Typed exception hierarchy mapped to stable process exit codes.

Exit-code contract (from the safety spec):
    0  ok
    1  generic error
    2  usage error
    3  partial failure (some repos failed)
    4  nothing matched
    5  config / state error
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes. Do not renumber."""

    OK = 0
    GENERIC = 1
    USAGE = 2
    PARTIAL = 3
    NOTHING_MATCHED = 4
    CONFIG = 5


class RepoEnvError(Exception):
    """Base class for all repo-env errors.

    Carries an :class:`ExitCode` plus an optional user-facing ``hint`` that the
    UI layer renders as a "next step" line.
    """

    exit_code: ExitCode = ExitCode.GENERIC

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(RepoEnvError):
    """Invalid invocation / arguments."""

    exit_code = ExitCode.USAGE


class NothingMatchedError(RepoEnvError):
    """A selector or glob matched no repositories."""

    exit_code = ExitCode.NOTHING_MATCHED


class PartialFailureError(RepoEnvError):
    """Some repositories in a batch operation failed."""

    exit_code = ExitCode.PARTIAL


class ConfigError(RepoEnvError):
    """Configuration or persisted-state problem."""

    exit_code = ExitCode.CONFIG


class GitError(RepoEnvError):
    """A git subprocess failed."""

    exit_code = ExitCode.GENERIC
