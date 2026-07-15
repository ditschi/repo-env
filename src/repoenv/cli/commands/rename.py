"""``renv rename`` — rename an environment."""

from __future__ import annotations

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.errors import UsageError
from repoenv.ui import console


def rename_command(
    old: str = typer.Argument(
        ...,
        help="Current environment name.",
        autocompletion=complete_env_name,
    ),
    new: str = typer.Argument(..., help="New environment name."),
) -> None:
    """Rename an environment in the registry and its metadata."""
    with state_store.registry_transaction() as registry:
        environment = registry.get(old)
        if environment is None:
            raise UsageError(f"No environment named '{old}'.", hint="Run 'renv ls' to see names.")
        if new in registry:
            raise UsageError(f"Environment '{new}' already exists.")

        registry.remove(old)
        environment.name = new
        environment.touch()
        registry.add(environment)
        if environment.path.exists():
            state_store.write_env_metadata(environment)
    console.print_info(f"Renamed '{old}' -> '{new}'.")
