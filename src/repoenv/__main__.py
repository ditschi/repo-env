"""Process entry point: run the Typer app and map errors to exit codes.

Nothing here should ever let a raw Python traceback reach the user unless
``--debug`` (or ``REPOENV_DEBUG=1``) was explicitly requested. Known errors
(``RepoEnvError``) already carry a friendly message + hint; anything else is
an unexpected bug and gets a short, generic message instead of a stack trace.

``--debug`` is checked directly against ``sys.argv``/the environment (not via
a Click callback) because failures can happen *during* argument parsing --
e.g. an unknown subcommand -- before any callback would run.
"""

from __future__ import annotations

import os
import sys

from repoenv.cli.app import app
from repoenv.errors import ExitCode, RepoEnvError
from repoenv.ui import console

_DEBUG_ENV_VAR = "REPOENV_DEBUG"


def _debug_requested(argv: list[str]) -> bool:
    if os.environ.get(_DEBUG_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return "--debug" in argv


def main() -> None:
    """Console-script entry point (``renv``)."""
    debug = _debug_requested(sys.argv[1:])
    try:
        app()
    except RepoEnvError as error:
        if debug:
            raise
        console.print_error(error)
        sys.exit(int(error.exit_code))
    except KeyboardInterrupt:
        if debug:
            raise
        console.print_info("Aborted.")
        sys.exit(130)
    except Exception as error:  # noqa: BLE001 - last-resort guard; see module docstring
        if debug:
            raise
        console.print_fatal(str(error) or error.__class__.__name__)
        sys.exit(int(ExitCode.GENERIC))


if __name__ == "__main__":
    main()
