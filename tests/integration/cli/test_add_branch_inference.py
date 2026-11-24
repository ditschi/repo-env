"""``renv add`` without ``--branch`` should join the environment's existing task branch.

Before this behavior, a repo added later to an environment created with
``--branch feature/x`` landed detached at the default branch instead of on
``feature/x`` unless the caller remembered to repeat ``--branch`` by hand.
"""

from __future__ import annotations

from tests.integration.support import gitfixtures
from tests.integration.support.renv_helpers import Renv


def _add_beta_to_task_env(renv: Renv, env_branch: str, *add_opts: str) -> str | None:
    """Create env ``task`` on ``env_branch`` with alpha, add beta; returns beta's current branch."""
    renv.setup("alpha", "beta")
    renv.ok("create", "task", "--branch", env_branch, "--include", "alpha")
    renv.ok("add", "task", "--include", "beta", *add_opts)
    return gitfixtures.current_branch(renv.worktrees / "task" / "beta")


def test_add_without_branch_reuses_environment_task_branch(renv: Renv) -> None:
    assert _add_beta_to_task_env(renv, "feature/rollout") == "feature/rollout"


def test_add_explicit_branch_still_overrides_inference(renv: Renv) -> None:
    assert _add_beta_to_task_env(renv, "feature/a", "--branch", "feature/b") == "feature/b"
