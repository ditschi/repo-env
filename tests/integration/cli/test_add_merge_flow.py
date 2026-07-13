from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_repo_pair(tmp_path: Path, name: str) -> Path:
    remotes = tmp_path / "remotes"
    remotes.mkdir(exist_ok=True)
    bare = remotes / f"{name}.git"
    _run(["git", "init", "--bare", str(bare)], cwd=tmp_path)

    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    clone = src / name
    _run(["git", "clone", str(bare), str(clone)], cwd=tmp_path)

    _run(["git", "config", "user.email", "t@t"], cwd=clone)
    _run(["git", "config", "user.name", "t"], cwd=clone)
    (clone / "README.md").write_text(name, encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=clone)
    _run(["git", "commit", "-m", "init"], cwd=clone)
    _run(["git", "push", "origin", "HEAD:main"], cwd=clone)
    return clone


@pytest.mark.integration
def test_add_and_merge_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "src"
    dest = tmp_path / "envs"

    _make_repo_pair(tmp_path, "alpha")
    _make_repo_pair(tmp_path, "beta")
    _make_repo_pair(tmp_path, "gamma")

    home = tmp_path / "repoenv-home"
    home.mkdir()
    monkeypatch.setenv("REPOENV_HOME", str(home))

    runner = CliRunner()
    assert runner.invoke(app, ["init", "-y", "--source", str(source), "--dest", str(dest)]).exit_code == 0
    assert runner.invoke(app, ["create", "a", "--include", "alpha"]).exit_code == 0
    assert runner.invoke(app, ["new", "b", "--include", "beta"]).exit_code == 0

    add_result = runner.invoke(app, ["add", "a", "--include", "gamma"])
    assert add_result.exit_code == 0
    assert (dest / "a" / "gamma" / ".git").exists()

    merge_result = runner.invoke(app, ["merge", "ab", "a", "b", "--op", "union"])
    assert merge_result.exit_code == 0
    assert (dest / "ab" / "alpha" / ".git").exists()
    assert (dest / "ab" / "beta" / ".git").exists()
    assert (dest / "ab" / "gamma" / ".git").exists()
