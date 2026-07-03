"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def repoenv_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point repo-env config/state at a temp dir so tests stay hermetic."""
    home = tmp_path / "repoenv-home"
    home.mkdir()
    monkeypatch.setenv("REPOENV_HOME", str(home))
    yield home
