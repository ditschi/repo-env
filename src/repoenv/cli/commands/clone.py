"""``renv clone`` — clone repositories into the source tree (for later ``renv create``)."""
# aihealth: disable=primitive_obsession, excess_arguments -- typer CLI boundary: every CLI option is a command parameter  # noqa: E501

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store
from repoenv.domain.scm import ProviderKind
from repoenv.errors import NothingMatchedError, PartialFailureError, UsageError
from repoenv.services import clone_service
from repoenv.services.clone_service import Action, CloneOutcome, CloneQuery, ResolvedRepo, Role, SyncOptions
from repoenv.ui import console

_URL_HELP = (
    "A host (https://github.com), host+owner (.../my-org), or a full "
    "owner/repo URL. Repeatable; comma-separated values also work."
)
_INCLUDE_HELP = (
    "owner/repo glob(s) to clone, e.g. 'myself/test-*', 'owner/repo', "
    "or 'prefix-*/*'. '**' matches everything. Default: everything "
    "reachable via --url. Repeatable; CSV supported."
)
_ROLE_HELP = (
    "Which org memberships count when an --include owner-glob has a "
    "wildcard: member (any active membership, default) | owner (admin "
    "role only) | any (active + pending)."
)
_PROTOCOL_HELP = "ssh|https. Default: gh's configured git_protocol for GitHub hosts, ssh elsewhere."
_PROVIDER_HELP = (
    "SCM provider of every --url host. Default: config 'providers.<host>', then "
    "well-known hosts, then probing the host's API."
)
_UPDATE_HELP = "For repos that already exist locally: fetch and fast-forward to the latest upstream."
_RESET_DEFAULT_HELP = "For repos that already exist locally: check out the upstream default branch."
_FORCE_HELP = "Allow --update/--reset-default to discard local changes or diverged commits."


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


def _repositories(count: int) -> str:
    return f"{count} repositor{'y' if count == 1 else 'ies'}"


def _force_is_pointless(sync: SyncOptions) -> bool:
    """Return True if ``--force`` was given without anything it could apply to."""
    if not sync.force:
        return False
    return not (sync.update or sync.reset_default)


def _validate_flags(sync: SyncOptions, protocol: Optional[str]) -> None:
    if _force_is_pointless(sync):
        raise UsageError(
            "--force has no effect without --update or --reset-default.",
            hint="Add --update and/or --reset-default, or drop --force.",
        )
    if protocol is not None and protocol not in ("ssh", "https"):
        raise UsageError("--protocol must be 'ssh' or 'https'.")


def _resolve_plan(query: CloneQuery, config: config_store.UserConfig) -> list[ResolvedRepo]:
    """Resolve ``query``, print warnings and the resolved repos; fail if nothing matched."""
    plan = clone_service.resolve_clone_targets(query, provider_settings=config.providers)
    for warning in plan.warnings:
        console.print_info(f"Warning: {warning}")

    if not plan.repos:
        raise NothingMatchedError(
            "No repositories matched.",
            hint="Check --url/--include/--exclude, or --role if using a wildcard owner.",
        )

    console.print_info(f"Resolved {_repositories(len(plan.repos))}:")
    for repo in plan.repos:
        console.print_info(f"  {repo.relative_path}")
    return plan.repos


def _report_outcomes(outcomes: list[CloneOutcome]) -> None:
    """Print one line per outcome plus a summary; raise if any repo failed."""
    counts: dict[Action, int] = {}
    for outcome in outcomes:
        counts[outcome.action] = counts.get(outcome.action, 0) + 1
        suffix = f" -- {outcome.detail}" if outcome.detail else ""
        console.print_info(f"  [{outcome.action.value:<9}] {outcome.repo.relative_path}{suffix}")

    summary = ", ".join(f"{count} {action.value}" for action, count in counts.items())
    console.print_info(f"Done: {_repositories(len(outcomes))} -> {summary}")

    failed = [o.repo.relative_path for o in outcomes if o.action is Action.FAILED]
    if failed:
        raise PartialFailureError(
            f"{_repositories(len(failed))} failed: {', '.join(failed)}.",
            hint="See the output above for details.",
        )


def clone_command(
    ctx: typer.Context,
    url: list[str] = typer.Option([], "--url", "-u", help=_URL_HELP),
    include: list[str] = typer.Option([], "--include", "-i", help=_INCLUDE_HELP),
    exclude: list[str] = typer.Option(
        [], "--exclude", "-x", help="owner/repo glob(s) to skip. Same format as --include."
    ),
    role: Role = typer.Option(Role.MEMBER, "--role", help=_ROLE_HELP),
    source: Optional[Path] = typer.Option(
        None, "--source", "-s", help="Directory to clone into (default: config source)."
    ),
    protocol: Optional[str] = typer.Option(None, "--protocol", help=_PROTOCOL_HELP),
    provider: Optional[ProviderKind] = typer.Option(None, "--provider", help=_PROVIDER_HELP),
    jobs: int = typer.Option(1, "--jobs", "-j", min=1, help="Parallel workers (default 1 = sequential)."),
    update: bool = typer.Option(False, "--update", help=_UPDATE_HELP),
    reset_default: bool = typer.Option(False, "--reset-default", help=_RESET_DEFAULT_HELP),
    force: bool = typer.Option(False, "--force", help=_FORCE_HELP),
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
    sync = SyncOptions(update=update, reset_default=reset_default, force=force)
    _validate_flags(sync, protocol)

    config = config_store.load_config()
    resolved_source = _resolve_source(source, config)

    query = CloneQuery(
        urls=url,
        include=include,
        exclude=exclude,
        role=role,
        role_explicit=_role_was_explicit(ctx),
        protocol=protocol,
        provider=provider,
    )
    repos = _resolve_plan(query, config)

    if dry_run:
        console.print_info(f"Dry run: would clone into {resolved_source} (no changes made).")
        return

    _report_outcomes(clone_service.execute_clone_plan(repos, source=resolved_source, sync=sync, jobs=jobs))
