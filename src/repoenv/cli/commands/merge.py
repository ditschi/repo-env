"""``renv merge`` — combine two environments into a new one."""

from __future__ import annotations

import getpass
import socket
from pathlib import Path
from typing import Optional

import typer

from repoenv import __version__
from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.domain.selection import SetOp
from repoenv.errors import UsageError
from repoenv.services import environment_service
from repoenv.ui import console


def merge_command(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="New environment name."),
    left: str = typer.Argument(
        ...,
        help="First source environment.",
        autocompletion=complete_env_name,
    ),
    right: str = typer.Argument(
        ...,
        help="Second source environment.",
        autocompletion=complete_env_name,
    ),
    op: SetOp = typer.Option(SetOp.UNION, "--op", help="Set operation: union|intersect|difference."),
    dest: Optional[Path] = typer.Option(
        None, "--dest", "-d", help="Destination root (defaults to left env parent)."
    ),
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Alias for the merged environment."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without making changes."),
) -> None:
    """Merge two environments into a newly created environment."""
    with state_store.registry_transaction() as registry:
        if registry.get(name) is not None:
            raise UsageError(f"Environment '{name}' already exists.")

        left_env = registry.get(left) or registry.find_by_alias(left)
        right_env = registry.get(right) or registry.find_by_alias(right)
        if left_env is None or right_env is None:
            raise UsageError(
                "Both source environments must exist.",
                hint="Run 'renv ls' to view names and aliases.",
            )
        if left_env.source != right_env.source:
            raise UsageError("Cannot merge environments from different source roots.")

        dest_root = dest or left_env.path.parent
        plan = environment_service.build_merge_plan(
            left=left_env,
            right=right_env,
            op=op,
            dest_name=name,
            dest_root=dest_root,
            alias=alias,
        )
        console.print_info(
            f"Merge {left_env.name} {op.value} {right_env.name} -> {name} ({len(plan.worktrees)} repos)"
        )

        if dry_run:
            console.print_info("Dry run: no changes made.")
            return

        merged = environment_service.execute_create_plan(plan)
        registry.add(merged)
        state_store.write_env_metadata(merged)
    command_name = ctx.info_name or "merge"
    marker = {
        "schema_version": 1,
        "kind": "repo-env-marker",
        "tool": "repo-env",
        "tool_version": __version__,
        "environment_name": merged.name,
        "environment_path": str(merged.path),
        "source_path": str(merged.source),
        "created_at": merged.created_at.isoformat(),
        "created_by": getpass.getuser(),
        "host": socket.gethostname(),
        "command": {
            "cwd": str(Path.cwd()),
            "name": command_name,
            "recreate": f"renv {command_name} {name} {left} {right} --op {op.value}",
            "options": {
                "dest": str(dest_root),
                "alias": alias,
                "op": op.value,
            },
        },
    }
    state_store.write_env_metadata(merged, marker=marker)
    console.print_info(f"Created merged environment '{name}'.")
