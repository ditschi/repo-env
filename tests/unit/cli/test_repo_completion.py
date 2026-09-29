"""Tests for repo-name completion on ``create``/``add --include/--exclude``.

Before this, ``--include``/``--exclude`` had no ``autocompletion=`` at all, so
tab-completing repo names while building an environment wasn't possible, and
there was no "base dir" concept -- this exercises that prefix-completing the
(already recursive, host/org/repo-shaped) discovered repo list gives base-dir
narrowing for free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoenv.adapters import config_store, state_store
from repoenv.cli.completion_helpers import complete_repo_name
from repoenv.domain.models import Environment
from tests.integration.support.gitfixtures import RepoFactory


def _make_source_tree(root: Path) -> Path:
    source = root / "src"
    factory = RepoFactory(root)
    for org, name in (("acme", "svc-alpha"), ("acme", "svc-beta"), ("other", "tool-x")):
        clone = factory.make_bare_and_clone(f"{org}__{name}")
        nested = source / "github.com" / org / name
        nested.parent.mkdir(parents=True, exist_ok=True)
        clone.rename(nested)
    return source


def test_complete_repo_name_lists_discovered_repos(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    ctx = SimpleNamespace(params={"source": str(source)})

    result = complete_repo_name(ctx, "")

    assert "github.com/acme/svc-alpha" in result
    assert "github.com/acme/svc-beta" in result
    assert "github.com/other/tool-x" in result


def test_complete_repo_name_narrows_by_base_dir_prefix(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    ctx = SimpleNamespace(params={"source": str(source)})

    result = complete_repo_name(ctx, "github.com/acme/")

    assert result == ["github.com/acme/svc-alpha", "github.com/acme/svc-beta"]


def test_complete_repo_name_completes_after_comma(tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)
    ctx = SimpleNamespace(params={"source": str(source)})

    result = complete_repo_name(ctx, "github.com/acme/svc-alpha,github.com/other/")

    assert result == ["github.com/acme/svc-alpha,github.com/other/tool-x"]


def test_complete_repo_name_falls_back_to_environment_source_for_add(
    tmp_path: Path, repoenv_home: Path
) -> None:
    source = _make_source_tree(tmp_path)
    env = Environment(name="task", path=tmp_path / "envs" / "task", source=source)
    registry = state_store.load_registry()
    registry.add(env)
    state_store.save_registry(registry)

    ctx = SimpleNamespace(params={"env": "task"})
    result = complete_repo_name(ctx, "github.com/other/")

    assert result == ["github.com/other/tool-x"]


def test_complete_repo_name_no_source_returns_empty(repoenv_home: Path) -> None:
    ctx = SimpleNamespace(params={})
    assert complete_repo_name(ctx, "") == []


def test_complete_repo_name_at_prefix_completes_groups_not_repos(tmp_path: Path, repoenv_home: Path) -> None:
    source = _make_source_tree(tmp_path)
    cfg = config_store.load_config()
    cfg.groups["backend"] = "*/backend-*"
    cfg.groups["frontend"] = "*/frontend-*"
    config_store.save_config(cfg)

    ctx = SimpleNamespace(params={"source": str(source)})
    assert complete_repo_name(ctx, "@") == ["@backend", "@frontend"]
    assert complete_repo_name(ctx, "@back") == ["@backend"]


def test_complete_repo_name_at_prefix_after_comma(tmp_path: Path, repoenv_home: Path) -> None:
    source = _make_source_tree(tmp_path)
    cfg = config_store.load_config()
    cfg.groups["backend"] = "*/backend-*"
    config_store.save_config(cfg)

    ctx = SimpleNamespace(params={"source": str(source)})
    result = complete_repo_name(ctx, "github.com/acme/svc-alpha,@back")
    assert result == ["github.com/acme/svc-alpha,@backend"]


def _bash_complete(*, repoenv_home: Path, cwd: Path, words: str, cword: int, args: list[str]) -> list[str]:
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


def test_bash_completion_suggests_repos_for_create_include(repoenv_home: Path, tmp_path: Path) -> None:
    source = _make_source_tree(tmp_path)

    suggestions = _bash_complete(
        repoenv_home=repoenv_home,
        cwd=tmp_path,
        words=f"renv create task --source {source} --include ",
        cword=6,
        args=["create", "task", "--source", str(source), "--include", ""],
    )

    assert "github.com/acme/svc-alpha" in suggestions
    assert "github.com/other/tool-x" in suggestions
