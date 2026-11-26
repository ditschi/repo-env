"""``renv init`` — first-run setup wizard (also scriptable via flags)."""
# aihealth: disable=primitive_obsession, excess_arguments -- typer CLI boundary: every CLI option is a command parameter  # noqa: E501

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store
from repoenv.ui import console


@dataclass(frozen=True)
class _InitValues:
    """The defaults ``renv init`` writes (before ``None``-normalising the branch)."""

    source: Path | None
    dest: Path | None
    default_branch: str | None

    def with_fallback(self, existing: config_store.UserConfig) -> _InitValues:
        """Fill every value not given on the command line from the existing config."""
        return _InitValues(
            source=self.source if self.source is not None else existing.source,
            dest=self.dest if self.dest is not None else existing.dest,
            default_branch=self.default_branch
            if self.default_branch is not None
            else existing.default_branch,
        )


def _prompt_for_values(values: _InitValues) -> _InitValues:
    """Ask for each value (prefilled from *values*); exit with 130 when the user cancels."""
    try:
        return _InitValues(
            source=_ask_path("Source directory of clones", values.source or Path.cwd()),
            dest=_ask_path("Directory for environments", values.dest or Path.cwd() / "envs"),
            default_branch=_ask_text("Fallback default branch (blank = auto)", values.default_branch or ""),
        )
    except KeyboardInterrupt:
        console.print_info("Init aborted by user; config not changed.")
        raise typer.Exit(code=130) from None


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
    given = _InitValues(source=source, dest=dest, default_branch=default_branch)
    values = given.with_fallback(config_store.load_config())
    if interactive:
        values = _prompt_for_values(values)

    config = config_store.UserConfig(
        source=values.source,
        dest=values.dest,
        default_branch=values.default_branch or None,
        install_completion=install_completion,
    )
    written = config_store.save_config(config)
    console.print_info(f"Wrote config to {written}")


def _ask_path(prompt: str, default: Path) -> Path:
    import questionary

    answer = questionary.path(
        f"{prompt}:",
        default=str(default),
        only_directories=True,
    ).unsafe_ask()
    if answer is None:
        raise KeyboardInterrupt
    return Path(answer).expanduser() if answer else default


def _ask_text(prompt: str, default: str) -> str:
    import questionary

    answer = questionary.text(f"{prompt}:", default=default).unsafe_ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer if answer is not None else default
