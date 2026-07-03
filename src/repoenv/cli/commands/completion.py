"""``renv completion`` — print shell completion scripts.

Typer/Click already provide completion via ``--install-completion``; this
command exposes the raw script for a given shell so users can source it
manually or vendor it into their dotfiles.
"""

from __future__ import annotations

import os
import subprocess
import sys

import typer

from repoenv.errors import UsageError
from repoenv.ui import console

_SUPPORTED = ("bash", "zsh", "fish")


def completion_command(
    shell: str = typer.Argument(..., help="Shell to generate completion for: bash|zsh|fish."),
) -> None:
    """Print a shell completion script to stdout."""
    if shell not in _SUPPORTED:
        raise UsageError(f"Unsupported shell '{shell}'.", hint=f"Choose one of: {', '.join(_SUPPORTED)}.")

    child_env = dict(os.environ)
    child_env["_RENV_COMPLETE"] = f"{shell}_source"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "repoenv"],
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    console.print_data(result.stdout.rstrip("\n"))
