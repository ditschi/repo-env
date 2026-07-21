"""Process entry point: run the Typer app and map errors to exit codes."""

from __future__ import annotations

import os
import sys

from repoenv.cli.app import app
from repoenv.errors import ExitCode, RepoEnvError
from repoenv.ui import console


def main() -> None:
    """Console-script entry point (``renv``)."""
    try:
        app()
    except RepoEnvError as error:
        console.print_error(error)
        sys.exit(int(error.exit_code))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:  # noqa: BLE001 - final CLI safety net
        if "--debug" in sys.argv or os.environ.get("REPOENV_DEBUG"):
            raise
        console.print_error(
            RepoEnvError(
                f"Unexpected internal error: {error}",
                hint="Re-run with --debug to see the full traceback.",
            )
        )
        sys.exit(int(ExitCode.GENERIC))


if __name__ == "__main__":
    main()
