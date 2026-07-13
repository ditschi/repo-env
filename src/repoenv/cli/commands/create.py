"""``renv create`` — create an environment from repos matching a selection."""

from __future__ import annotations

import getpass
import socket
from pathlib import Path
from typing import Optional

import typer

from repoenv import __version__
from repoenv.adapters import config_store, state_store
from repoenv.errors import UsageError
from repoenv.services import environment_service
from repoenv.ui import console


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
        None, "--branch", "-b", help="Create and check out this new branch."
    ),
    default_branch: Optional[str] = typer.Option(
        None, "--default-branch", "-B", help="Fallback default branch when auto-detection fails."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Short alias for the environment."),
    preserve: bool = typer.Option(False, "--preserve", help="Skip fetch/update; use source repos as-is."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Create a new environment of git worktrees."""
    config = config_store.load_config()
    resolved_source = source or config.source
    resolved_dest = dest or config.dest
    if resolved_source is None:
        raise UsageError("No --source given and no default configured. Run 'renv init' first.")
    if resolved_dest is None:
        raise UsageError("No --dest given and no default configured. Run 'renv init' first.")

    registry = state_store.load_registry()
    if name in registry:
        raise UsageError(f"Environment '{name}' already exists.", hint="Use 'renv add' to extend it.")

    plan = environment_service.build_create_plan(
        name=name,
        source=resolved_source,
        dest=resolved_dest,
        include=include or None,
        exclude=exclude or None,
        branch=branch,
        alias=alias,
        default_branch=default_branch or config.default_branch,
        include_renv=include_renv,
    )

    console.print_info(f"Environment '{name}' -> {plan.env_path}")
    console.print_info(f"Repositories ({len(plan.repos)}):")
    console.render_repositories(plan.repos)

    if dry_run:
        console.print_info("Dry run: no changes made.")
        return

    env = environment_service.execute_create_plan(plan, preserve=preserve)
    registry.add(env)
    state_store.save_registry(registry)
    state_store.write_env_metadata(env)
    command_name = ctx.info_name or "create"
    recreate_parts = [f"renv {command_name}", name]
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
    if default_branch is not None:
        recreate_parts.extend(["--default-branch", default_branch])
    if alias is not None:
        recreate_parts.extend(["--alias", alias])
    if preserve:
        recreate_parts.append("--preserve")
    marker = {
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
    state_store.write_env_marker(env, marker)

    console.print_info(f"Created environment '{name}' with {len(env.repos)} worktree(s).")
