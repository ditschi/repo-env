"""``renv add`` — add repositories to an existing environment."""

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.services import environment_service
from repoenv.ui import console


def add_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    branch: Optional[str] = typer.Option(
        None, "--branch", "-b", help="Create and check out this new branch."
    ),
    force: bool = typer.Option(False, "--force", help="Include repos with a dirty working tree."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Add repositories to an existing environment."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    plan = environment_service.build_add_plan(
        env=environment,
        include=include or None,
        exclude=exclude or None,
        force=force,
    )
    console.print_info(f"Add to '{environment.name}' ({len(plan.repos)}): {', '.join(plan.repos)}")
    if plan.skipped:
        for repo, reason in plan.skipped.items():
            console.print_info(f"  skip {repo}: {reason}")

    if dry_run:
        console.print_info("Dry run: no changes made.")
        return

    environment_service.execute_add_plan(environment, plan, branch=branch)
    registry.add(environment)
    state_store.save_registry(registry)
    state_store.write_env_metadata(environment)
    console.print_info(f"Added {len(plan.repos)} repository(ies) to '{environment.name}'.")
