"""``renv rm`` — remove an environment (delete files by default)."""
# aihealth: disable=excess_arguments -- typer CLI boundary: options are parameters

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli import options as cli_options
from repoenv.cli.completion_helpers import complete_repo_name
from repoenv.cli.resolve import resolve_environment
from repoenv.cli.worktree_reporting import expand_selection
from repoenv.domain.models import Environment
from repoenv.errors import UsageError
from repoenv.services import lifecycle_service
from repoenv.ui import console


@dataclass(frozen=True)
class _RmRequest:
    """How ``renv rm`` removes: the whole environment or only selected repos, and what to delete."""

    partial: bool
    delete_files: bool
    delete_branches: bool
    force: bool


def rm_command(
    env: Optional[str] = cli_options.env_argument(),
    include: list[str] = typer.Option(
        [],
        "--include",
        "-i",
        help="Only remove repos matching these glob(s) from the env (keeps the env).",
        autocompletion=complete_repo_name,
    ),
    exclude: list[str] = typer.Option(
        [], "--exclude", "-x", help="Glob(s) of repos to keep.", autocompletion=complete_repo_name
    ),
    delete_branches: bool = typer.Option(
        False,
        "--delete-branches",
        help="Also delete local branches renv created (safe delete; --force deletes unmerged ones).",
    ),
    keep_files: bool = typer.Option(
        False, "--keep-files", help="Only update the registry; keep worktrees and the env dir on disk."
    ),
    force: bool = typer.Option(False, "--force", help="Remove even if worktrees are dirty."),
    dry_run: bool = cli_options.dry_run_option(),
) -> None:
    """Remove an environment, or only selected repos with ``-i``/``-x``.

    Deletes files unless ``--keep-files`` is passed.
    """
    if delete_branches and keep_files:
        raise UsageError(
            "--delete-branches cannot be combined with --keep-files.",
            hint="Branches stay checked out while their worktrees exist.",
        )
    request = _RmRequest(
        partial=bool(include or exclude),
        delete_files=not keep_files,
        delete_branches=delete_branches,
        force=force,
    )
    if request.partial:
        include, exclude = expand_selection(include, exclude)

    with state_store.registry_transaction() as registry:
        environment = resolve_environment(registry, env)
        target = _select_target(environment, include, exclude) if request.partial else environment
        _refuse_dirty(environment, target, request)

        scope = _describe_scope(environment, target, request)
        console.print_info(
            f"Remove {scope} (delete_files={request.delete_files}, delete_branches={request.delete_branches})"
        )
        if dry_run:
            console.print_info("Dry run: no changes made.")
            return

        _remove(environment, target, request)
        _update_registry(registry, environment, target, request)
    console.print_info(f"Removed {scope}.")


def _select_target(environment: Environment, include: list[str], exclude: list[str]) -> Environment:
    """Return a copy of ``environment`` holding only the selected repos."""
    entries = lifecycle_service.select_repo_entries(
        environment, include=include or None, exclude=exclude or None
    )
    if len(entries) == len(environment.repos):
        raise UsageError(
            f"Selection matches every repo in '{environment.name}'.",
            hint="Run 'renv rm' without -i/-x to remove the whole environment.",
        )
    return environment.model_copy(update={"repos": entries})


def _refuse_dirty(environment: Environment, target: Environment, request: _RmRequest) -> None:
    """Raise unless ``--force`` is given or no worktree of *target* has local changes."""
    dirty = lifecycle_service.check_dirty(target)
    if dirty and not request.force:
        raise UsageError(
            f"Refusing to remove '{environment.name}': dirty worktrees: {', '.join(dirty)}.",
            hint="Commit/stash changes, or pass --force.",
        )


def _describe_scope(environment: Environment, target: Environment, request: _RmRequest) -> str:
    if request.partial:
        return f"{len(target.repos)} repo(s) from '{environment.name}'"
    return f"environment '{environment.name}'"


def _remove(environment: Environment, target: Environment, request: _RmRequest) -> None:
    """Delete worktrees (and the env dir for a full removal) and/or created branches."""
    if request.delete_files:
        lifecycle_service.remove_worktrees(target, force=request.force)
        if not request.partial and environment.path.exists():
            shutil.rmtree(environment.path, ignore_errors=True)
    if request.delete_branches:
        _delete_branches(target, force=request.force)


def _update_registry(
    registry: state_store.Registry, environment: Environment, target: Environment, request: _RmRequest
) -> None:
    """Drop the removed repos from *environment*, or the whole environment from the registry."""
    if not request.partial:
        registry.remove(environment.name)
        return
    removed = {entry.repo for entry in target.repos}
    environment.repos = [entry for entry in environment.repos if entry.repo not in removed]
    registry.add(environment)
    state_store.write_env_metadata(environment)


def _delete_branches(target: Environment, *, force: bool) -> None:
    deleted, warnings = lifecycle_service.delete_created_branches(target, force=force)
    if deleted:
        console.print_info(f"Deleted branch(es): {', '.join(deleted)}")
    for warning in warnings:
        console.print_info(f"Warning: {warning}")
