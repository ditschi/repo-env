from __future__ import annotations

from pathlib import Path

from repoenv.adapters import state_store
from repoenv.domain.models import Environment


def test_save_and_load_registry(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    env = Environment(name="demo", path=Path("/tmp/env"), source=Path("/tmp/src"))
    registry.add(env)
    state_store.save_registry(registry)

    loaded = state_store.load_registry()
    loaded_env = loaded.get("demo")
    assert loaded_env is not None
    assert loaded_env.name == "demo"


def test_find_by_alias(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    registry.add(Environment(name="demo", alias="d", path=Path("/tmp/env"), source=Path("/tmp/src")))
    assert registry.find_by_alias("d") is not None
    assert registry.find_by_alias("x") is None


def test_write_env_marker_creates_marker_file(tmp_path: Path) -> None:
    env_path = tmp_path / "envs" / "demo"
    env_path.mkdir(parents=True)
    env = Environment(name="demo", path=env_path, source=tmp_path / "src")

    marker_path = state_store.write_env_marker(env, {"kind": "repo-env-marker", "schema_version": 1})

    assert marker_path == env_path / ".repoenv.marker.json"
    assert marker_path.exists()
