"""Tests for shell env-name completion (registry names, not CWD paths)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.domain.models import Environment, RepoEntry, RepoStatus


def _register(
    repoenv_home: Path,
    name: str,
    *,
    alias: str | None = None,
) -> Environment:
    env_path = repoenv_home / "envs" / name
    wt = env_path / "repo"
    wt.mkdir(parents=True)
    env = Environment(
        name=name,
        alias=alias,
        path=env_path,
        source=repoenv_home / "src",
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
    registry = state_store.load_registry()
    registry.add(env)
    state_store.save_registry(registry)
    return env


def _bash_complete(
    *,
    repoenv_home: Path,
    cwd: Path,
    words: str,
    cword: int,
    args: list[str],
) -> list[str]:
    """Run Click/Typer bash completion and return suggestion lines."""
    renv_exe = shutil.which("renv")
    if renv_exe is None:
        pytest.fail("renv console script not on PATH; install the package first.")

    env = os.environ.copy()
    env["REPOENV_HOME"] = str(repoenv_home)
    env["_RENV_COMPLETE"] = "complete_bash"
    env["COMP_WORDS"] = words
    env["COMP_CWORD"] = str(cword)
    result = subprocess.run(
        [renv_exe, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def test_complete_env_name_lists_names_and_aliases(repoenv_home: Path) -> None:
    _register(repoenv_home, "alpha", alias="a")
    _register(repoenv_home, "beta")

    assert complete_env_name(None, "") == ["a", "alpha", "beta"]
    assert complete_env_name(None, "a") == ["a", "alpha"]
    assert complete_env_name(None, "b") == ["beta"]


def test_complete_env_name_empty_registry(repoenv_home: Path) -> None:
    assert complete_env_name(None, "") == []


@pytest.mark.parametrize(
    ("words", "cword", "args"),
    [
        ("renv status ", 2, ["status"]),
        ("renv rm ", 2, ["rm"]),
        ("renv rename ", 2, ["rename"]),
        ("renv merge merged ", 3, ["merge", "merged"]),
        ("renv merge merged alpha ", 4, ["merge", "merged", "alpha"]),
    ],
)
def test_bash_completion_suggests_registry_env_names_not_cwd_dirs(
    repoenv_home: Path,
    tmp_path: Path,
    words: str,
    cword: int,
    args: list[str],
) -> None:
    """Regression: env-name args must not fall back to local directory completion."""
    _register(repoenv_home, "alpha", alias="a")
    _register(repoenv_home, "beta")

    cwd = tmp_path / "cwd-with-decoys"
    cwd.mkdir()
    for name in ("decoy-a", "decoy-b", "src", "tests"):
        (cwd / name).mkdir()

    suggestions = _bash_complete(
        repoenv_home=repoenv_home,
        cwd=cwd,
        words=words,
        cword=cword,
        args=args,
    )

    assert "alpha" in suggestions
    assert "beta" in suggestions
    assert "a" in suggestions
    assert not any("decoy" in item for item in suggestions)
    assert not any(item.startswith("./") or item.startswith("/") for item in suggestions)
