"""``renv select`` — interactive picker: choose an environment, then an action.

Arrow-key driven wrapper around existing commands (see ``_ACTIONS`` below); it
does no work of its own beyond prompting and dispatch, so every action stays
covered by that command's own tests. Prompting is isolated behind
``_ask_environment``/``_ask_action`` (same shape as ``init.py``'s
``_ask_path``/``_ask_text``) so tests can monkeypatch the boundary instead of
driving a real terminal.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional, Tuple

import typer

from repoenv.adapters import state_store
from repoenv.cli.commands.activate import activate_command
from repoenv.cli.commands.path import path_command
from repoenv.cli.commands.rm import rm_command
from repoenv.cli.commands.sh import sh_command
from repoenv.cli.commands.status import status_command
from repoenv.cli.commands.sync import sync_command
from repoenv.domain.models import Environment
from repoenv.errors import UsageError
from repoenv.ui import console

Handler = Callable[[str], None]


def _remove(name: str) -> None:
    import questionary

    confirmed = questionary.confirm(
        f"Remove environment '{name}'? This deletes its worktrees.",
        default=False,
    ).unsafe_ask()
    if not confirmed:
        console.print_info("Cancelled.")
        return
    # Typer resolves `rm_command`'s other defaults (typer.Option(...) sentinels)
    # only when invoked through the CLI, so every parameter must be passed
    # explicitly here to get the same behavior as plain `renv rm <name>`.
    rm_command(env=name, delete_files=True, force=False, dry_run=False)


# (key, description, handler) — order is the order shown in the action prompt.
_ACTIONS: List[Tuple[str, str, Handler]] = [
    ("status", "Show health status", lambda name: status_command(env=name, as_json=False)),
    ("activate", "Set as the default active environment", lambda name: activate_command(name=name)),
    ("sh", "Open a subshell in this environment", lambda name: sh_command(env=name)),
    ("sync", "Fetch remote updates for each repo", lambda name: sync_command(env=name)),
    ("path", "Print the environment path", lambda name: path_command(env=name, repo=None)),
    ("rm", "Remove this environment", _remove),
]


def select_command() -> None:
    """Pick an environment and an action with arrow keys instead of flags."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UsageError(
            "'renv select' needs an interactive terminal.",
            hint="Use 'renv ls' or a direct subcommand in scripts/CI.",
        )

    registry = state_store.load_registry()
    environments = registry.list()
    if not environments:
        console.print_info("No environments yet. Create one with 'renv create'.")
        return

    try:
        env_name = _ask_environment(environments)
        action_key = _ask_action()
    except KeyboardInterrupt:
        console.print_info("Cancelled.")
        raise typer.Exit(code=130) from None

    handler = next(fn for key, _, fn in _ACTIONS if key == action_key)
    handler(env_name)


def _ask_environment(environments: List[Environment]) -> str:
    import questionary

    choices = [
        questionary.Choice(
            title=f"{env.name}  ({len(env.repos)} repo(s)) - {env.path}",
            value=env.name,
        )
        for env in environments
    ]
    answer: Optional[str] = questionary.select("Pick an environment:", choices=choices).unsafe_ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


def _ask_action() -> str:
    import questionary

    choices = [questionary.Choice(title=f"{key} - {desc}", value=key) for key, desc, _ in _ACTIONS]
    answer: Optional[str] = questionary.select("Pick an action:", choices=choices).unsafe_ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer
