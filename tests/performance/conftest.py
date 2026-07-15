"""Shared helpers for CLI cold-start performance budgets."""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

# Median over several fresh subprocesses damps runner noise without hiding regressions.
SAMPLES = 5

# Conservative budgets for shared CI runners (local medians are typically ~0.3s).
HELP_BUDGET_S = 1.0
COMPLETION_COMMAND_BUDGET_S = 1.0
COMPLETION_ENV_BUDGET_S = 1.2


@pytest.fixture(scope="session")
def renv_exe() -> str:
    """Console script used for subprocess cold-start measurements."""
    exe = shutil.which("renv")
    if exe is None:
        pytest.fail("renv console script not on PATH; install the package first (nox -s performance).")
    return exe


@pytest.fixture()
def isolated_home(tmp_path: Path) -> Path:
    """Empty REPOENV_HOME for hermetic subprocess invocations."""
    home = tmp_path / "repoenv-home"
    home.mkdir()
    return home


def subprocess_env(*, home: Path | None = None, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build an environment dict for a fresh ``renv`` subprocess."""
    env = os.environ.copy()
    if home is not None:
        env["REPOENV_HOME"] = str(home)
    if extra:
        env.update(extra)
    return env


def median_cold_start(
    renv_exe: str,
    args: list[str],
    *,
    env: Mapping[str, str],
    samples: int = SAMPLES,
) -> float:
    """Return the median wall time over ``samples`` fresh ``renv`` subprocesses."""
    elapsed: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        subprocess.run([renv_exe, *args], check=False, capture_output=True, text=True, env=dict(env))
        elapsed.append(time.perf_counter() - start)
    return statistics.median(elapsed)


def bash_completion_env(*, words: str, cword: int) -> dict[str, str]:
    """Environment for Click/Typer bash shell completion (``_RENV_COMPLETE``)."""
    return {
        "_RENV_COMPLETE": "complete_bash",
        "COMP_WORDS": words,
        "COMP_CWORD": str(cword),
    }
