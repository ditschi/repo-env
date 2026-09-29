"""``renv run`` — run a command across an environment's worktrees."""

from __future__ import annotations

import json
from typing import Optional

import typer
from typer.core import TyperCommand

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.summary import aggregate_exit_code
from repoenv.errors import UsageError
from repoenv.services import runner
from repoenv.ui import console

_RAW_ARGS_KEY = "repoenv_raw_args"


class RunCommand(TyperCommand):
    """Stashes the pre-parse argv so the callback can fix up ``[ENV] -- CMD``.

    Click's parser treats a bare ``--`` purely as "stop parsing options" and
    discards the token itself before argument values reach the callback. With
    ``env`` (an optional single-value Argument) declared before ``command``
    (a variadic Argument), Click always fills ``env`` from the first leftover
    positional token -- including one that came *after* ``--`` when no env
    was actually given, e.g. ``renv run -- git status`` would otherwise parse
    as env='git', command=['status']. Saving the raw args lets
    ``_split_env_and_command`` detect and correct that.
    """

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:  # type: ignore[override]
        ctx.meta[_RAW_ARGS_KEY] = list(args)
        return super().parse_args(ctx, args)


def _split_env_and_command(
    ctx: typer.Context, env: Optional[str], command: list[str]
) -> tuple[Optional[str], list[str]]:
    """Correct Click's env/command split using the raw pre-parse argv.

    If ``env`` was actually the first token *after* the ``--`` separator
    (i.e. no env was given on the command line), push it back onto the
    front of ``command`` and report no env, so cwd/active-environment
    autodetection takes over as documented.
    """
    if env is None:
        return env, command
    raw_args = ctx.meta.get(_RAW_ARGS_KEY)
    if not raw_args or "--" not in raw_args:
        return env, command
    before_dashdash = raw_args[: raw_args.index("--")]
    if env in before_dashdash:
        return env, command
    return None, [env, *command]


def run_command(
    ctx: typer.Context,
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    command: Optional[list[str]] = typer.Argument(None, help="Command after '--'."),
    jobs: int = typer.Option(1, "--jobs", "-j", min=1, help="Parallel workers (default 1 = sequential)."),
    include: list[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    use_shell: bool = typer.Option(False, "--shell", help="Run via the shell (enables pipes/globs)."),
    as_json: bool = typer.Option(False, "--json", help="Emit per-repo results as JSON to stdout."),
) -> None:
    """Run ``-- CMD`` in every worktree of an environment."""
    env, command = _split_env_and_command(ctx, env, list(command or []))
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
