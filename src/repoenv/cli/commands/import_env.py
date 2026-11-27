"""``renv import`` — adopt an existing on-disk environment into the registry."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import git_adapter, state_store
from repoenv.domain.models import Environment, RepoEntry, RepoStatus
from repoenv.errors import NothingMatchedError, UsageError
from repoenv.ui import console


def _repo_entry(worktree: Path) -> RepoEntry:
    """Describe the checked-out *worktree* as an adopted (not renv-created) repo entry."""
    sha = git_adapter.rev_parse(worktree, "HEAD")
    branch = git_adapter.current_branch(worktree)
    return RepoEntry(
        repo=worktree.name,
        worktree_path=worktree,
        remote="origin",
        base=branch or sha,
        branch=branch or f"detached@{sha[:12]}",
        branch_created=False,
        source_sha=sha,
        status=RepoStatus.OK,
    )


def _scan_worktrees(directory: Path) -> list[RepoEntry]:
    """Return an entry for every git repository directly below *directory*, sorted by path."""
    children = sorted(p for p in directory.iterdir() if p.is_dir())
    return [_repo_entry(child) for child in children if git_adapter.is_git_repo(child)]


def import_command(
    directory: Path = typer.Argument(..., help="Existing environment directory to adopt."),
    name: Optional[str] = typer.Option(None, "--name", help="Name to register (defaults to dir name)."),
    source: Optional[Path] = typer.Option(None, "--source", help="Source repositories directory."),
    alias: Optional[str] = typer.Option(None, "--alias", help="Short alias for the environment."),
) -> None:
    """Register an environment from worktrees already present on disk."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise UsageError(f"Not a directory: {directory}")

    env_name = name or directory.name
    with state_store.registry_transaction() as registry:
        if env_name in registry:
            raise UsageError(
                f"Environment '{env_name}' already exists.", hint="Pass --name to choose another."
            )

        entries = _scan_worktrees(directory)
        if not entries:
            raise NothingMatchedError(
                f"No git worktrees found under {directory}.",
                hint="Point at a directory containing checked-out repositories.",
            )

        environment = Environment(
            name=env_name,
            alias=alias,
            path=directory,
            source=(source or directory).resolve(),
            base_branch=None,
            repos=entries,
        )
        registry.add(environment)
        state_store.write_env_metadata(environment)
        console.print_info(f"Imported environment '{env_name}' with {len(entries)} repo(s).")
