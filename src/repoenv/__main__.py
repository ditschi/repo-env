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
        # Pin the program name: on Windows argv[0] is ``renv.exe``, which would
        # make Click look for ``_RENV.EXE_COMPLETE`` and break shell completion.
        app(prog_name="renv")
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
