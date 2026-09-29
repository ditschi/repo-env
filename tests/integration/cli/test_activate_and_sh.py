"""``renv activate`` and ``renv sh`` had zero CLI-level test coverage.

These are the daily-driver commands behind "no need to type the env name
every time": ``activate`` sets the persisted default, ``sh`` opens a subshell
scoped to one environment. The precedence rule (cwd-inside-an-env beats the
activated one) lives in ``resolve_environment`` and is unit-tested there, but
nothing previously exercised it end-to-end through these two commands -- the
same blind spot that let the ``renv run`` ``--`` parsing bug ship.
"""

from __future__ import annotations

import stat
from pathlib import Path

from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_activate_is_used_when_no_env_given_and_cwd_is_outside_any_env(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "a", "--include", "alpha"]).exit_code == 0
    assert runner.invoke(app, ["create", "b", "--include", "beta"]).exit_code == 0

    assert runner.invoke(app, ["activate", "a"]).exit_code == 0

    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Environment 'a':" in result.output

    # switching the active environment changes the default
    assert runner.invoke(app, ["activate", "b"]).exit_code == 0
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Environment 'b':" in result.output


def test_cwd_inside_an_env_wins_over_the_activated_one(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path, monkeypatch
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "a", "--include", "alpha"]).exit_code == 0
    assert runner.invoke(app, ["create", "b", "--include", "beta"]).exit_code == 0
    assert runner.invoke(app, ["activate", "b"]).exit_code == 0

    monkeypatch.chdir(worktrees_dir / "a")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Environment 'a':" in result.output
    assert "active: 'b'" in result.output


def test_sh_scopes_env_vars_and_cwd_to_the_environment(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["create", "web", "--include", "alpha"]).exit_code == 0

    capture = tmp_path / "capture.txt"
    fake_shell = tmp_path / "fake_shell.sh"
    fake_shell.write_text(
        "#!/bin/sh\n"
        'printf "ENV_NAME=%s\\n" "$ENV_NAME" > "$RENV_TEST_CAPTURE"\n'
        'printf "ENV_PATH=%s\\n" "$ENV_PATH" >> "$RENV_TEST_CAPTURE"\n'
        'printf "REPOENV_ACTIVE=%s\\n" "$REPOENV_ACTIVE" >> "$RENV_TEST_CAPTURE"\n'
        'printf "PWD=%s\\n" "$(pwd)" >> "$RENV_TEST_CAPTURE"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_shell.chmod(fake_shell.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("SHELL", str(fake_shell))
    monkeypatch.setenv("RENV_TEST_CAPTURE", str(capture))

    result = runner.invoke(app, ["sh", "web"])
    assert result.exit_code == 0, result.output

    lines = dict(line.split("=", 1) for line in capture.read_text(encoding="utf-8").splitlines())
    assert lines["ENV_NAME"] == "web"
    assert lines["ENV_PATH"] == str(worktrees_dir / "web")
    assert lines["REPOENV_ACTIVE"] == "web"
    assert Path(lines["PWD"]).resolve() == (worktrees_dir / "web").resolve()
