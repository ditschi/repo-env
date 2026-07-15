"""``renv create`` — create an environment from repos matching a selection."""

from __future__ import annotations

import getpass
import socket
from pathlib import Path
from typing import Optional

import typer

from repoenv import __version__
from repoenv.adapters import config_store, paths, state_store
from repoenv.errors import PartialFailureError, UsageError
from repoenv.services import environment_service
from repoenv.ui import console


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


def _build_create_marker(
    *,
    ctx: typer.Context,
    env_name: str,
    env_path: Path,
    source_path: Path,
    include: list[str],
    exclude: list[str],
    include_renv: bool,
    source: Path | None,
    dest: Path | None,
    branch: str | None,
    from_branches: list[str],
    alias: str | None,
    preserve: bool,
) -> dict[str, object]:
    command_name = ctx.info_name or "create"
    recreate_parts = [f"renv {command_name}", env_name]
    for pattern in include:
        recreate_parts.extend(["--include", pattern])
    for pattern in exclude:
        recreate_parts.extend(["--exclude", pattern])
    if include_renv:
        recreate_parts.append("--include-renv")
    if source is not None:
        recreate_parts.extend(["--source", str(source)])
    if dest is not None:
        recreate_parts.extend(["--dest", str(dest)])
    if branch is not None:
        recreate_parts.extend(["--branch", branch])
    for from_branch in from_branches:
        recreate_parts.extend(["--from", from_branch])
    if alias is not None:
        recreate_parts.extend(["--alias", alias])
    if preserve:
        recreate_parts.append("--preserve")
    return {
        "schema_version": 1,
        "kind": "repo-env-marker",
        "tool": "repo-env",
        "tool_version": __version__,
        "environment_name": env_name,
        "environment_path": str(env_path),
        "source_path": str(source_path),
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "command": {
            "name": "create",
            "recreate": " ".join(recreate_parts),
        },
    }


def create_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name of the environment to create."),
    source: Optional[Path] = typer.Option(None, "--source", "-s", help="Directory of source clones."),
    dest: Optional[Path] = typer.Option(None, "--dest", "-d", help="Where the environment dir is created."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    include_renv: bool = typer.Option(
        False,
        "--include-renv",
        help="Include repositories found under nested renv roots.",
    ),
    branch: Optional[str] = typer.Option(
        None, "--branch", "-b", help="Create and check out this new branch (postfixed per base on multi)."
    ),
    from_branch: list[str] = typer.Option(
        [],
        "--from",
        "-f",
        help="Base branch(es) to start from; repeatable or comma-separated. Multiple => one worktree each.",
    ),
    on_branch_conflict: environment_service.BranchConflictStrategy = typer.Option(
        environment_service.BranchConflictStrategy.DETACH,
        "--on-branch-conflict",
        help="When the target branch is already checked out elsewhere: detach|move|fail.",
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

    from_branches = environment_service.parse_branch_list(from_branch)
    plan = environment_service.build_create_plan(
        name=name,
        source=resolved_source,
        dest=resolved_dest,
        include=include or None,
        exclude=exclude or None,
        branch=branch,
        alias=alias,
        default_branch=config.default_branch,
        from_branches=from_branches or None,
        include_renv=include_renv,
    )

    console.print_info(f"Environment '{name}' -> {plan.env_path}")
    console.print_info(f"Worktrees ({len(plan.worktrees)}):")
    console.render_repositories(plan.labels)

    with state_store.registry_transaction() as registry:
        active_set = registry.get_active() is not None

    if dry_run:
        console.print_info("Dry run: no changes made.")
        if not activate and not active_set:
            console.print_info(f"Hint: run 'renv activate {name}' to set it as the default.")
        return

    with state_store.registry_transaction() as registry:
        env = environment_service.execute_create_plan(
            plan, preserve=preserve, on_branch_conflict=on_branch_conflict
        )
        registry.add(env)
        if activate:
            registry.set_active(env.name)
            active_set = True
        state_store.write_env_metadata(env)
    marker = _build_create_marker(
        ctx=ctx,
        env_name=env.name,
        env_path=env.path,
        source_path=env.source,
        include=include,
        exclude=exclude,
        include_renv=include_renv,
        source=source,
        dest=dest,
        branch=branch,
        from_branches=from_branches,
        alias=alias,
        preserve=preserve,
    )
    state_store.write_env_metadata(env, marker=marker)

    failed = environment_service.failed_repos(env)
    if failed:
        raise PartialFailureError(
            f"Some repositories failed: {', '.join(failed)}.",
            hint="Run 'renv repair' or 'renv status' to see which worktrees are missing or failed.",
        )

    if not activate and not active_set:
        console.print_info(f"Hint: run 'renv activate {env.name}' to set it as the default.")

    console.print_info(f"Created environment '{name}' with {len(env.repos)} worktree(s).")
