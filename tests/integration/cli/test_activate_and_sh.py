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

import pytest

from tests.integration.support.renv_helpers import Renv

_CAPTURING_SHELL = (
    "#!/bin/sh\n"
    'printf "ENV_NAME=%s\\n" "$ENV_NAME" > "$RENV_TEST_CAPTURE"\n'
    'printf "ENV_PATH=%s\\n" "$ENV_PATH" >> "$RENV_TEST_CAPTURE"\n'
    'printf "REPOENV_ACTIVE=%s\\n" "$REPOENV_ACTIVE" >> "$RENV_TEST_CAPTURE"\n'
    'printf "PWD=%s\\n" "$(pwd)" >> "$RENV_TEST_CAPTURE"\n'
    "exit 0\n"
)


@pytest.fixture()
def envs_a_b(renv: Renv) -> Renv:
    """Environments ``a`` (repo ``alpha``) and ``b`` (repo ``beta``)."""
    renv.setup("alpha", "beta")
    renv.ok("create", "a", "--include", "alpha")
    renv.ok("create", "b", "--include", "beta")
    return renv


def _install_capturing_shell(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make ``$SHELL`` a script that dumps the env vars it sees; returns the capture file."""
    fake_shell = directory / "fake_shell.sh"
    fake_shell.write_text(_CAPTURING_SHELL, encoding="utf-8")
    fake_shell.chmod(fake_shell.stat().st_mode | stat.S_IEXEC)
    capture = directory / "capture.txt"
    monkeypatch.setenv("SHELL", str(fake_shell))
    monkeypatch.setenv("RENV_TEST_CAPTURE", str(capture))
    return capture


def test_activate_is_used_when_no_env_given_and_cwd_is_outside_any_env(
    envs_a_b: Renv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envs_a_b.ok("activate", "a")

    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert "Environment 'a':" in envs_a_b.ok("status").output

    # switching the active environment changes the default
    envs_a_b.ok("activate", "b")
    assert "Environment 'b':" in envs_a_b.ok("status").output


def test_cwd_inside_an_env_wins_over_the_activated_one(
    envs_a_b: Renv, monkeypatch: pytest.MonkeyPatch
) -> None:
    envs_a_b.ok("activate", "b")

    monkeypatch.chdir(envs_a_b.worktrees / "a")
    output = envs_a_b.ok("status").output
    assert "Environment 'a':" in output
    assert "active: 'b'" in output


def test_sh_scopes_env_vars_and_cwd_to_the_environment(
    renv: Renv, web_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _install_capturing_shell(tmp_path, monkeypatch)

    renv.ok("sh", "web")

    lines = dict(line.split("=", 1) for line in capture.read_text(encoding="utf-8").splitlines())
    assert lines["ENV_NAME"] == "web"
    assert lines["ENV_PATH"] == str(web_env)
    assert lines["REPOENV_ACTIVE"] == "web"
    assert Path(lines["PWD"]).resolve() == web_env.resolve()
