from __future__ import annotations

from tests.integration.support.renv_helpers import Renv, env_meta


def test_create_creates_worktrees(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    renv.ok("create", "feat", "--branch", "feature/x")

    # Keep compatibility alias covered.
    renv.ok("new", "compat", "--dry-run")

    feat = renv.worktrees / "feat"
    assert (feat / "alpha" / ".git").exists()
    assert (feat / "beta" / ".git").exists()
    assert (feat / ".repoenv.json").exists()
    meta_data = env_meta(feat)
    assert "environment" in meta_data
    assert meta_data["environment"]["name"] == "feat"
    marker = meta_data["marker"]
    assert marker["kind"] == "repo-env-marker"
    assert marker["environment_name"] == "feat"
    assert marker["command"]["name"] == "create"
    assert "renv create feat" in marker["command"]["recreate"]
