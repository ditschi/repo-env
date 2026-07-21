"""``renv ls`` — list environments."""

from __future__ import annotations

import json

import typer

from repoenv.adapters import state_store
from repoenv.ui import console


def ls_command(
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
    reconcile: bool = typer.Option(
        False,
        "--reconcile",
        help="Remove stale registry entries whose environment directory is missing on disk.",
    ),
) -> None:
    """List known environments."""
    if reconcile:
        with state_store.registry_transaction() as registry:
            stale = [env for env in registry.list() if not env.path.exists()]
            removed_names: list[str] = []
            for env in stale:
                if registry.remove(env.name):
                    removed_names.append(env.name)
            environments = registry.list()
        if removed_names:
            console.print_info(
                "Reconciled registry: removed stale environment(s): " + ", ".join(sorted(removed_names))
            )
    else:
        registry = state_store.load_registry()
        environments = registry.list()

    stale_names = [env.name for env in environments if not env.path.exists()]

    if as_json:
        payload = [env.model_dump(mode="json") for env in environments]
        console.print_data(json.dumps(payload, indent=2))
        return

    if not environments:
        console.print_info("No environments yet. Create one with 'renv create'.")
        return

    if stale_names:
        console.print_info(
            "Warning: registry has stale environment(s) missing on disk: " + ", ".join(sorted(stale_names))
        )
        console.print_info("Hint: run 'renv ls --reconcile' to remove stale entries.")

    console.render_environments(environments)
