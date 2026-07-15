from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repoenv.adapters import config_store, state_store
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

    def fake_build_add_plan(*, env, include, exclude):
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
    assert "Hint: run 'renv activate demo'" in result.output


def test_create_dry_run_shows_activate_hint(repoenv_home: Path, monkeypatch) -> None:
    source = repoenv_home / "src"
    dest = repoenv_home / "envs"
    source.mkdir()
    dest.mkdir()
    config_store.save_config(config_store.UserConfig(source=source, dest=dest))

    def fake_build_create_plan(**kwargs):
        class _Plan:
            name = kwargs["name"]
            env_path = dest / kwargs["name"]
            repos = ["r1"]

        return _Plan()

    monkeypatch.setattr(
        "repoenv.cli.commands.create.environment_service.build_create_plan",
        fake_build_create_plan,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["create", "web", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run: no changes made." in result.output
    assert "Hint: run 'renv activate web'" in result.output
