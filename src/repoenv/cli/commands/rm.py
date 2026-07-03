"""``renv rm`` — remove an environment (registry-only by default)."""

from __future__ import annotations

import shutil
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import UsageError
from repoenv.services import lifecycle_service
from repoenv.ui import console


def rm_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
    delete_files: bool = typer.Option(False, "--delete-files", help="Also remove worktrees and the env dir."),
    force: bool = typer.Option(False, "--force", help="Remove even if worktrees are dirty."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Remove an environment. Registry-only unless ``--delete-files``."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    dirty = lifecycle_service.check_dirty(environment)
    if dirty and not force:
        raise UsageError(
            f"Refusing to remove '{environment.name}': dirty worktrees: {', '.join(dirty)}.",
            hint="Commit/stash changes, or pass --force.",
        )

    console.print_info(f"Remove environment '{environment.name}' (delete_files={delete_files})")
    if dry_run:
        console.print_info("Dry run: no changes made.")
        return

    if delete_files:
        lifecycle_service.remove_worktrees(environment, force=force)
        if environment.path.exists():
            shutil.rmtree(environment.path, ignore_errors=True)

    registry.remove(environment.name)
    state_store.save_registry(registry)
    console.print_info(f"Removed environment '{environment.name}'.")
