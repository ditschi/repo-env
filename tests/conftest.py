"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Typer's --install-completion/--show-completion auto-detect the calling shell
# via `shellingham`, which walks the process tree. That's flaky/exception-prone
# on some CI sandboxes (e.g. macOS GitHub Actions runners raise there instead of
# a clean ShellDetectionFailure), unrelated to anything renv does. This env var
# is typer's own documented test hook to skip that detection entirely, since
# tests always pass an explicit shell name anyway.
os.environ.setdefault("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")


@pytest.fixture()
def repoenv_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point repo-env config/state at a temp dir so tests stay hermetic."""
    home = tmp_path / "repoenv-home"
    home.mkdir()
    monkeypatch.setenv("REPOENV_HOME", str(home))
    yield home
