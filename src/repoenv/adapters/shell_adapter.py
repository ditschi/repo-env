"""Shell adapter: run a command (argv-verbatim) in a worktree directory.

Exec by default (no ``shell=True``) so user commands are never re-parsed. The
``use_shell`` opt-in is reserved for callers that explicitly need pipes/globs.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


def run_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    use_shell: bool = False,
) -> tuple[int, str, str, float]:
    """Run ``argv`` in ``cwd`` and return (exit_code, stdout, stderr, duration_s)."""
    start = time.monotonic()
    if use_shell:
        command: str | list[str] = " ".join(argv)
    else:
        command = argv
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        shell=use_shell,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.monotonic() - start
    return proc.returncode, proc.stdout, proc.stderr, duration
