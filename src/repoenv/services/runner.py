"""Runner service: fan a command out across an environment's worktrees.

Sequential by default (Decision D2); ``jobs > 1`` uses a thread pool since the
work is subprocess/IO-bound. Per-repo environment variables are injected so
commands can introspect their context.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from repoenv.adapters import shell_adapter
from repoenv.domain.models import Environment, RepoEntry, RunResult
from repoenv.domain.selection import resolve_selection


@dataclass(frozen=True)
class _RunContext:
    """What every per-repo run shares."""

    env: Environment
    argv: list[str]
    total: int
    use_shell: bool


def _repo_env(ctx: _RunContext, entry: RepoEntry, index: int) -> dict[str, str]:
    merged = dict(os.environ)
    merged.update(
        {
            "REPO_NAME": entry.repo,
            "REPO_PATH": str(entry.worktree_path),
            "ENV_PATH": str(ctx.env.path),
            "ENV_NAME": ctx.env.name,
            "REPO_REMOTE": entry.remote,
            "REPO_BRANCH": entry.branch,
            "REPO_INDEX": str(index),
            "REPO_TOTAL": str(ctx.total),
        }
    )
    return merged


def _run_one(ctx: _RunContext, index: int, entry: RepoEntry) -> RunResult:
    if not entry.worktree_path.exists():
        return RunResult(
            repo=entry.repo,
            worktree_path=entry.worktree_path,
            exit_code=0,
            duration_s=0.0,
            stderr="worktree path missing; skipped",
            skipped=True,
        )
    child_env = _repo_env(ctx, entry, index)
    code, out, err, duration = shell_adapter.run_command(
        ctx.argv, cwd=entry.worktree_path, env=child_env, use_shell=ctx.use_shell
    )
    return RunResult(
        repo=entry.repo,
        worktree_path=entry.worktree_path,
        exit_code=code,
        duration_s=duration,
        stdout=out,
        stderr=err,
    )


@dataclass(frozen=True)
class RunOptions:
    """How ``run_across`` executes: parallelism, shell mode and repo selection."""

    jobs: int = 1
    use_shell: bool = False
    include: list[str] | None = None
    exclude: list[str] | None = None


def run_across(env: Environment, argv: list[str], options: RunOptions | None = None) -> list[RunResult]:
    """Run ``argv`` in each worktree and return results ordered by repo name."""
    options = options or RunOptions()
    jobs = options.jobs
    entries = sorted(env.repos, key=lambda e: e.repo)
    if options.include is not None or options.exclude is not None:
        names = [e.repo for e in entries]
        selected = set(resolve_selection(names, include=options.include, exclude=options.exclude))
        entries = [e for e in entries if e.repo in selected]
    ctx = _RunContext(env=env, argv=argv, total=len(entries), use_shell=options.use_shell)

    if jobs <= 1:
        return [_run_one(ctx, index, entry) for index, entry in enumerate(entries, start=1)]

    def _task(item: tuple[int, RepoEntry]) -> RunResult:
        return _run_one(ctx, *item)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(_task, enumerate(entries, start=1)))
    return sorted(results, key=lambda r: r.repo)
