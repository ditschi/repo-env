"""Console helpers: data goes to stdout, logs/errors go to stderr.

Honors ``NO_COLOR`` and non-TTY automatically (rich handles this). Keeping the
stdout/stderr split strict is what makes ``cd "$(renv path web)"`` safe.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from repoenv.domain.models import Environment, RunResult
from repoenv.domain.summary import RunSummary
from repoenv.errors import RepoEnvError

_out = Console()
_err = Console(stderr=True)


def print_data(text: str) -> None:
    """Print machine-consumable data to stdout with no decoration."""
    _out.print(text, markup=False, highlight=False, soft_wrap=True)


def print_info(text: str) -> None:
    """Print a human status/log line to stderr."""
    _err.print(text)


def print_error(error: RepoEnvError) -> None:
    """Render an error (message + optional next-step hint) to stderr."""
    _err.print(f"[bold red]error:[/] {error.message}")
    if error.hint:
        _err.print(f"[dim]hint:[/] {error.hint}")


def render_environments(environments: list[Environment]) -> None:
    """Print a table of environments to stdout."""
    table = Table(title="environments")
    table.add_column("name", style="bold")
    table.add_column("alias")
    table.add_column("repos", justify="right")
    table.add_column("path")
    for env in environments:
        table.add_row(env.name, env.alias or "-", str(len(env.repos)), str(env.path))
    _out.print(table)


def render_run_results(results: list[RunResult]) -> None:
    """Print grouped per-repo output followed by a summary table."""
    for result in results:
        header_style = "green" if result.ok else "red"
        _err.print(f"[{header_style}]== {result.repo} (exit {result.exit_code}) ==[/]")
        if result.stdout:
            print_data(result.stdout.rstrip("\n"))
        if result.stderr:
            _err.print(result.stderr.rstrip("\n"))

    summary = RunSummary.from_results(results)
    table = Table(title="summary")
    table.add_column("total", justify="right")
    table.add_column("ok", justify="right", style="green")
    table.add_column("failed", justify="right", style="red")
    table.add_column("skipped", justify="right", style="yellow")
    table.add_row(str(summary.total), str(summary.succeeded), str(summary.failed), str(summary.skipped))
    _err.print(table)
