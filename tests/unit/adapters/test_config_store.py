from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters import config_store
from repoenv.errors import ConfigError


def test_load_config_defaults_when_missing(repoenv_home: Path) -> None:
    cfg = config_store.load_config()
    assert cfg.source is None
    assert cfg.dest is None
    assert cfg.aliases == {}


def test_save_then_load_config(repoenv_home: Path) -> None:
    path = repoenv_home / "src"
    dest = repoenv_home / "envs"
    cfg = config_store.UserConfig(source=path, dest=dest, default_branch="main")
    config_store.save_config(cfg)
    loaded = config_store.load_config()
    assert loaded.source == path
    assert loaded.dest == dest
    assert loaded.default_branch == "main"


def test_rejects_yaml_aliases(repoenv_home: Path) -> None:
    text = """
a: &x test
b: *x
"""
    config_path = repoenv_home / "repoenv.yaml"
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        config_store.load_config(config_path)
