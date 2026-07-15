"""Machine-owned state store: the environment registry (JSON) and per-env metadata.

JSON (not YAML) so ``--json`` output is a zero-transcoding pass-through and the
schema is a stable typed contract. Writes are atomic and locked.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock
from pydantic import ValidationError

from repoenv.adapters import paths
from repoenv.adapters.atomic import atomic_write_text
from repoenv.domain.models import SCHEMA_VERSION, Environment
from repoenv.errors import ConfigError


class Registry:
    """In-memory view of all known environments, keyed by name."""

    def __init__(
        self, environments: dict[str, Environment] | None = None, *, active: str | None = None
    ) -> None:
        self._environments: dict[str, Environment] = environments or {}
        self._active: str | None = active

    def list(self) -> list[Environment]:
        """Return environments sorted by name for deterministic output."""
        return [self._environments[name] for name in sorted(self._environments)]

    def get(self, name: str) -> Environment | None:
        """Return the environment named ``name`` or ``None``."""
        return self._environments.get(name)

    def find_by_alias(self, alias: str) -> Environment | None:
        """Return the environment whose alias matches ``alias``."""
        for env in self._environments.values():
            if env.alias == alias:
                return env
        return None

    def add(self, env: Environment) -> None:
        """Insert or replace an environment."""
        self._environments[env.name] = env

    def remove(self, name: str) -> bool:
        """Remove an environment; return True if it existed."""
        if self._active == name:
            self._active = None
        return self._environments.pop(name, None) is not None

    def get_active(self) -> str | None:
        """Return the active environment name, if any."""
        return self._active

    def set_active(self, name: str | None) -> None:
        """Set the active environment name (or clear it with None)."""
        self._active = name

    def __contains__(self, name: object) -> bool:
        return name in self._environments


def load_registry(path: Path | None = None) -> Registry:
    """Load the environment registry, returning an empty one when absent."""
    registry_path = path or paths.registry_path()
    if not registry_path.exists():
        return Registry()

    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(
            f"Could not read registry at {registry_path}: {exc}",
            hint="Run 'renv repair' to restore missing worktrees, or 'renv status' for details.",
        ) from exc

    environments: dict[str, Environment] = {}
    for item in raw.get("environments", []):
        try:
            env = Environment.model_validate(item)
        except ValidationError as exc:
            raise ConfigError(
                f"Registry entry is invalid:\n{exc}",
                hint="Run 'renv repair' or fix the registry entry manually.",
            ) from exc
        environments[env.name] = env
    active = raw.get("active")
    if active is not None and not isinstance(active, str):
        raise ConfigError(
            f"Registry field 'active' must be a string or null, not {type(active).__name__}.",
            hint="Remove or fix the 'active' field in the registry JSON.",
        )
    if active is not None and active not in environments:
        # Don't fail hard: an env may have been removed manually.
        active = None
    return Registry(environments, active=active)


def save_registry(registry: Registry, path: Path | None = None) -> Path:
    """Atomically persist the registry to disk."""
    registry_path = path or paths.registry_path()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "active": registry.get_active(),
        "environments": [env.model_dump(mode="json") for env in registry.list()],
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    atomic_write_text(registry_path, text, mode=0o600, backup=True)
    return registry_path


@contextmanager
def registry_transaction(path: Path | None = None) -> Iterator[Registry]:
    """Load-modify-save the registry under a single file lock.

    This prevents lost updates when multiple repo-env processes mutate the
    registry concurrently (e.g. parallel ``renv add`` runs).
    """
    registry_path = path or paths.registry_path()
    lock = FileLock(str(paths.lock_path(registry_path)), is_singleton=True)
    with lock:
        registry = load_registry(registry_path)
        yield registry
        save_registry(registry, registry_path)


def write_env_metadata(env: Environment, *, marker: dict[str, object] | None = None) -> Path:
    """Write per-environment metadata inside the environment directory.

    This file also serves as the renv-root marker (replacing the older dedicated
    marker file) and may optionally include a reproduction marker block.
    """
    meta_path = env.path / paths.ENV_META_FILENAME
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "environment": env.model_dump(mode="json"),
        "marker": marker,
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    atomic_write_text(meta_path, text, mode=0o600, backup=False)
    return meta_path
