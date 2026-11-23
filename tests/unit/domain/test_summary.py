from __future__ import annotations

from pathlib import Path

import pytest

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
    assert (summary.total, summary.succeeded, summary.failed, summary.skipped) == (3, 1, 1, 1)


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([], ExitCode.NOTHING_MATCHED),
        ([0, 0], ExitCode.OK),
        ([2], ExitCode.GENERIC),
        ([0, 2], ExitCode.PARTIAL),
    ],
)
def test_aggregate_exit_codes(codes: list[int], expected: ExitCode) -> None:
    results = [_result(f"repo{index}", code) for index, code in enumerate(codes)]
    assert aggregate_exit_code(results) == expected
