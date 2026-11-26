"""``renv add`` — add repositories to an existing environment."""
# aihealth: disable=primitive_obsession, excess_arguments -- typer CLI boundary: every CLI option is a command parameter  # noqa: E501

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli import options as cli_options
from repoenv.cli.resolve import resolve_environment
from repoenv.cli.worktree_reporting import (
    expand_selection,
    print_activate_hint,
    print_progress,
    print_skipped_worktrees,
    raise_on_failures,
)
from repoenv.domain.models import Environment
from repoenv.services import environment_service
from repoenv.ui import console


def _print_add_plan(environment: Environment, plan: environment_service.AddPlan) -> None:
    print_skipped_worktrees(plan.skipped_worktrees)
    console.print_info(f"Add to '{environment.name}' ({len(plan.repos)}): {', '.join(plan.repos)}")


def _effective_branch(branch: str | None, environment: Environment) -> str | None:
    """Return *branch*, or the task branch the environment already uses when none was given."""
    if branch is not None:
        return branch
    inferred = environment_service.infer_env_branch(environment)
    if inferred is not None:
        console.print_info(f"No --branch given; joining existing task branch '{inferred}'.")
    return inferred


def add_command(
    env: Optional[str] = cli_options.env_argument(),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Directory of source clones."),
    include: list[str] = cli_options.include_option(),
    exclude: list[str] = cli_options.exclude_option(),
    branch: Optional[str] = cli_options.branch_option(),
    on_branch_conflict: environment_service.BranchConflictStrategy = cli_options.on_branch_conflict_option(),
    preserve: bool = cli_options.preserve_option(),
    activate: bool = cli_options.activate_option(),
    dry_run: bool = cli_options.dry_run_option(),
    include_worktrees: bool = cli_options.include_worktrees_option(),
) -> None:
    """Add repositories to an existing environment."""
    include, exclude = expand_selection(include, exclude)

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
        _print_add_plan(environment, plan)
        effective_branch = _effective_branch(branch, environment)
        active_set = registry.get_active() is not None

        if dry_run:
            console.print_info("Dry run: no changes made.")
        else:
            options = environment_service.ExecuteOptions(
                preserve=preserve, on_branch_conflict=on_branch_conflict, on_repo_start=print_progress
            )
            environment_service.execute_add_plan(environment, plan, branch=effective_branch, options=options)
            registry.add(environment)
            if activate:
                registry.set_active(environment.name)
            state_store.write_env_metadata(environment)

    print_activate_hint(environment.name, activate=activate, active_set=active_set)
    if dry_run:
        return

    raise_on_failures(environment)
    console.print_info(f"Added {len(plan.repos)} repository(ies) to '{environment.name}'.")
