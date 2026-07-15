"""``renv status`` / ``renv check`` — environment health report."""

from __future__ import annotations

import json
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.services import lifecycle_service
from repoenv.ui import console


def status_command(
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Report per-repo health: present/missing worktrees and dirty state."""
    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)
    health = lifecycle_service.assess_health(environment)
    entry_by_repo = {entry.repo: entry for entry in environment.repos}

    if as_json:
        payload = {
            "environment": environment.name,
            "repos": [
                {
                    "repo": h.repo,
                    "worktree_path": str(h.worktree_path),
                    "present": h.present,
                    "dirty": h.dirty,
                    "status": entry_by_repo[h.repo].status.value if h.repo in entry_by_repo else "unknown",
                    "note": entry_by_repo[h.repo].note if h.repo in entry_by_repo else None,
                }
                for h in health
            ],
        }
        console.print_data(json.dumps(payload, indent=2))
        return

    console.print_info(f"Environment '{environment.name}':")
    missing: list[str] = []
    for h in health:
        if not h.present:
            state = "MISSING"
            missing.append(h.repo)
        elif h.dirty:
            state = "DIRTY"
        else:
            state = "OK"
        console.print_info(f"  [{state:<7}] {h.repo} -> {h.worktree_path}")
    if missing:
        console.print_info(f"Hint: run 'renv repair {environment.name}' to recreate missing worktree(s).")
