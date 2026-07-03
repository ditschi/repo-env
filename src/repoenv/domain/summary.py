"""Run-result aggregation and exit-code mapping."""

from __future__ import annotations

from dataclasses import dataclass

from repoenv.domain.models import RunResult
from repoenv.errors import ExitCode


@dataclass(frozen=True)
class RunSummary:
    """Aggregate counts for a batch run."""

    total: int
    succeeded: int
    failed: int
    skipped: int

    @classmethod
    def from_results(cls, results: list[RunResult]) -> "RunSummary":
        """Build a summary from per-repo results."""
        succeeded = sum(1 for r in results if not r.skipped and r.exit_code == 0)
        failed = sum(1 for r in results if not r.skipped and r.exit_code != 0)
        skipped = sum(1 for r in results if r.skipped)
        return cls(total=len(results), succeeded=succeeded, failed=failed, skipped=skipped)


def aggregate_exit_code(results: list[RunResult]) -> ExitCode:
    """Map a batch of results to a single process exit code.

    - no results          -> NOTHING_MATCHED
    - all ok/skipped       -> OK
    - some ok, some failed -> PARTIAL
    - all failed           -> GENERIC
    """
    if not results:
        return ExitCode.NOTHING_MATCHED

    summary = RunSummary.from_results(results)
    if summary.failed == 0:
        return ExitCode.OK
    if summary.succeeded == 0 and summary.skipped == 0:
        return ExitCode.GENERIC
    return ExitCode.PARTIAL
