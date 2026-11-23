"""Tests for environment resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters.state_store import Registry
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.models import Environment


def _make_env(name: str, path: Path) -> Environment:
    return Environment(name=name, path=path, source=path.parent / "source")


@pytest.fixture
def info_messages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture messages passed to ``console.print_info`` during resolution."""
    messages: list[str] = []
    monkeypatch.setattr("repoenv.cli.resolve.console.print_info", messages.append)
    return messages


def _resolve_from(registry: Registry, cwd: Path) -> Environment:
    cwd.mkdir(parents=True)
    return resolve_environment(registry, None, cwd=cwd)


def test_resolve_cwd_env_over_active(tmp_path: Path, info_messages: list[str]) -> None:
    env_a = _make_env("active-env", tmp_path / "active")
    env_b = _make_env("cwd-env", tmp_path / "cwd")
    registry = Registry({"active-env": env_a, "cwd-env": env_b}, active="active-env")

    resolved = _resolve_from(registry, env_b.path / "alpha")
    assert resolved.name == "cwd-env"
    assert any("active-env" in msg and "cwd-env" in msg for msg in info_messages)


def test_resolve_cwd_env_no_message_when_active_matches(tmp_path: Path, info_messages: list[str]) -> None:
    env = _make_env("same", tmp_path / "env")
    registry = Registry({"same": env}, active="same")

    resolved = _resolve_from(registry, env.path / "repo")
    assert resolved.name == "same"
    assert info_messages == []


def test_resolve_config_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _make_env("ado", tmp_path / "ado")
    registry = Registry({"ado": env})
    monkeypatch.setenv("REPOENV_HOME", str(tmp_path / "home"))
    from repoenv.adapters import config_store

    config_store.save_config(config_store.UserConfig(aliases={"web": "ado"}))

    resolved = resolve_environment(registry, "web")
    assert resolved.name == "ado"
