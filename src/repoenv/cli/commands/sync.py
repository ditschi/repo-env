"""``renv sync`` — fetch each repo's remote for an environment."""

from __future__ import annotations

from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import PartialFailureError
from repoenv.services import lifecycle_service
from repoenv.ui import console


def sync_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
) -> None:
    """Fetch updates from each repository's remote."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    failed = lifecycle_service.sync_environment(environment)
    console.print_info(f"Synced {len(environment.repos) - len(failed)} repo(s) for '{environment.name}'.")
    if failed:
        raise PartialFailureError(
            f"Failed to fetch: {', '.join(failed)}.",
            hint="Check network access and remote configuration.",
        )
