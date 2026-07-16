"""``renv run`` — run a command across an environment's worktrees."""

from __future__ import annotations

import json
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.passthrough import get_passthrough_args
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.summary import aggregate_exit_code
from repoenv.errors import UsageError
from repoenv.services import runner
from repoenv.ui import console


def run_command(
    ctx: typer.Context,
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    jobs: int = typer.Option(1, "--jobs", "-j", min=1, help="Parallel workers (default 1 = sequential)."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    use_shell: bool = typer.Option(False, "--shell", help="Run via the shell (enables pipes/globs)."),
    as_json: bool = typer.Option(False, "--json", help="Emit per-repo results as JSON to stdout."),
) -> None:
    """Run ``-- CMD`` in every worktree of an environment.

    Everything after the first ``--`` is the command, verbatim -- it is never
    matched against ``ENV`` or any option, so omitting ``ENV`` (e.g.
    ``renv run -- git status``) correctly falls back to environment
    resolution instead of mistaking the command's first word for ``ENV``.
    """
    command = get_passthrough_args(ctx)
    if not command:
        raise UsageError(
            "No command given.",
            hint="Put the command after '--', e.g. renv run web -- git status.",
        )

    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)
    results = runner.run_across(
        environment,
        list(command),
        jobs=jobs,
        use_shell=use_shell,
        include=include or None,
        exclude=exclude or None,
    )

    if as_json:
        payload = [r.model_dump(mode="json") for r in results]
        console.print_data(json.dumps(payload, indent=2))
    else:
        console.render_run_results(results)

    raise typer.Exit(code=int(aggregate_exit_code(results)))
