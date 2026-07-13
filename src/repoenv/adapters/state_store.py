"""Machine-owned state store: the environment registry (JSON) and per-env metadata.

JSON (not YAML) so ``--json`` output is a zero-transcoding pass-through and the
schema is a stable typed contract. Writes are atomic and locked.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from repoenv.adapters import paths
from repoenv.adapters.atomic import atomic_write_text
from repoenv.domain.models import SCHEMA_VERSION, Environment
from repoenv.errors import ConfigError


class Registry:
    """In-memory view of all known environments, keyed by name."""

    def __init__(self, environments: dict[str, Environment] | None = None) -> None:
        self._environments: dict[str, Environment] = environments or {}

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
        return self._environments.pop(name, None) is not None

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
            hint="Run 'renv doctor' to reconcile, or remove the corrupt registry.",
        ) from exc

    environments: dict[str, Environment] = {}
    for item in raw.get("environments", []):
        try:
            env = Environment.model_validate(item)
        except ValidationError as exc:
            raise ConfigError(
                f"Registry entry is invalid:\n{exc}",
                hint="Run 'renv doctor' to reconcile the registry with disk.",
            ) from exc
        environments[env.name] = env
    return Registry(environments)


def save_registry(registry: Registry, path: Path | None = None) -> Path:
    """Atomically persist the registry to disk."""
    registry_path = path or paths.registry_path()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "environments": [env.model_dump(mode="json") for env in registry.list()],
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    atomic_write_text(registry_path, text, mode=0o600, backup=True)
    return registry_path


def write_env_metadata(env: Environment) -> Path:
    """Write per-environment metadata inside the environment directory."""
    meta_path = env.path / paths.ENV_META_FILENAME
    text = json.dumps(env.model_dump(mode="json"), indent=2) + "\n"
    atomic_write_text(meta_path, text, mode=0o600, backup=False)
    return meta_path


def write_env_marker(env: Environment, marker: dict[str, object]) -> Path:
    """Write marker metadata used to detect renv roots and reproduce creation."""
    marker_path = env.path / paths.ENV_MARKER_FILENAME
    text = json.dumps(marker, indent=2, sort_keys=True) + "\n"
    atomic_write_text(marker_path, text, mode=0o600, backup=False)
    return marker_path
