"""Resolve config/state directories via platformdirs (honors ``XDG_CONFIG_HOME``).

An explicit ``REPOENV_HOME`` override wins over the platform default, which
keeps tests hermetic and lets power users relocate everything.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

_APP_NAME = "repoenv"
_ENV_OVERRIDE = "REPOENV_HOME"

CONFIG_FILENAME = "repoenv.yaml"
REGISTRY_FILENAME = "registry.json"
ENV_META_FILENAME = ".repoenv.json"
ENV_MARKER_FILENAME = ".repoenv.marker.json"


def home_dir() -> Path:
    """Return the base directory for all repo-env config and state."""
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    return Path(platformdirs.user_config_dir(_APP_NAME))


def config_path() -> Path:
    """Path to the user-authored YAML config file."""
    return home_dir() / CONFIG_FILENAME


def registry_path() -> Path:
    """Path to the machine-owned JSON environment registry."""
    return home_dir() / REGISTRY_FILENAME


def lock_path(target: Path) -> Path:
    """Path to the lock file guarding ``target``."""
    return target.with_suffix(target.suffix + ".lock")


def ensure_home() -> Path:
    """Create the home directory (mode 0700) if missing and return it."""
    base = home_dir()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base
