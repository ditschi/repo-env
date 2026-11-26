"""``renv pr --dry-run`` must accurately preview what a real run would do.

Before this, dry-run printed the raw, unrendered {repo}/{branch}/{env}
template and ignored --include/--exclude entirely (always listing every repo
in the environment), so it could show repos that would never actually get a
PR, and never showed what the title/body would actually expand to.
"""

from __future__ import annotations

import pytest

from tests.integration.support.renv_helpers import Renv


def test_pr_dry_run_renders_template_and_respects_include(
    renv: Renv, monkeypatch: pytest.MonkeyPatch
) -> None:
    renv.setup("alpha", "beta")
    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)
    renv.ok("create", "env", "--branch", "feature/x")

    output = renv.ok(
        "pr", "env", "--title", "Rollout {repo} on {branch}", "--include", "alpha", "--dry-run"
    ).output
    assert "would create PRs for 1 repo(s)" in output
    assert "Rollout alpha on feature/x" in output
    assert "beta" not in output
    assert "{repo}" not in output
