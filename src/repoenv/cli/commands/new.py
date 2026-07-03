"""``renv new`` — create an environment from repos matching a selection."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store, state_store
from repoenv.errors import UsageError
from repoenv.services import environment_service
from repoenv.ui import console


def new_command(
    name: str = typer.Argument(..., help="Name of the environment to create."),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Directory of source clones."),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Where the environment dir is created."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    branch: Optional[str] = typer.Option(
        None, "--branch", "-b", help="Create and check out this new branch."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Short alias for the environment."),
    force: bool = typer.Option(False, "--force", help="Include repos with a dirty working tree."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Create a new environment of git worktrees."""
    config = config_store.load_config()
    resolved_source = source or config.source
    resolved_dest = dest or config.dest
    if resolved_source is None:
        raise UsageError("No --source given and no default configured. Run 'renv init' first.")
    if resolved_dest is None:
        raise UsageError("No --dest given and no default configured. Run 'renv init' first.")

    registry = state_store.load_registry()
    if name in registry:
        raise UsageError(f"Environment '{name}' already exists.", hint="Use 'renv add' to extend it.")

    plan = environment_service.build_create_plan(
        name=name,
        source=resolved_source,
        dest=resolved_dest,
        include=include or None,
        exclude=exclude or None,
        branch=branch,
        alias=alias,
        default_branch=config.default_branch,
        force=force,
    )

    console.print_info(f"Environment '{name}' -> {plan.env_path}")
    console.print_info(f"Repositories ({len(plan.repos)}): {', '.join(plan.repos)}")
    if plan.skipped:
        for repo, reason in plan.skipped.items():
            console.print_info(f"  skip {repo}: {reason}")

    if dry_run:
        console.print_info("Dry run: no changes made.")
        return

    env = environment_service.execute_create_plan(plan)
    registry.add(env)
    state_store.save_registry(registry)
    state_store.write_env_metadata(env)
    console.print_info(f"Created environment '{name}' with {len(env.repos)} worktree(s).")
