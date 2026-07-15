"""Integration-test fixtures and markers."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.support.gitfixtures import RepoFactory


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Ensure every test under ``tests/integration/`` carries both markers."""
    for item in items:
        item.add_marker(pytest.mark.integration)
        item.add_marker(pytest.mark.int)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTENV_ROOT = _REPO_ROOT / ".testenv"


def _sanitize_nodeid(nodeid: str) -> str:
    sanitized = re.sub(r"[^\w.-]+", "_", nodeid)
    return sanitized.strip("_")[:180] or "test"


@pytest.fixture()
def testenv_root(request: pytest.FixtureRequest) -> Iterator[Path]:
    """Per-test directory under ``.testenv/`` (wiped at start, kept for inspection).

    Standard layout::

        .testenv/<test-name>/
          source/        git clones used as renv input
          worktrees/     renv environments and worktrees
          remotes/       bare repos (fixture internals)
          repoenv-home/  isolated REPOENV_HOME
    """
    node = _sanitize_nodeid(request.node.nodeid)
    root = _TESTENV_ROOT / node
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    yield root


@pytest.fixture()
def repo_factory(testenv_root: Path) -> RepoFactory:
    """Factory for bare remotes, source clones, and the worktrees root."""
    return RepoFactory(testenv_root)


@pytest.fixture()
def source_dir(repo_factory: RepoFactory) -> Path:
    """Git repo clones passed to ``renv init --source``."""
    return repo_factory.source


@pytest.fixture()
def worktrees_dir(repo_factory: RepoFactory) -> Path:
    """Root directory passed to ``renv init --dest`` for created worktrees."""
    return repo_factory.worktrees


@pytest.fixture()
def repoenv_home(testenv_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point repo-env config/state at an isolated directory."""
    home = testenv_root / "repoenv-home"
    home.mkdir()
    monkeypatch.setenv("REPOENV_HOME", str(home))
    return home
