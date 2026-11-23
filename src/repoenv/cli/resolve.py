"""Resolve an environment selector (name, alias, or cwd autodetect) to an env."""

from __future__ import annotations

import os
from pathlib import Path

from repoenv.adapters import config_store
from repoenv.adapters.state_store import Registry
from repoenv.domain.models import Environment
from repoenv.errors import NothingMatchedError, UsageError
from repoenv.ui import console


def _lookup_by_selector(registry: Registry, selector: str) -> Environment | None:
    """Resolve a name, environment alias, or config alias to an environment."""
    env = registry.get(selector)
    if env is not None:
        return env
    env = registry.find_by_alias(selector)
    if env is not None:
        return env
    mapped = config_store.load_config().aliases.get(selector)
    if mapped:
        return registry.get(mapped) or registry.find_by_alias(mapped)
    return None


def resolve_environment(registry: Registry, selector: str | None, *, cwd: Path | None = None) -> Environment:
    """Resolve ``selector`` to a single environment.

    Precedence: explicit name -> alias -> cwd autodetect (``-`` or ``None``).
    """
    if selector and selector != "-":
        return _resolve_explicit(registry, selector)

    active_name = registry.get_active()
    env = (
        _env_containing(registry, cwd or Path.cwd(), active_name)
        or _env_from_shell(registry)
        or _env_from_active(registry, active_name)
    )
    if env is not None:
        return env

    raise UsageError(
        "No environment specified and the current directory is not inside one.",
        hint="Pass an environment name, cd into an environment directory, or run 'renv activate <name>'.",
    )


def _resolve_explicit(registry: Registry, selector: str) -> Environment:
    env = _lookup_by_selector(registry, selector)
    if env is None:
        raise NothingMatchedError(
            f"No environment named or aliased '{selector}'.",
            hint="Run 'renv ls' to see available environments.",
        )
    return env


def _env_containing(registry: Registry, cwd: Path, active_name: str | None) -> Environment | None:
    """Return the environment whose directory contains ``cwd``."""
    env = next((candidate for candidate in registry.list() if _is_within(cwd, candidate.path)), None)
    if env is not None and active_name and active_name != env.name:
        console.print_info(
            f"Using environment '{env.name}' from current directory " f"(active: '{active_name}')."
        )
    return env


def _env_from_shell(registry: Registry) -> Environment | None:
    """If invoked from within `renv sh`, prefer the active env var."""
    active_env = os.environ.get("REPOENV_ACTIVE")
    return _lookup_by_selector(registry, active_env) if active_env else None


def _env_from_active(registry: Registry, active_name: str | None) -> Environment | None:
    """Fall back to persisted active environment (power-user default)."""
    return registry.get(active_name) if active_name else None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
