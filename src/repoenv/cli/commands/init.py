"""``renv init`` — first-run setup wizard (also scriptable via flags)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store
from repoenv.ui import console


def init_command(
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Default directory of source clones."),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Default directory for environments."),
    default_branch: Optional[str] = typer.Option(None, "--default-branch", help="Fallback default branch."),
    install_completion: bool = typer.Option(
        False, "--install-completion", help="Record completion preference."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive: use flags/defaults, no prompts."),
) -> None:
    """Create the user config, prompting for anything not passed as a flag."""
    interactive = not yes and sys.stdin.isatty() and sys.stdout.isatty()

    resolved_source = source
    resolved_dest = dest
    resolved_branch = default_branch

    if interactive:
        resolved_source = resolved_source or _ask_path("Source directory of clones", Path.cwd())
        resolved_dest = resolved_dest or _ask_path("Directory for environments", Path.cwd() / "envs")
        resolved_branch = resolved_branch or _ask_text("Fallback default branch (blank = auto)", "")

    config = config_store.UserConfig(
        source=resolved_source,
        dest=resolved_dest,
        default_branch=resolved_branch or None,
        install_completion=install_completion,
    )
    written = config_store.save_config(config)
    console.print_info(f"Wrote config to {written}")


def _ask_path(prompt: str, default: Path) -> Path:
    import questionary

    answer = questionary.text(f"{prompt}:", default=str(default)).ask()
    return Path(answer).expanduser() if answer else default


def _ask_text(prompt: str, default: str) -> str:
    import questionary

    answer = questionary.text(f"{prompt}:", default=default).ask()
    return answer if answer is not None else default
