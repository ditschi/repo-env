from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import config_store, state_store
from repoenv.cli.app import app
from repoenv.domain.models import Environment


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "repo-env" in result.stdout


def test_ls_empty(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_path_prints_stdout_only(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))
    registry.add(env)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["path", "demo"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "/tmp/demo"


def test_init_non_interactive(repoenv_home: Path) -> None:
    runner = CliRunner()
    source = repoenv_home / "src"
    dest = repoenv_home / "envs"
    result = runner.invoke(app, ["init", "-y", "--source", str(source), "--dest", str(dest)])
    assert result.exit_code == 0
    cfg = config_store.load_config()
    assert cfg.source == source
    assert cfg.dest == dest
