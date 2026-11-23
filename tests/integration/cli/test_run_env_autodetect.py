"""Regression tests for ``renv run`` when the ``[ENV]`` argument is omitted.

``renv run -- CMD...`` (cwd/active-environment autodetect) is the form shown
in the README quickstart. Click discards the literal ``--`` separator before
argument values reach the command callback, so a naive ``env`` + ``command``
argument pair greedily assigns the first token *after* ``--`` to ``env`` when
no env was actually given.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.support.renv_helpers import Renv

_NOT_FOUND = "No environment named or aliased"


def test_run_without_env_autodetects_from_cwd(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    renv.setup("alpha", "beta")
    renv.ok("create", "web", "--include", "alpha,beta")

    monkeypatch.chdir(renv.worktrees / "web")
    output = renv.ok("run", "--", "git", "status").output
    assert _NOT_FOUND not in output
    assert "alpha" in output
    assert "beta" in output


def test_run_without_env_passes_flag_like_command_tokens(
    renv: Renv, web_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(web_env)
    assert _NOT_FOUND not in renv.ok("run", "--", "git", "branch", "--show-current").output


@pytest.mark.usefixtures("web_env")
def test_run_with_explicit_env_before_dashdash_still_works(renv: Renv) -> None:
    assert "alpha" in renv.ok("run", "web", "--", "git", "status").output
