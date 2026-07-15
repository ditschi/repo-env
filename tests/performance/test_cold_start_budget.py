"""CLI cold-start latency budgets for shell completion responsiveness."""

from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters import state_store
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from tests.performance.conftest import (
    COMPLETION_COMMAND_BUDGET_S,
    COMPLETION_ENV_BUDGET_S,
    HELP_BUDGET_S,
    bash_completion_env,
    median_cold_start,
    subprocess_env,
)


def _seed_registry(home: Path, *, count: int = 12) -> None:
    """Register several environments so env-name completion exercises the registry."""
    registry = state_store.load_registry(home / "registry.json")
    for i in range(count):
        env_path = home / "envs" / f"env-{i}"
        wt = env_path / "repo"
        wt.mkdir(parents=True)
        env = Environment(
            name=f"env-{i}",
            alias=f"alias-{i}" if i % 3 == 0 else None,
            path=env_path,
            source=home / "src",
            repos=[
                RepoEntry(
                    repo="repo",
                    worktree_path=wt,
                    remote="origin",
                    base="main",
                    branch="feature",
                    status=RepoStatus.OK,
                )
            ],
        )
        registry.add(env)
    state_store.save_registry(registry, home / "registry.json")


@pytest.mark.performance
def test_help_cold_start_within_budget(renv_exe: str, isolated_home: Path) -> None:
    elapsed = median_cold_start(renv_exe, ["--help"], env=subprocess_env(home=isolated_home))
    assert (
        elapsed < HELP_BUDGET_S
    ), f"renv --help cold start too slow: {elapsed:.3f}s (budget {HELP_BUDGET_S}s)"


@pytest.mark.performance
def test_bash_completion_command_list_within_budget(renv_exe: str, isolated_home: Path) -> None:
    """Simulates ``renv <Tab>`` — completes subcommands after the program name."""
    elapsed = median_cold_start(
        renv_exe,
        [],
        env=subprocess_env(
            home=isolated_home,
            extra=bash_completion_env(words="renv ", cword=1),
        ),
    )
    assert (
        elapsed < COMPLETION_COMMAND_BUDGET_S
    ), f"command completion cold start too slow: {elapsed:.3f}s (budget {COMPLETION_COMMAND_BUDGET_S}s)"


@pytest.mark.performance
def test_bash_completion_env_names_within_budget(renv_exe: str, isolated_home: Path) -> None:
    """Simulates ``renv status <Tab>`` — loads the registry and completes env names."""
    _seed_registry(isolated_home)
    elapsed = median_cold_start(
        renv_exe,
        ["status"],
        env=subprocess_env(
            home=isolated_home,
            extra=bash_completion_env(words="renv status ", cword=2),
        ),
    )
    assert (
        elapsed < COMPLETION_ENV_BUDGET_S
    ), f"env-name completion cold start too slow: {elapsed:.3f}s (budget {COMPLETION_ENV_BUDGET_S}s)"
