"""``renv rm`` — remove an environment (delete files by default)."""

from __future__ import annotations

import shutil
from typing import Optional

import typer

from repoenv.adapters import config_store, state_store
from repoenv.cli.completion_helpers import complete_env_name, complete_repo_name
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.models import Environment
from repoenv.errors import UsageError
from repoenv.services import environment_service, lifecycle_service
from repoenv.ui import console


def rm_command(
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
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
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Remove an environment, or only selected repos with ``-i``/``-x``.

    Deletes files unless ``--keep-files`` is passed.
    """
    delete_files = not keep_files
    if delete_branches and not delete_files:
        raise UsageError(
            "--delete-branches cannot be combined with --keep-files.",
            hint="Branches stay checked out while their worktrees exist.",
        )
    partial = bool(include or exclude)
    if partial:
        groups = config_store.load_config().groups
        include = environment_service.expand_repo_groups(include, groups)
        exclude = environment_service.expand_repo_groups(exclude, groups)

    with state_store.registry_transaction() as registry:
        environment = resolve_environment(registry, env)
        target = _select_target(environment, include, exclude) if partial else environment

        dirty = lifecycle_service.check_dirty(target)
        if dirty and not force:
            raise UsageError(
                f"Refusing to remove '{environment.name}': dirty worktrees: {', '.join(dirty)}.",
                hint="Commit/stash changes, or pass --force.",
            )

        scope = (
            f"{len(target.repos)} repo(s) from '{environment.name}'"
            if partial
            else f"environment '{environment.name}'"
        )
        console.print_info(f"Remove {scope} (delete_files={delete_files}, delete_branches={delete_branches})")
        if dry_run:
            console.print_info("Dry run: no changes made.")
            return

        if delete_files:
            lifecycle_service.remove_worktrees(target, force=force)
            if not partial and environment.path.exists():
                shutil.rmtree(environment.path, ignore_errors=True)
        if delete_branches:
            _delete_branches(target, force=force)

        if partial:
            removed = {entry.repo for entry in target.repos}
            environment.repos = [entry for entry in environment.repos if entry.repo not in removed]
            registry.add(environment)
            state_store.write_env_metadata(environment)
        else:
            registry.remove(environment.name)
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


def _delete_branches(target: Environment, *, force: bool) -> None:
    deleted, warnings = lifecycle_service.delete_created_branches(target, force=force)
    if deleted:
        console.print_info(f"Deleted branch(es): {', '.join(deleted)}")
    for warning in warnings:
        console.print_info(f"Warning: {warning}")
