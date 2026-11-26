"""``renv status`` / ``renv check`` — environment health report."""

from __future__ import annotations

import json
from typing import Optional

import typer

from repoenv.adapters import state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.domain.models import Environment
from repoenv.services import lifecycle_service
from repoenv.services.lifecycle_service import RepoHealth
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
    if as_json:
        console.print_data(json.dumps(_json_payload(environment, health), indent=2))
        return
    _print_report(environment, health)


def _json_payload(environment: Environment, health: list[RepoHealth]) -> dict[str, object]:
    entry_by_repo = {entry.repo: entry for entry in environment.repos}
    repos: list[dict[str, object]] = []
    for h in health:
        entry = entry_by_repo.get(h.repo)
        repos.append(
            {
                "repo": h.repo,
                "worktree_path": str(h.worktree_path),
                "present": h.present,
                "dirty": h.dirty,
                "status": entry.status.value if entry is not None else "unknown",
                "note": entry.note if entry is not None else None,
            }
        )
    return {"environment": environment.name, "repos": repos}


def _state_label(h: RepoHealth) -> str:
    if not h.present:
        return "MISSING"
    if h.dirty:
        return "DIRTY"
    return "OK"


def _print_report(environment: Environment, health: list[RepoHealth]) -> None:
    console.print_info(f"Environment '{environment.name}':")
    notes = {entry.repo: entry.note for entry in environment.repos}
    for h in health:
        console.print_info(f"  [{_state_label(h):<7}] {h.repo} -> {h.worktree_path}")
        note = notes.get(h.repo)
        if note:
            console.print_info(f"            ↳ {note}")
    if any(not h.present for h in health):
        console.print_info(f"Hint: run 'renv repair {environment.name}' to recreate missing worktree(s).")
