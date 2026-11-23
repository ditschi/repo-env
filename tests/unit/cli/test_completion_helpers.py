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


def _bash_complete(*, repoenv_home: Path, cwd: Path, words: str) -> list[str]:
    """Run Click/Typer bash completion for the partial command line ``words``.

    ``words`` ends with a space, so the word being completed is the empty one
    after the last typed argument.
    """
    typed = words.split()
    args = typed[1:]
    cword = len(typed)
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
    "words",
    ["renv status ", "renv rm ", "renv rename ", "renv merge merged ", "renv merge merged alpha "],
)
def test_bash_completion_suggests_registry_env_names_not_cwd_dirs(
    repoenv_home: Path,
    tmp_path: Path,
    words: str,
) -> None:
    """Regression: env-name args must not fall back to local directory completion."""
    _register(repoenv_home, "alpha", alias="a")
    _register(repoenv_home, "beta")

    cwd = tmp_path / "cwd-with-decoys"
    cwd.mkdir()
    for name in ("decoy-a", "decoy-b", "src", "tests"):
        (cwd / name).mkdir()

    suggestions = _bash_complete(repoenv_home=repoenv_home, cwd=cwd, words=words)

    assert {"alpha", "beta", "a"} <= set(suggestions)
    stray_paths = [item for item in suggestions if "decoy" in item or item.startswith(("./", "/"))]
    assert not stray_paths
