from __future__ import annotations

import os
import subprocess
import time

import pytest


@pytest.mark.performance
def test_help_cold_start_under_half_second() -> None:
    # Completion perf guard placeholder: check command cold-start budget.
    # Keep threshold conservative for CI stability.
    env = os.environ.copy()
    start = time.perf_counter()
    subprocess.run(["renv", "--help"], check=True, capture_output=True, text=True, env=env)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"CLI cold start too slow: {elapsed:.3f}s"
