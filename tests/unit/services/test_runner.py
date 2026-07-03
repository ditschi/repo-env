from __future__ import annotations

from pathlib import Path

from repoenv.domain.models import Environment, RepoEntry
from repoenv.services import runner


def test_run_across_injects_env(monkeypatch) -> None:
    env = Environment(name="env1", path=Path("/tmp/env1"), source=Path("/tmp/src"))
    env.repos.append(
        RepoEntry(repo="alpha", worktree_path=Path("/tmp/env1/alpha"), base="main", branch="main")
    )

    captured = {}

    def fake_run(argv, *, cwd, env, use_shell):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["env"] = env
        captured["use_shell"] = use_shell
        return 0, "ok", "", 0.01

    monkeypatch.setattr(runner.shell_adapter, "run_command", fake_run)
    monkeypatch.setattr(Path, "exists", lambda self: True)

    results = runner.run_across(env, ["git", "status"], jobs=1)
    assert len(results) == 1
    assert results[0].exit_code == 0
    assert captured["argv"] == ["git", "status"]
    assert captured["env"]["ENV_NAME"] == "env1"
    assert captured["env"]["REPO_NAME"] == "alpha"
