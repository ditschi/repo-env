from __future__ import annotations

from pathlib import Path

from repoenv.domain.models import RunResult
from repoenv.domain.summary import RunSummary, aggregate_exit_code
from repoenv.errors import ExitCode


def _result(repo: str, code: int, skipped: bool = False) -> RunResult:
    return RunResult(
        repo=repo,
        worktree_path=Path(f"/tmp/{repo}"),
        exit_code=code,
        duration_s=0.1,
        skipped=skipped,
    )


def test_summary_counts() -> None:
    results = [_result("a", 0), _result("b", 1), _result("c", 0, skipped=True)]
    summary = RunSummary.from_results(results)
    assert summary.total == 3
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.skipped == 1


def test_aggregate_exit_codes() -> None:
    assert aggregate_exit_code([]) == ExitCode.NOTHING_MATCHED
    assert aggregate_exit_code([_result("a", 0), _result("b", 0)]) == ExitCode.OK
    assert aggregate_exit_code([_result("a", 2)]) == ExitCode.GENERIC
    assert aggregate_exit_code([_result("a", 0), _result("b", 2)]) == ExitCode.PARTIAL
