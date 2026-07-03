"""Resolve an environment selector (name, alias, or cwd autodetect) to an env."""

from __future__ import annotations

from pathlib import Path

from repoenv.adapters.state_store import Registry
from repoenv.domain.models import Environment
from repoenv.errors import NothingMatchedError, UsageError


def resolve_environment(registry: Registry, selector: str | None, *, cwd: Path | None = None) -> Environment:
    """Resolve ``selector`` to a single environment.

    Precedence: explicit name -> alias -> cwd autodetect (``-`` or ``None``).
    """
    if selector and selector != "-":
        env = registry.get(selector) or registry.find_by_alias(selector)
        if env is None:
            raise NothingMatchedError(
                f"No environment named or aliased '{selector}'.",
                hint="Run 'renv ls' to see available environments.",
            )
        return env

    cwd = cwd or Path.cwd()
    for env in registry.list():
        if _is_within(cwd, env.path):
            return env

    raise UsageError(
        "No environment specified and the current directory is not inside one.",
        hint="Pass an environment name, or cd into an environment directory.",
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
