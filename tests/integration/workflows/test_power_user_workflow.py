"""End-to-end power-user workflow integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory, run_git
from tests.integration.support.renv_helpers import init_renv


def test_power_user_batch_edit_commit_push_and_pr(
    repo_factory: RepoFactory,
    repoenv_home: Path,
    source_dir: Path,
    worktrees_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("svc-alpha", "svc-beta", "svc-gamma"):
        repo_factory.make_bare_and_clone(name)
    branch = "feature/rollout"

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    create = runner.invoke(
        app,
        ["create", "batch", "--branch", branch, "--include", "svc-*"],
    )
    assert create.exit_code == 0, create.output

    edit = runner.invoke(
        app,
        [
            "run",
            "batch",
            "--",
            "python3",
            "-c",
            "from pathlib import Path; Path('shared.txt').write_text('batch-change\\n', encoding='utf-8')",
        ],
    )
    assert edit.exit_code == 0, edit.output

    commit_msg = "chore: apply shared rollout change"
    commit = runner.invoke(
        app,
        ["run", "batch", "--shell", "--", f"git add -A && git commit -m '{commit_msg}'"],
    )
    assert commit.exit_code == 0, commit.output

    for name in ("svc-alpha", "svc-beta", "svc-gamma"):
        wt = worktrees_dir / "batch" / name
        assert RepoFactory.latest_commit_message(wt) == commit_msg

    for name in ("svc-alpha", "svc-beta", "svc-gamma"):
        wt = worktrees_dir / "batch" / name
        run_git(["push", "-u", "origin", branch], cwd=wt)

    created: list[tuple[str, str]] = []

    def fake_create_pr(worktree, *, title, body, base, head, draft, reviewers, labels, assignees):
        created.append((worktree.name, title))
        return f"https://example.test/{worktree.name}/pull/1"

    monkeypatch.setattr("repoenv.adapters.gh_adapter.is_available", lambda: True)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.existing_pr_url", lambda wt, head: None)
    monkeypatch.setattr("repoenv.adapters.gh_adapter.create_pr", fake_create_pr)

    pr = runner.invoke(
        app,
        ["pr", "batch", "--title", "Rollout {repo}", "--body", "env={env}", "--push"],
    )
    assert pr.exit_code == 0, pr.output
    assert len(created) == 3
    assert created[0][1] == "Rollout svc-alpha"


def test_subset_follow_up_only_touches_marked_repos(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    for name in ("svc-alpha", "svc-beta", "svc-gamma"):
        repo_factory.make_bare_and_clone(name)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert (
        runner.invoke(
            app,
            ["create", "batch", "--branch", "feature/followup", "--include", "svc-*"],
        ).exit_code
        == 0
    )

    beta_head_before = run_git(["rev-parse", "HEAD"], cwd=worktrees_dir / "batch" / "svc-beta").stdout.strip()

    for name in ("svc-alpha", "svc-gamma"):
        (worktrees_dir / "batch" / name / ".needs-followup").write_text("yes\n", encoding="utf-8")

    follow_up = runner.invoke(
        app,
        [
            "run",
            "batch",
            "--shell",
            "--",
            (
                "if [ -f .needs-followup ]; then "
                "echo 'follow-up' >> shared.txt && git add shared.txt .needs-followup && "
                "git commit -m 'chore: follow-up subset'; fi"
            ),
        ],
    )
    assert follow_up.exit_code == 0, follow_up.output

    alpha_head = run_git(["rev-parse", "HEAD"], cwd=worktrees_dir / "batch" / "svc-alpha").stdout.strip()
    beta_head = run_git(["rev-parse", "HEAD"], cwd=worktrees_dir / "batch" / "svc-beta").stdout.strip()
    gamma_head = run_git(["rev-parse", "HEAD"], cwd=worktrees_dir / "batch" / "svc-gamma").stdout.strip()
    assert alpha_head != beta_head_before
    assert gamma_head != beta_head_before
    assert beta_head == beta_head_before
    assert (
        RepoFactory.latest_commit_message(worktrees_dir / "batch" / "svc-alpha") == "chore: follow-up subset"
    )
    assert (
        RepoFactory.latest_commit_message(worktrees_dir / "batch" / "svc-gamma") == "chore: follow-up subset"
    )


def test_same_branch_across_disjoint_envs(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    branch = "feature/shared-name"

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    first = runner.invoke(
        app,
        ["create", "env-a", "--branch", branch, "--include", "alpha"],
    )
    second = runner.invoke(
        app,
        ["create", "env-b", "--branch", branch, "--include", "beta"],
    )
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert RepoFactory.current_branch(worktrees_dir / "env-a" / "alpha") == branch
    assert RepoFactory.current_branch(worktrees_dir / "env-b" / "beta") == branch


def test_mixed_manual_branch_state_then_move_follow_up(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    alpha = repo_factory.make_bare_and_clone("alpha")
    repo_factory.make_bare_and_clone("beta")
    RepoFactory.checkout_branch_in_source(alpha, "feature/mixed")
    branch = "feature/mixed"

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    initial = runner.invoke(app, ["create", "mixed", "--branch", branch])
    assert initial.exit_code == 0, initial.output

    alpha_wt = worktrees_dir / "mixed" / "alpha"
    beta_wt = worktrees_dir / "mixed" / "beta"
    assert RepoFactory.is_detached(alpha_wt) is True
    assert RepoFactory.current_branch(beta_wt) == branch

    meta = json.loads((worktrees_dir / "mixed" / ".repoenv.json").read_text(encoding="utf-8"))
    alpha_entry = next(item for item in meta["environment"]["repos"] if item["repo"] == "alpha")
    assert alpha_entry["note"] is not None
    assert "detached" in alpha_entry["note"].lower()

    run_git(["worktree", "remove", "--force", str(alpha_wt)], cwd=alpha)
    move_result = runner.invoke(
        app,
        [
            "create",
            "mixed-move",
            "--branch",
            branch,
            "--include",
            "alpha",
            "--on-branch-conflict",
            "move",
        ],
    )
    assert move_result.exit_code == 0, move_result.output
    moved_wt = worktrees_dir / "mixed-move" / "alpha"
    assert RepoFactory.current_branch(moved_wt) == branch
    assert RepoFactory.current_branch(alpha) == "main"
