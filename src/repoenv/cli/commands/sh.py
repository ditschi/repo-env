"""``renv sh`` — spawn an interactive subshell scoped to an environment.

Sets ``ENV_NAME``/``ENV_PATH`` and a loud prompt marker so the user always
knows they are inside a repo-env context. POSIX-focused; uses ``$SHELL``.
"""

from __future__ import annotations

import os
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.ui import console


def sh_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
) -> None:
    """Open an interactive subshell with the environment context loaded."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    shell = os.environ.get("SHELL", "/bin/sh")
    child_env = dict(os.environ)
    marker = f"(renv:{environment.name} x{len(environment.repos)})"
    child_env.update(
        {
            "ENV_NAME": environment.name,
            "ENV_PATH": str(environment.path),
            "REPOENV_ACTIVE": environment.name,
            "PROMPT_COMMAND": "",
            "PS1": marker + " \\w $ ",
        }
    )

    console.print_info(f"Entering subshell for '{environment.name}'. Type 'exit' to leave.")
    cwd = environment.path if environment.path.exists() else None
    completed = (
        os.spawnve(os.P_WAIT, shell, [shell], child_env) if cwd is None else _spawn_in(shell, child_env, cwd)
    )
    console.print_info(f"Left subshell for '{environment.name}' (exit {completed}).")
    raise typer.Exit(code=completed if completed else 0)


def _spawn_in(shell: str, child_env: dict[str, str], cwd: "os.PathLike[str]") -> int:
    prev = os.getcwd()
    os.chdir(cwd)
    try:
        return os.spawnve(os.P_WAIT, shell, [shell], child_env)
    finally:
        os.chdir(prev)
