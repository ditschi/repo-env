"""``renv activate`` — set the default active environment."""

from __future__ import annotations

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.errors import NothingMatchedError
from repoenv.ui import console


def activate_command(
    name: str = typer.Argument(
        ...,
        help="Environment name or alias to activate.",
        autocompletion=complete_env_name,
    ),
) -> None:
    """Persistently mark an environment as the default for future commands."""
    with state_store.registry_transaction() as registry:
        env = registry.get(name) or registry.find_by_alias(name)
        if env is None:
            raise NothingMatchedError(
                f"No environment named or aliased '{name}'.",
                hint="Run 'renv ls' to see available environments.",
            )
        registry.set_active(env.name)
    console.print_info(f"Active environment set to '{env.name}'.")
