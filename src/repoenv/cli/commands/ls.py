"""``renv ls`` — list environments."""

from __future__ import annotations

import json

import typer

from repoenv.adapters import state_store
from repoenv.ui import console


def ls_command(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """List known environments."""
    registry = state_store.load_registry()
    environments = registry.list()

    if as_json:
        payload = [env.model_dump(mode="json") for env in environments]
        console.print_data(json.dumps(payload, indent=2))
        return

    if not environments:
        console.print_info("No environments yet. Create one with 'renv create'.")
        return

    console.render_environments(environments)
