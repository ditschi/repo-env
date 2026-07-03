"""``renv prune`` — reconcile registry with disk and prune stale worktrees."""

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.services import lifecycle_service
from repoenv.ui import console


def prune_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
) -> None:
    """Run ``git worktree prune`` across an environment's repositories."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)
    pruned = lifecycle_service.prune_environment(environment)
    console.print_info(f"Pruned worktree metadata for {pruned} repo(s) in '{environment.name}'.")
