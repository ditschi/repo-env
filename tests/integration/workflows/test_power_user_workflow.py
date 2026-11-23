"""End-to-end power-user workflow integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.support import gitfixtures
from tests.integration.support.gitfixtures import run_git
from tests.integration.support.renv_helpers import Renv, env_meta

_SERVICES = ("svc-alpha", "svc-beta", "svc-gamma")


def _batch_of_services(renv: Renv, branch: str) -> Path:
    """Create env ``batch`` on ``branch`` with all ``svc-*`` repos; returns its directory."""
    renv.setup(*_SERVICES)
    renv.ok("create", "batch", "--branch", branch, "--include", "svc-*")
    return renv.worktrees / "batch"


def _point_origin_at_github_keep_local_push(renv: Renv, worktree: Path, branch: str) -> None:
    """Push ``branch`` to the local bare remote, then make origin look like GitHub for ``renv pr``."""
    run_git(["push", "-u", "origin", branch], cwd=worktree)
    bare = renv.repos.remotes / f"{worktree.name}.git"
    run_git(["remote", "set-url", "--push", "origin", str(bare)], cwd=worktree)
    run_git(["remote", "set-url", "origin", f"git@github.com:example/{worktree.name}.git"], cwd=worktree)


def _head(worktree: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()


def test_power_user_batch_edit_commit_push_and_pr(renv: Renv, monkeypatch: pytest.MonkeyPatch) -> None:
    branch = "feature/rollout"
    batch = _batch_of_services(renv, branch)

    write_shared = (
        "from pathlib import Path; Path('shared.txt').write_text('batch-change\\n', encoding='utf-8')"
    )
    renv.ok("run", "batch", "--", "python3", "-c", write_shared)

    commit_msg = "chore: apply shared rollout change"
    renv.ok("run", "batch", "--shell", "--", f"git add -A && git commit -m '{commit_msg}'")

    for name in _SERVICES:
        assert gitfixtures.latest_commit_message(batch / name) == commit_msg

    for name in _SERVICES:
        _point_origin_at_github_keep_local_push(renv, batch / name, branch)

    created: list[tuple[str, str]] = []

    def fake_create_pr(worktree, pull_request, *, repository):
        assert repository == f"github.com/example/{worktree.name}"
        created.append((worktree.name, pull_request.title))
        return f"https://example.test/{worktree.name}/pull/1"

    def fake_existing_pr_url(worktree, *, head, repository):
        assert head == branch
        assert repository == f"github.com/example/{worktree.name}"
        return None

    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.existing_pr_url", fake_existing_pr_url)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.create_pr", fake_create_pr)

    renv.ok("pr", "batch", "--title", "Rollout {repo}", "--body", "env={env}", "--push")
    assert len(created) == 3
    assert created[0][1] == "Rollout svc-alpha"


def test_subset_follow_up_only_touches_marked_repos(renv: Renv) -> None:
    batch = _batch_of_services(renv, "feature/followup")
    beta_head_before = _head(batch / "svc-beta")

    marked = ("svc-alpha", "svc-gamma")
    for name in marked:
        (batch / name / ".needs-followup").write_text("yes\n", encoding="utf-8")

    follow_up = (
        "if [ -f .needs-followup ]; then "
        "echo 'follow-up' >> shared.txt && git add shared.txt .needs-followup && "
        "git commit -m 'chore: follow-up subset'; fi"
    )
    renv.ok("run", "batch", "--shell", "--", follow_up)

    heads = {name: _head(batch / name) for name in _SERVICES}
    assert {name for name, head in heads.items() if head != beta_head_before} == set(marked)
    marked_messages = {name: gitfixtures.latest_commit_message(batch / name) for name in marked}
    assert marked_messages == dict.fromkeys(marked, "chore: follow-up subset")


def test_same_branch_across_disjoint_envs(renv: Renv) -> None:
    renv.setup("alpha", "beta")
    branch = "feature/shared-name"

    first = renv.invoke("create", "env-a", "--branch", branch, "--include", "alpha")
    second = renv.invoke("create", "env-b", "--branch", branch, "--include", "beta")
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    branches = (
        gitfixtures.current_branch(renv.worktrees / "env-a" / "alpha"),
        gitfixtures.current_branch(renv.worktrees / "env-b" / "beta"),
    )
    assert branches == (branch, branch)


def test_mixed_manual_branch_state_then_move_follow_up(renv: Renv) -> None:
    branch = "feature/mixed"
    alpha, _ = renv.setup("alpha", "beta")
    gitfixtures.checkout_branch_in_source(alpha, branch)

    renv.ok("create", "mixed", "--branch", branch)

    alpha_wt = renv.worktrees / "mixed" / "alpha"
    assert gitfixtures.is_detached(alpha_wt) is True
    assert gitfixtures.current_branch(renv.worktrees / "mixed" / "beta") == branch

    repos = env_meta(renv.worktrees / "mixed")["environment"]["repos"]
    alpha_entry = next(item for item in repos if item["repo"] == "alpha")
    assert alpha_entry["note"] is not None
    assert "detached" in alpha_entry["note"].lower()

    run_git(["worktree", "remove", "--force", str(alpha_wt)], cwd=alpha)
    renv.ok("create", "mixed-move", "--branch", branch, "--include", "alpha", "--on-branch-conflict", "move")
    assert gitfixtures.current_branch(renv.worktrees / "mixed-move" / "alpha") == branch
    assert gitfixtures.current_branch(alpha) == "main"
