"""Shell completion helpers for Typer/Click.

Kept separate so individual commands can share completion logic without
introducing import cycles.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from repoenv.adapters import config_store, git_adapter, state_store


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


def _source_for_completion(ctx: typer.Context) -> Optional[Path]:
    """Best-effort source directory to complete repo names against.

    Prefers an already-typed ``--source`` on the same command line; for
    ``add``, falls back to the target environment's own recorded source
    (resolved from its ``env`` argument, if that was typed already); finally
    falls back to the configured default ``source``.
    """
    params = getattr(ctx, "params", None) or {}
    raw_source = params.get("source")
    if raw_source:
        return Path(raw_source).expanduser()

    env_selector = params.get("env")
    if env_selector:
        registry = state_store.load_registry()
        env = registry.get(env_selector) or registry.find_by_alias(env_selector)
        if env is not None:
            return env.source

    return config_store.load_config().source


def complete_repo_name(ctx: typer.Context, incomplete: str) -> List[str]:
    """Complete repo paths discoverable under the effective source directory.

    Repo paths are ``host/org/repo``-shaped (see ``git_adapter.discover_repos``),
    so completing a prefix like ``acme/`` naturally narrows to every repo
    under that "base dir" -- no separate base-dir concept is needed.
    Also supports comma-separated values (``--include a,b,<Tab>``): only the
    segment after the last comma is completed. A segment starting with ``@``
    completes configured repo groups (``renv config groups.<name> <pattern>``)
    instead of repo paths.
    """
    prefix, _, partial = incomplete.rpartition(",")
    matches = _group_matches(partial[1:]) if partial.startswith("@") else _repo_matches(ctx, partial)
    if prefix:
        return [f"{prefix},{m}" for m in matches]
    return matches


def _group_matches(partial: str) -> List[str]:
    """Configured repo groups (as ``@name``) starting with ``partial``."""
    groups = config_store.load_config().groups
    return sorted(f"@{name}" for name in groups if name.startswith(partial))


def _repo_matches(ctx: typer.Context, partial: str) -> List[str]:
    """Repo paths under the effective source directory starting with ``partial``."""
    source = _source_for_completion(ctx)
    if source is None or not source.exists():
        return []
    return sorted({c for c in git_adapter.discover_repos(source) if c.startswith(partial)})
