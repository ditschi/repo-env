"""``renv pr`` — create pull requests across an environment's repositories."""

from __future__ import annotations

import json
from typing import List, Optional

import typer

from repoenv.adapters import gh_adapter, state_store
from repoenv.cli.completion_helpers import complete_env_name
from repoenv.cli.resolve import resolve_environment
from repoenv.errors import UsageError
from repoenv.services import pr_service
from repoenv.ui import console


def pr_command(
    env: Optional[str] = typer.Argument(
        None,
        help="Environment name or alias ('-' = cwd).",
        autocompletion=complete_env_name,
    ),
    title: str = typer.Option(..., "--title", "-t", help="PR title. Supports {repo}/{branch}/{env}."),
    body: str = typer.Option("", "--body", "-b", help="PR body. Supports {repo}/{branch}/{env}."),
    base: Optional[str] = typer.Option(None, "--base", help="Base branch for the PRs."),
    draft: bool = typer.Option(False, "--draft", help="Create draft pull requests."),
    include: List[str] = typer.Option([], "--include", "-i", help="Glob(s) of repos to include."),
    exclude: List[str] = typer.Option([], "--exclude", "-x", help="Glob(s) of repos to exclude."),
    reviewer: List[str] = typer.Option([], "--reviewer", help="Reviewer (repeatable)."),
    label: List[str] = typer.Option([], "--label", help="Label (repeatable)."),
    assignee: List[str] = typer.Option([], "--assignee", help="Assignee (repeatable)."),
    push: bool = typer.Option(False, "--push", help="Push branches before creating PRs."),
    skip_no_diff: bool = typer.Option(False, "--skip-no-diff", help="Skip repos with no changes."),
    if_exists: str = typer.Option("skip", "--if-exists", help="When a PR exists: skip|fail."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without calling gh."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Bulk-create pull requests. Never pushes unless ``--push`` is given."""
    if if_exists not in ("skip", "fail"):
        raise UsageError("--if-exists must be 'skip' or 'fail'.")
    if not gh_adapter.is_available():
        raise UsageError("The GitHub CLI 'gh' is not available.", hint="Install gh and run 'gh auth login'.")

    registry = state_store.load_registry()
    environment = resolve_environment(registry, env)

    if dry_run:
        console.print_info(f"Dry run: would create PRs for {len(environment.repos)} repo(s):")
        for entry in environment.repos:
            console.print_info(f"  {entry.repo}: title='{title}' base='{base or entry.base}' draft={draft}")
        return

    outcome = pr_service.create_prs(
        environment,
        title=title,
        body=body,
        base=base,
        draft=draft,
        reviewers=reviewer,
        labels=label,
        assignees=assignee,
        push=push,
        skip_no_diff=skip_no_diff,
        if_exists=if_exists,
        include=include or None,
        exclude=exclude or None,
    )

    if as_json:
        payload = {
            "created": [{"repo": r.repo, "url": r.url} for r in outcome.created],
            "skipped": [{"repo": r.repo, "reason": r.reason} for r in outcome.skipped],
        }
        console.print_data(json.dumps(payload, indent=2))
        return

    for result in outcome.created:
        console.print_info(f"  created  {result.repo}: {result.url}")
    for result in outcome.skipped:
        console.print_info(f"  skipped  {result.repo}: {result.reason}")
    console.print_info(f"Created {len(outcome.created)}, skipped {len(outcome.skipped)}.")
