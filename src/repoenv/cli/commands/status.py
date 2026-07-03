"""``renv status`` / ``renv doctor`` — environment health report."""

from __future__ import annotations

import json
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.resolve import resolve_environment
from repoenv.services import lifecycle_service
from repoenv.ui import console


def status_command(
    env: Optional[str] = typer.Argument(None, help="Environment name or alias ('-' = cwd)."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Report per-repo health: present/missing worktrees and dirty state."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)
    health = lifecycle_service.assess_health(environment)

    if as_json:
        payload = {
            "environment": environment.name,
            "repos": [
                {
                    "repo": h.repo,
                    "worktree_path": str(h.worktree_path),
                    "present": h.present,
                    "dirty": h.dirty,
                }
                for h in health
            ],
        }
        console.print_data(json.dumps(payload, indent=2))
        return

    console.print_info(f"Environment '{environment.name}':")
    for h in health:
        if not h.present:
            state = "MISSING"
        elif h.dirty:
            state = "DIRTY"
        else:
            state = "OK"
        console.print_info(f"  [{state:<7}] {h.repo} -> {h.worktree_path}")
