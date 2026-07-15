"""Tests for environment resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters.state_store import Registry
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.models import Environment


def _make_env(name: str, path: Path) -> Environment:
    return Environment(name=name, path=path, source=path.parent / "source")


def test_resolve_cwd_env_over_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_a = _make_env("active-env", tmp_path / "active")
    env_b = _make_env("cwd-env", tmp_path / "cwd")
    registry = Registry({"active-env": env_a, "cwd-env": env_b}, active="active-env")
    cwd = env_b.path / "alpha"
    cwd.mkdir(parents=True)

    messages: list[str] = []
    monkeypatch.setattr(
        "repoenv.cli.resolve.console.print_info",
        lambda msg: messages.append(msg),
    )

    resolved = resolve_environment(registry, None, cwd=cwd)
    assert resolved.name == "cwd-env"
    assert any("active-env" in msg and "cwd-env" in msg for msg in messages)


def test_resolve_cwd_env_no_message_when_active_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _make_env("same", tmp_path / "env")
    registry = Registry({"same": env}, active="same")
    cwd = env.path / "repo"
    cwd.mkdir(parents=True)

    messages: list[str] = []
    monkeypatch.setattr(
        "repoenv.cli.resolve.console.print_info",
        lambda msg: messages.append(msg),
    )

    resolved = resolve_environment(registry, None, cwd=cwd)
    assert resolved.name == "same"
    assert messages == []


def test_resolve_config_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _make_env("ado", tmp_path / "ado")
    registry = Registry({"ado": env})
    monkeypatch.setenv("REPOENV_HOME", str(tmp_path / "home"))
    from repoenv.adapters import config_store

    config_store.save_config(config_store.UserConfig(aliases={"web": "ado"}))

    resolved = resolve_environment(registry, "web")
    assert resolved.name == "ado"
