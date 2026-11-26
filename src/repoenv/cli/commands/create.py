"""``renv create`` — create an environment from repos matching a selection."""
# aihealth: disable=primitive_obsession, excess_arguments -- typer CLI boundary: options are parameters

from __future__ import annotations

import getpass
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from repoenv import __version__
from repoenv.adapters import config_store, paths, state_store
from repoenv.cli import options as cli_options
from repoenv.cli.worktree_reporting import (
    print_activate_hint,
    print_progress,
    print_skipped_worktrees,
    raise_on_failures,
)
from repoenv.domain.models import Environment
from repoenv.errors import UsageError
from repoenv.services import environment_service
from repoenv.ui import console


@dataclass(frozen=True)
class _CreateArgs:
    """The ``renv create`` arguments as given (after ``@group`` expansion)."""

    source: Path | None
    dest: Path | None
    include: list[str]
    exclude: list[str]
    include_worktrees: bool
    branch: str | None
    default_branch: str | None
    alias: str | None
    preserve: bool


def _resolve_create_paths(
    *,
    source: Path | None,
    dest: Path | None,
    config: config_store.UserConfig,
) -> tuple[Path, Path]:
    resolved_source = source or config.source
    resolved_dest = dest or config.dest
    if resolved_source is None:
        raise UsageError("No --source given and no default configured. Run 'renv init' first.")
    if resolved_dest is None:
        raise UsageError("No --dest given and no default configured. Run 'renv init' first.")
    return resolved_source, resolved_dest


def _exists_on_disk(env: Environment) -> bool:
    """Return True if *env*'s directory exists and holds its metadata (or legacy marker) file."""
    if not env.path.exists():
        return False
    return (env.path / paths.ENV_META_FILENAME).exists() or (env.path / paths.ENV_MARKER_FILENAME).exists()


def _reconcile_existing_env(name: str) -> None:
    with state_store.registry_transaction() as registry:
        existing = registry.get(name)
        if existing is None:
            return
        if not _exists_on_disk(existing):
            registry.remove(name)
            console.print_info(f"Reconciled: removed stale registry entry for '{name}' (missing on disk).")
            return
        raise UsageError(f"Environment '{name}' already exists.", hint="Use 'renv add' to extend it.")


def _recreate_flags(args: _CreateArgs) -> list[str]:
    """Return the CLI flags that recreate an environment created with *args*."""
    flags: list[str] = []
    for pattern in args.include:
        flags.extend(["--include", pattern])
    for pattern in args.exclude:
        flags.extend(["--exclude", pattern])
    if args.include_worktrees:
        flags.append("--include-worktrees")
    optional: list[tuple[str, object]] = [
        ("--source", args.source),
        ("--dest", args.dest),
        ("--branch", args.branch),
        ("--default-branch", args.default_branch),
        ("--alias", args.alias),
    ]
    for flag, value in optional:
        if value is not None:
            flags.extend([flag, str(value)])
    if args.preserve:
        flags.append("--preserve")
    return flags


def _build_create_marker(ctx: typer.Context, env: Environment, args: _CreateArgs) -> dict[str, object]:
    command_name = ctx.info_name or "create"
    recreate_parts = [f"renv {command_name}", env.name, *_recreate_flags(args)]
    return {
        "schema_version": 1,
        "kind": "repo-env-marker",
        "tool": "repo-env",
        "tool_version": __version__,
        "environment_name": env.name,
        "environment_path": str(env.path),
        "source_path": str(env.source),
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "command": {
            "name": "create",
            "recreate": " ".join(recreate_parts),
        },
    }


def _build_plan(
    name: str, source_and_dest: tuple[Path, Path], args: _CreateArgs, config_default_branch: str | None
) -> environment_service.CreatePlan:
    source, dest = source_and_dest
    return environment_service.build_create_plan(
        environment_service.CreateRequest(
            name=name,
            source=source,
            dest=dest,
            include=args.include or None,
            exclude=args.exclude or None,
            branch=args.branch,
            alias=args.alias,
            default_branch=args.default_branch or config_default_branch,
            include_worktrees=args.include_worktrees,
        )
    )


def _print_plan(name: str, plan: environment_service.CreatePlan) -> None:
    console.print_info(f"Environment '{name}' -> {plan.env_path}")
    print_skipped_worktrees(plan.skipped_worktrees)
    console.print_info(f"Repositories ({len(plan.repos)}):")
    console.render_repositories(plan.repos)


def _execute_and_register(
    plan: environment_service.CreatePlan, options: environment_service.ExecuteOptions, *, activate: bool
) -> Environment:
    with state_store.registry_transaction() as registry:
        env = environment_service.execute_create_plan(plan, options=options)
        registry.add(env)
        if activate:
            registry.set_active(env.name)
        state_store.write_env_metadata(env)
    return env


def create_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name of the environment to create."),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Directory of source clones."),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Where the environment dir is created."),
    include: list[str] = cli_options.include_option(),
    exclude: list[str] = cli_options.exclude_option(),
    include_worktrees: bool = cli_options.include_worktrees_option(),
    branch: Optional[str] = cli_options.branch_option(),
    on_branch_conflict: environment_service.BranchConflictStrategy = cli_options.on_branch_conflict_option(),
    default_branch: Optional[str] = typer.Option(
        None, "--default-branch", "-B", help="Fallback default branch when auto-detection fails."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Short alias for the environment."),
    preserve: bool = cli_options.preserve_option(),
    activate: bool = cli_options.activate_option(),
    dry_run: bool = cli_options.dry_run_option(),
) -> None:
    """Create a new environment of git worktrees."""
    config = config_store.load_config()
    resolved_source, resolved_dest = _resolve_create_paths(source=source, dest=dest, config=config)
    _reconcile_existing_env(name)

    args = _CreateArgs(
        source=source,
        dest=dest,
        include=environment_service.expand_repo_groups(include, config.groups),
        exclude=environment_service.expand_repo_groups(exclude, config.groups),
        include_worktrees=include_worktrees,
        branch=branch,
        default_branch=default_branch,
        alias=alias,
        preserve=preserve,
    )
    plan = _build_plan(name, (resolved_source, resolved_dest), args, config.default_branch)
    _print_plan(name, plan)

    with state_store.registry_transaction() as registry:
        active_set = registry.get_active() is not None

    if dry_run:
        console.print_info("Dry run: no changes made.")
        print_activate_hint(name, activate=activate, active_set=active_set)
        return

    options = environment_service.ExecuteOptions(
        preserve=preserve, on_branch_conflict=on_branch_conflict, on_repo_start=print_progress
    )
    env = _execute_and_register(plan, options, activate=activate)
    state_store.write_env_metadata(env, marker=_build_create_marker(ctx, env, args))

    raise_on_failures(env)
    print_activate_hint(env.name, activate=activate, active_set=active_set)
    console.print_info(f"Created environment '{name}' with {len(env.repos)} worktree(s).")
