"""Typer application: wires global options and Phase 1 subcommands.

Kept thin on purpose. Each command lives in its own module under
``repoenv.cli.commands`` and only calls into the service layer.
"""

from __future__ import annotations

import typer

from repoenv import __version__
from repoenv.cli.commands.add import add_command
from repoenv.cli.commands.completion import completion_command
from repoenv.cli.commands.import_env import import_command
from repoenv.cli.commands.init import init_command
from repoenv.cli.commands.ls import ls_command
from repoenv.cli.commands.merge import merge_command
from repoenv.cli.commands.new import new_command
from repoenv.cli.commands.path import path_command
from repoenv.cli.commands.pr import pr_command
from repoenv.cli.commands.prune import prune_command
from repoenv.cli.commands.rename import rename_command
from repoenv.cli.commands.rm import rm_command
from repoenv.cli.commands.sh import sh_command
from repoenv.cli.commands.status import status_command
from repoenv.cli.commands.sync import sync_command
from repoenv.cli.commands.run import run_command

app = typer.Typer(
    name="renv",
    help="Build and operate isolated git-worktree environments across many repositories.",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"repo-env {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Top-level options shared by all subcommands."""
    _ = version


app.command("init")(init_command)
app.command("new")(new_command)
app.command("add")(add_command)
app.command("merge")(merge_command)
app.command("ls")(ls_command)
app.command("path")(path_command)
app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(run_command)
app.command("rm")(rm_command)
app.command("rename")(rename_command)
app.command("sync")(sync_command)
app.command("status")(status_command)
app.command("doctor")(status_command)
app.command("prune")(prune_command)
app.command("import")(import_command)
app.command("pr")(pr_command)
app.command("sh")(sh_command)
app.command("completion")(completion_command)
