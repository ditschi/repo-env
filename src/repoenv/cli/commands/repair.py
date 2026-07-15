"""``renv repair`` — recreate missing or failed worktrees from registry metadata."""

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import PartialFailureError
from repoenv.services import environment_service, lifecycle_service
from repoenv.ui import console


def repair_command(
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to repair."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to skip."),
    on_branch_conflict: environment_service.BranchConflictStrategy = typer.Option(
        environment_service.BranchConflictStrategy.DETACH,
        "--on-branch-conflict",
        help="When the target branch is already checked out elsewhere: detach|move|fail.",
    ),
    preserve: bool = typer.Option(False, "--preserve", help="Skip fetch/update; use source repos as-is."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Recreate worktrees that are missing or marked failed/stale."""
    with state_store.registry_transaction() as registry:
        environment = resolve_environment(registry, env)
        candidates = lifecycle_service.list_repair_candidates(
            environment,
            include=include or None,
            exclude=exclude or None,
        )

        if not candidates:
            console.print_info(f"No worktrees need repair in '{environment.name}'.")
            return

        console.print_info(f"Repair candidates ({len(candidates)}): {', '.join(candidates)}")
        if dry_run:
            console.print_info("Dry run: no changes made.")
            return

        repaired, failed = lifecycle_service.repair_environment(
            environment,
            preserve=preserve,
            on_branch_conflict=on_branch_conflict,
            include=include or None,
            exclude=exclude or None,
        )
        registry.add(environment)
        state_store.write_env_metadata(environment)

    console.print_info(f"Repaired {len(repaired)} worktree(s) in '{environment.name}'.")
    if failed:
        raise PartialFailureError(
            f"Failed to repair: {', '.join(failed)}.",
            hint="Run 'renv status' for details, or remove stray directories blocking the path.",
        )
