"""``renv add`` — add repositories to an existing environment."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import PartialFailureError
from repoenv.services import environment_service
from repoenv.ui import console


def add_command(
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Directory of source clones."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    branch: Optional[str] = typer.Option(
        None, "--branch", "-b", help="Create and check out this new branch."
    ),
    on_branch_conflict: environment_service.BranchConflictStrategy = typer.Option(
        environment_service.BranchConflictStrategy.DETACH,
        "--on-branch-conflict",
        help="When the target branch is already checked out elsewhere: detach|move|fail.",
    ),
    preserve: bool = typer.Option(False, "--preserve", help="Skip fetch/update; use source repos as-is."),
    activate: bool = typer.Option(False, "--activate", help="Mark this environment as the default."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
    include_worktrees: bool = typer.Option(
        False,
        "--include-worktrees",
        help="Include git linked worktrees found under the source directory.",
    ),
) -> None:
    """Add repositories to an existing environment."""
    with state_store.registry_transaction() as registry:
        environment = resolve_environment(registry, env)
        if source is not None:
            environment.source = source.expanduser()

        plan = environment_service.build_add_plan(
            env=environment,
            include=include or None,
            exclude=exclude or None,
            include_worktrees=include_worktrees,
        )
        if plan.skipped_worktrees:
            console.print_info(
                f"Skipped {len(plan.skipped_worktrees)} git worktree(s) (use --include-worktrees to include)."
            )
        console.print_info(f"Add to '{environment.name}' ({len(plan.repos)}): {', '.join(plan.repos)}")

        active_set = registry.get_active() is not None

        if dry_run:
            console.print_info("Dry run: no changes made.")
        else:
            environment_service.execute_add_plan(
                environment,
                plan,
                branch=branch,
                preserve=preserve,
                on_branch_conflict=on_branch_conflict,
                on_repo_start=lambda repo, cur, tot: console.print_info(f"  [{cur}/{tot}] {repo}"),
            )
            registry.add(environment)
            if activate:
                registry.set_active(environment.name)
                active_set = True
            state_store.write_env_metadata(environment)

    if not activate and not active_set:
        console.print_info(f"Hint: run 'renv activate {environment.name}' to set it as the default.")

    if dry_run:
        return

    failed = environment_service.failed_repos(environment)
    if failed:
        raise PartialFailureError(
            f"Some repositories failed: {', '.join(failed)}.",
            hint="Run 'renv repair' or 'renv status' to see which worktrees are missing or failed.",
        )
    console.print_info(f"Added {len(plan.repos)} repository(ies) to '{environment.name}'.")
