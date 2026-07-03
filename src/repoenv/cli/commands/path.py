"""``renv path`` — print an environment path to stdout for shell composition."""

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import NothingMatchedError
from repoenv.ui import console


def path_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
    repo: Optional[str] = typer.Option(None, "--repo", "-r", help="Print a single worktree path."),
) -> None:
    """Print an absolute path to stdout (for ``cd "$(renv path web)"``)."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    if repo is None:
        console.print_data(str(environment.path))
        return

    for entry in environment.repos:
        if entry.repo == repo:
            console.print_data(str(entry.worktree_path))
            return

    raise NothingMatchedError(
        f"Environment '{environment.name}' has no repo '{repo}'.",
        hint="Run 'renv ls --json' to see the repos in an environment.",
    )
