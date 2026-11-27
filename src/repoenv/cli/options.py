"""Shared typer argument/option declarations for commands that take the same CLI options.

Each factory returns a fresh typer ``ArgumentInfo``/``OptionInfo`` (typed ``Any`` like
``typer.Argument``/``typer.Option`` themselves) so commands keep declaring every option as a
parameter while the declaration lives in one place.
"""

from __future__ import annotations

from typing import Any

import typer

from repoenv.cli.completion_helpers import complete_env_name, complete_repo_name
from repoenv.services import environment_service

_INCLUDE_HELP = "Glob(s) of repos to include."
_EXCLUDE_HELP = "Glob(s) of repos to exclude."


def env_argument() -> Any:
    """The optional ``[ENV]`` argument: a name, alias, or ``-`` for the cwd."""
    return typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    )


def include_option() -> Any:
    """``--include/-i`` with repo-name completion."""
    return typer.Option([], "--include", "-i", help=_INCLUDE_HELP, autocompletion=complete_repo_name)


def exclude_option() -> Any:
    """``--exclude/-x`` with repo-name completion."""
    return typer.Option([], "--exclude", "-x", help=_EXCLUDE_HELP, autocompletion=complete_repo_name)


def branch_option() -> Any:
    """``--branch/-b``: the new task branch to create and check out."""
    return typer.Option(None, "--branch", "-b", help="Create and check out this new branch.")


def on_branch_conflict_option() -> Any:
    """``--on-branch-conflict`` defaulting to ``detach``."""
    return typer.Option(
        environment_service.BranchConflictStrategy.DETACH,
        "--on-branch-conflict",
        help="When the target branch is already checked out elsewhere: detach|move|fail.",
    )


def include_worktrees_option() -> Any:
    """``--include-worktrees``: also pick up git linked worktrees under the source."""
    return typer.Option(
        False,
        "--include-worktrees",
        help="Include git linked worktrees found under the source directory.",
    )


def preserve_option() -> Any:
    """``--preserve``: skip fetch/update of the source repos."""
    return typer.Option(False, "--preserve", help="Skip fetch/update; use source repos as-is.")


def activate_option() -> Any:
    """``--activate``: mark the environment as the default."""
    return typer.Option(False, "--activate", help="Mark this environment as the default.")


def dry_run_option() -> Any:
    """``--dry-run/-n``: preview without making changes."""
    return typer.Option(False, "--dry-run", "-n", help="Preview without making changes.")
