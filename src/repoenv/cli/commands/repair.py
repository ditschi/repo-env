"""``renv repair`` — recreate missing or failed worktrees from registry metadata."""
# aihealth: disable=excess_arguments -- typer CLI boundary: every CLI option is a command parameter

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli import options as cli_options
from repoenv.cli.resolve import resolve_environment
from repoenv.cli.worktree_reporting import expand_selection
from repoenv.errors import PartialFailureError
from repoenv.services import environment_service, lifecycle_service
from repoenv.ui import console


def repair_command(
    env: Optional[str] = cli_options.env_argument(),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to repair."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to skip."),
    on_branch_conflict: environment_service.BranchConflictStrategy = cli_options.on_branch_conflict_option(),
    preserve: bool = cli_options.preserve_option(),
    dry_run: bool = cli_options.dry_run_option(),
) -> None:
    """Recreate worktrees that are missing or marked failed/stale."""
    include, exclude = expand_selection(include, exclude)

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
            options=environment_service.ExecuteOptions(
                preserve=preserve, on_branch_conflict=on_branch_conflict
            ),
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
