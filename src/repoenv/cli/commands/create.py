"""``renv create`` — create an environment from repos matching a selection."""

from __future__ import annotations

import getpass
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from repoenv import __version__
from repoenv.adapters import config_store, paths, state_store
from repoenv.cli.completion_helpers import complete_repo_name
from repoenv.domain.models import Environment
from repoenv.errors import PartialFailureError, UsageError
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


def _reconcile_existing_env(name: str) -> None:
    with state_store.registry_transaction() as registry:
        existing = registry.get(name)
        if existing is None:
            return
        meta = existing.path / paths.ENV_META_FILENAME
        legacy = existing.path / paths.ENV_MARKER_FILENAME
        if not existing.path.exists() or not (meta.exists() or legacy.exists()):
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
    if plan.skipped_worktrees:
        console.print_info(
            f"Skipped {len(plan.skipped_worktrees)} git worktree(s) (use --include-worktrees to include)."
        )
    console.print_info(f"Repositories ({len(plan.repos)}):")
    console.render_repositories(plan.repos)


def _print_progress(repo: str, current: int, total: int) -> None:
    console.print_info(f"  [{current}/{total}] {repo}")


def _print_activate_hint(name: str, *, activate: bool, active_set: bool) -> None:
    if not activate and not active_set:
        console.print_info(f"Hint: run 'renv activate {name}' to set it as the default.")


def _raise_on_failures(env: Environment) -> None:
    if not environment_service.failed_repos(env):
        return
    details = environment_service.failure_details(env)
    lines = "\n".join(f"  {repo}: {note or 'unknown error'}" for repo, note in details)
    raise PartialFailureError(
        f"Some repositories failed:\n{lines}",
        hint="Run 'renv repair' or 'renv status' to see which worktrees are missing or failed.",
    )


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
    include: list[str] = typer.Option(
        [], "--include", "-i", help="Glob(s) of repos to include.", autocompletion=complete_repo_name
    ),
    exclude: list[str] = typer.Option(
        [], "--exclude", "-x", help="Glob(s) of repos to exclude.", autocompletion=complete_repo_name
    ),
    include_worktrees: bool = typer.Option(
        False,
        "--include-worktrees",
        help="Include git linked worktrees found under the source directory.",
    ),
    branch: Optional[str] = typer.Option(
        None, "--branch", "-b", help="Create and check out this new branch."
    ),
    on_branch_conflict: environment_service.BranchConflictStrategy = typer.Option(
        environment_service.BranchConflictStrategy.DETACH,
        "--on-branch-conflict",
        help="When the target branch is already checked out elsewhere: detach|move|fail.",
    ),
    default_branch: Optional[str] = typer.Option(
        None, "--default-branch", "-B", help="Fallback default branch when auto-detection fails."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Short alias for the environment."),
    preserve: bool = typer.Option(False, "--preserve", help="Skip fetch/update; use source repos as-is."),
    activate: bool = typer.Option(False, "--activate", help="Mark this environment as the default."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
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
        _print_activate_hint(name, activate=activate, active_set=active_set)
        return

    options = environment_service.ExecuteOptions(
        preserve=preserve, on_branch_conflict=on_branch_conflict, on_repo_start=_print_progress
    )
    env = _execute_and_register(plan, options, activate=activate)
    state_store.write_env_metadata(env, marker=_build_create_marker(ctx, env, args))

    _raise_on_failures(env)
    _print_activate_hint(env.name, activate=activate, active_set=active_set)
    console.print_info(f"Created environment '{name}' with {len(env.repos)} worktree(s).")
