"""Runner service: fan a command out across an environment's worktrees.

Sequential by default (Decision D2); ``jobs > 1`` uses a thread pool since the
work is subprocess/IO-bound. Per-repo environment variables are injected so
commands can introspect their context.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from repoenv.adapters import shell_adapter
from repoenv.domain.models import Environment, RepoEntry, RunResult


def _repo_env(
    base_env: dict[str, str], env: Environment, entry: RepoEntry, index: int, total: int
) -> dict[str, str]:
    merged = dict(base_env)
    merged.update(
        {
            "REPO_NAME": entry.repo,
            "REPO_PATH": str(entry.worktree_path),
            "ENV_PATH": str(env.path),
            "ENV_NAME": env.name,
            "REPO_REMOTE": entry.remote,
            "REPO_BRANCH": entry.branch,
            "REPO_INDEX": str(index),
            "REPO_TOTAL": str(total),
        }
    )
    return merged


def _run_one(
    env: Environment,
    entry: RepoEntry,
    argv: list[str],
    index: int,
    total: int,
    use_shell: bool,
) -> RunResult:
    if not entry.worktree_path.exists():
        return RunResult(
            repo=entry.repo,
            worktree_path=entry.worktree_path,
            exit_code=0,
            duration_s=0.0,
            stderr="worktree path missing; skipped",
            skipped=True,
        )
    child_env = _repo_env(dict(os.environ), env, entry, index, total)
    code, out, err, duration = shell_adapter.run_command(
        argv, cwd=entry.worktree_path, env=child_env, use_shell=use_shell
    )
    return RunResult(
        repo=entry.repo,
        worktree_path=entry.worktree_path,
        exit_code=code,
        duration_s=duration,
        stdout=out,
        stderr=err,
    )


def run_across(
    env: Environment,
    argv: list[str],
    *,
    jobs: int = 1,
    use_shell: bool = False,
) -> list[RunResult]:
    """Run ``argv`` in each worktree and return results ordered by repo name."""
    entries = sorted(env.repos, key=lambda e: e.repo)
    total = len(entries)

    if jobs <= 1:
        return [
            _run_one(env, entry, argv, index, total, use_shell)
            for index, entry in enumerate(entries, start=1)
        ]

    def _task(item: tuple[int, RepoEntry]) -> RunResult:
        index, entry = item
        return _run_one(env, entry, argv, index, total, use_shell)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(_task, enumerate(entries, start=1)))
    return sorted(results, key=lambda r: r.repo)
