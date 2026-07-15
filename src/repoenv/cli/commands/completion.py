"""``renv completion`` — print shell completion scripts.

Typer/Click already provide completion via ``--install-completion``; this
command exposes the raw script for a given shell so users can source it
manually or vendor it into their dotfiles.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from typer.completion import get_completion_script

from repoenv.errors import UsageError
from repoenv.ui import console

_SUPPORTED = ("bash", "zsh", "fish")


def _detect_shell() -> str:
    """Return the current shell name derived from $SHELL, or raise UsageError."""
    shell_path = os.environ.get("SHELL", "")
    name = Path(shell_path).name
    if name in _SUPPORTED:
        return name
    raise UsageError(
        f"Could not auto-detect a supported shell from $SHELL={shell_path!r}.",
        hint=f"Pass a shell explicitly: {', '.join(_SUPPORTED)}.",
    )


def completion_command(
    shell: Optional[str] = typer.Argument(
        None, help="Shell to generate completion for: bash|zsh|fish. Auto-detected from $SHELL when omitted."
    ),
) -> None:
    """Print a shell completion script to stdout.

    Usage (like ado-pipeline-manager):  eval "$(renv completion)"
    """
    resolved = shell or _detect_shell()
    if resolved not in _SUPPORTED:
        raise UsageError(f"Unsupported shell '{resolved}'.", hint=f"Choose one of: {', '.join(_SUPPORTED)}.")

    script = get_completion_script(
        prog_name="renv",
        complete_var="_RENV_COMPLETE",
        shell=resolved,
    )
    console.print_data(script)
