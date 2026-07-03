"""Process entry point: run the Typer app and map errors to exit codes."""

from __future__ import annotations

import sys

from repoenv.cli.app import app
from repoenv.errors import RepoEnvError
from repoenv.ui import console


def main() -> None:
    """Console-script entry point (``renv``)."""
    try:
        app()
    except RepoEnvError as error:
        console.print_error(error)
        sys.exit(int(error.exit_code))


if __name__ == "__main__":
    main()
