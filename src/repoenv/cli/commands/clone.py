"""``renv clone`` — clone repositories into the source tree (for later ``renv create``)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store
from repoenv.errors import NothingMatchedError, PartialFailureError, UsageError
from repoenv.services import clone_service
from repoenv.services.clone_service import Action, Role
from repoenv.ui import console


def _resolve_source(source: Optional[Path], config: config_store.UserConfig) -> Path:
    resolved = source or config.source
    if resolved is None:
        raise UsageError("No --source given and no default configured. Run 'renv init' first.")
    return resolved.expanduser()


def _role_was_explicit(ctx: typer.Context) -> bool:
    # Compared by ``.name`` (not imported against click's ``ParameterSource``
    # enum) because that type lives in different modules across typer
    # versions -- real ``click.core`` vs. a vendored fork. See
    # cli/passthrough.py for the same constraint.
    source = ctx.get_parameter_source("role")
    return source is not None and source.name == "COMMANDLINE"


def clone_command(
    ctx: typer.Context,
    url: list[str] = typer.Option(
        [],
        "--url",
        "-u",
        help=(
            "A host (https://github.com), host+owner (.../my-org), or a full "
            "owner/repo URL. Repeatable; comma-separated values also work."
        ),
    ),
    include: list[str] = typer.Option(
        [],
        "--include",
        "-i",
        help=(
            "owner/repo glob(s) to clone, e.g. 'myself/test-*', 'owner/repo', "
            "or 'prefix-*/*'. '**' matches everything. Default: everything "
            "reachable via --url. Repeatable; CSV supported."
        ),
    ),
    exclude: list[str] = typer.Option(
        [], "--exclude", "-x", help="owner/repo glob(s) to skip. Same format as --include."
    ),
    role: Role = typer.Option(
        Role.MEMBER,
        "--role",
        help=(
            "Which org memberships count when an --include owner-glob has a "
            "wildcard: member (any active membership, default) | owner (admin "
            "role only) | any (active + pending)."
        ),
    ),
    source: Optional[Path] = typer.Option(
        None, "--source", "-s", help="Directory to clone into (default: config source)."
    ),
    protocol: Optional[str] = typer.Option(
        None, "--protocol", help="ssh|https. Default: gh's configured git_protocol, per host."
    ),
    jobs: int = typer.Option(1, "--jobs", "-j", min=1, help="Parallel workers (default 1 = sequential)."),
    update: bool = typer.Option(
        False,
        "--update",
        help="For repos that already exist locally: fetch and fast-forward to the latest upstream.",
    ),
    reset_default: bool = typer.Option(
        False,
        "--reset-default",
        help="For repos that already exist locally: check out the upstream default branch.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow --update/--reset-default to discard local changes or diverged commits.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Preview without cloning or changing anything."
    ),
) -> None:
    """Clone repositories into ``--source``, laid out as ``host/owner/repo``.

    This only prepares the source tree -- it never creates or touches a renv
    environment. Run ``renv create``/``renv add`` afterwards to build one from
    the cloned repos.

    Repos already present locally are left alone unless ``--update`` and/or
    ``--reset-default`` are given; both refuse to touch a repo with local
    changes or diverged commits unless ``--force`` is also given.
    """
    if force and not (update or reset_default):
        raise UsageError(
            "--force has no effect without --update or --reset-default.",
            hint="Add --update and/or --reset-default, or drop --force.",
        )
    if protocol is not None and protocol not in ("ssh", "https"):
        raise UsageError("--protocol must be 'ssh' or 'https'.")

    config = config_store.load_config()
    resolved_source = _resolve_source(source, config)

    plan = clone_service.resolve_clone_targets(
        urls=url,
        include=include,
        exclude=exclude,
        role=role,
        role_explicit=_role_was_explicit(ctx),
        protocol=protocol,
    )
    for warning in plan.warnings:
        console.print_info(f"Warning: {warning}")

    if not plan.repos:
        raise NothingMatchedError(
            "No repositories matched.",
            hint="Check --url/--include/--exclude, or --role if using a wildcard owner.",
        )

    console.print_info(f"Resolved {len(plan.repos)} repositor{'y' if len(plan.repos) == 1 else 'ies'}:")
    for repo in plan.repos:
        console.print_info(f"  {repo.relative_path}")

    if dry_run:
        console.print_info(f"Dry run: would clone into {resolved_source} (no changes made).")
        return

    outcomes = clone_service.execute_clone_plan(
        plan.repos,
        source=resolved_source,
        update=update,
        reset_default=reset_default,
        force=force,
        jobs=jobs,
    )

    counts: dict[Action, int] = {}
    for outcome in outcomes:
        counts[outcome.action] = counts.get(outcome.action, 0) + 1
        suffix = f" -- {outcome.detail}" if outcome.detail else ""
        console.print_info(f"  [{outcome.action.value:<9}] {outcome.repo.relative_path}{suffix}")

    summary = ", ".join(f"{count} {action.value}" for action, count in counts.items())
    console.print_info(f"Done: {len(outcomes)} repositor{'y' if len(outcomes) == 1 else 'ies'} -> {summary}")

    failed = [o.repo.relative_path for o in outcomes if o.action is Action.FAILED]
    if failed:
        raise PartialFailureError(
            f"{len(failed)} repositor{'y' if len(failed) == 1 else 'ies'} failed: {', '.join(failed)}.",
            hint="See the output above for details.",
        )
