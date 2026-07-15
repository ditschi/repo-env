from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.domain.models import Environment


def test_path_writes_only_path_to_stdout(repoenv_home: Path) -> None:
    registry = state_store.Registry()
    env = Environment(name="demo", path=Path("/tmp/demo"), source=Path("/tmp/src"))
    registry.add(env)
    state_store.save_registry(registry)

    runner = CliRunner()
    result = runner.invoke(app, ["path", "demo"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "/tmp/demo"
