"""Shell completion helpers for Typer/Click.

Kept separate so individual commands can share completion logic without
introducing import cycles.
"""

from __future__ import annotations

from typing import List

import typer

from repoenv.adapters import config_store, state_store


def complete_env_name(ctx: typer.Context, incomplete: str) -> List[str]:
    """Complete environment names and aliases from the registry and config."""
    _ = ctx
    registry = state_store.load_registry()
    cfg = config_store.load_config()
    items: list[str] = []
    for env in registry.list():
        items.append(env.name)
        if env.alias:
            items.append(env.alias)
    items.extend(cfg.aliases.keys())
    prefix = incomplete or ""
    return sorted({x for x in items if x.startswith(prefix)})
