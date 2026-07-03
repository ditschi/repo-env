from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import state_store
from repoenv.cli.app import app
from repoenv.domain.models import Environment


def test_merge_requires_existing_source_envs(repoenv_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["merge", "x", "a", "b"])
    assert result.exit_code != 0
    assert result.exception is not None


def test_add_resolves_cwd_environment(repoenv_home: Path, monkeypatch) -> None:
    registry = state_store.Registry()
    env_path = repoenv_home / "envs" / "demo"
    env_path.mkdir(parents=True)
    env = Environment(name="demo", path=env_path, source=repoenv_home / "src")
    registry.add(env)
    state_store.save_registry(registry)

    monkeypatch.chdir(env_path)

    def fake_build_add_plan(*, env, include, exclude, force):
        assert env.name == "demo"

        class _Plan:
            repos = ["r1"]
            skipped = {}

        return _Plan()

    monkeypatch.setattr("repoenv.cli.commands.add.environment_service.build_add_plan", fake_build_add_plan)
    monkeypatch.setattr(
        "repoenv.cli.commands.add.environment_service.execute_add_plan", lambda *args, **kwargs: args[0]
    )

    runner = CliRunner()
    result = runner.invoke(app, ["add", "--dry-run"])
    assert result.exit_code == 0
