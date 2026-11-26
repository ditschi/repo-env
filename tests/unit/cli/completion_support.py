"""Shared helpers for exercising shell completion through the installed ``renv`` script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def bash_complete(*, repoenv_home: Path, cwd: Path, words: str) -> list[str]:
    """Run Click/Typer bash completion for the partial command line ``words``.

    ``words`` ends with a space, so the word being completed is the empty one
    after the last typed argument.
    """
    typed = words.split()
    args = typed[1:]
    cword = len(typed)
    renv_exe = shutil.which("renv")
    if renv_exe is None:
        pytest.fail("renv console script not on PATH; install the package first.")

    env = os.environ.copy()
    env["REPOENV_HOME"] = str(repoenv_home)
    env["_RENV_COMPLETE"] = "complete_bash"
    env["COMP_WORDS"] = words
    env["COMP_CWORD"] = str(cword)
    result = subprocess.run(
        [renv_exe, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]
