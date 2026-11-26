from __future__ import annotations

import pytest

from tests.integration.support.renv_helpers import Renv


def test_pr_dry_run(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    renv.setup("alpha")

    # Preview needs neither the GitHub CLI nor provider credentials/network.
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: False)

    renv.ok("create", "env")
    renv.ok("pr", "env", "--title", "test: pr {repo}", "--dry-run")
