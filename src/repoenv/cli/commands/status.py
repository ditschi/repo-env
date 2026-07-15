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
    entry_by_path = {str(entry.worktree_path): entry for entry in environment.repos}

    if as_json:
        payload = {
            "environment": environment.name,
            "repos": [
                {
                    "repo": h.repo,
                    "worktree": h.worktree_path.name,
                    "branch": (
                        entry_by_path[str(h.worktree_path)].branch
                        if str(h.worktree_path) in entry_by_path
                        else None
                    ),
                    "worktree_path": str(h.worktree_path),
                    "present": h.present,
                    "dirty": h.dirty,
                    "status": (
                        entry_by_path[str(h.worktree_path)].status.value
                        if str(h.worktree_path) in entry_by_path
                        else "unknown"
                    ),
                    "note": (
                        entry_by_path[str(h.worktree_path)].note
                        if str(h.worktree_path) in entry_by_path
                        else None
                    ),
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
            missing.append(h.worktree_path.name)
        elif h.dirty:
            state = "DIRTY"
        else:
            state = "OK"
        entry = entry_by_path.get(str(h.worktree_path))
        label = h.worktree_path.name
        branch = f" ({entry.branch})" if entry is not None else ""
        console.print_info(f"  [{state:<7}] {label}{branch} -> {h.worktree_path}")
    if missing:
        console.print_info(f"Hint: run 'renv repair {environment.name}' to recreate missing worktree(s).")
