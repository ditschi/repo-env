"""Console reporting and selection helpers shared by ``renv create``/``add``/``repair``/``rm``."""

from __future__ import annotations

from repoenv.adapters import config_store
from repoenv.domain.models import Environment
from repoenv.errors import PartialFailureError
from repoenv.services import environment_service
from repoenv.ui import console


def expand_selection(include: list[str], exclude: list[str]) -> tuple[list[str], list[str]]:
    """Expand ``@group`` references in ``--include``/``--exclude`` using the user config."""
    groups = config_store.load_config().groups
    return (
        environment_service.expand_repo_groups(include, groups),
        environment_service.expand_repo_groups(exclude, groups),
    )


def print_skipped_worktrees(skipped: list[str]) -> None:
    """Mention linked worktrees left out of a plan (if any)."""
    if skipped:
        console.print_info(f"Skipped {len(skipped)} git worktree(s) (use --include-worktrees to include).")


def print_progress(repo: str, current: int, total: int) -> None:
    """Per-repo progress line; an ``ExecuteOptions.on_repo_start`` callback."""
    console.print_info(f"  [{current}/{total}] {repo}")


def print_activate_hint(name: str, *, activate: bool, active_set: bool) -> None:
    """Suggest ``renv activate`` when no default environment is (or will be) set."""
    if not activate and not active_set:
        console.print_info(f"Hint: run 'renv activate {name}' to set it as the default.")


def raise_on_failures(env: Environment) -> None:
    """Raise :class:`PartialFailureError` listing every failed repo of *env*."""
    if not environment_service.failed_repos(env):
        return
    details = environment_service.failure_details(env)
    lines = "\n".join(f"  {repo}: {note or 'unknown error'}" for repo, note in details)
    raise PartialFailureError(
        f"Some repositories failed:\n{lines}",
        hint="Run 'renv repair' or 'renv status' to see which worktrees are missing or failed.",
    )
