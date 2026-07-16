"""Command typo handling (did-you-mean + optional auto-correct)."""

from __future__ import annotations

import difflib
import time
from typing import Any, List, Tuple

from typer.main import TyperGroup

from repoenv.errors import UsageError

# Read-only commands: they never write to disk or otherwise mutate state, so a
# typo pointing at one of them is safe to auto-correct immediately -- there is
# no destructive blast radius, unlike e.g. `create`, `rm`, or `run`.
SAFE_AUTOCORRECT_COMMANDS = frozenset({"ls", "repos", "path", "status", "check", "completion"})


class RepoEnvGroup(TyperGroup):
    """Typer group with git-like typo suggestions and optional auto-correct."""

    def resolve_command(self, ctx: Any, args: List[str]) -> Tuple[str | None, Any | None, List[str]]:
        try:
            return super().resolve_command(ctx, args)
        except Exception as exc:  # noqa: BLE001 - framework exception surface
            if exc.__class__.__name__ != "UsageError":
                raise
            message = str(exc)
            if "No such command" not in message or not args:
                raise

            typed = args[0]
            commands = list(self.list_commands(ctx))
            matches = difflib.get_close_matches(typed, commands, n=1, cutoff=0.4)
            if not matches:
                raise

            suggestion = matches[0]
            from repoenv.ui import console

            if suggestion in SAFE_AUTOCORRECT_COMMANDS:
                console.print_info(
                    f"'{typed}' is not a renv command. Using read-only command '{suggestion}'."
                )
                args[0] = suggestion
                return super().resolve_command(ctx, args)

            from repoenv.adapters import config_store

            cfg = config_store.load_config()
            if cfg.autocorrect is not None:
                try:
                    delay = float(cfg.autocorrect)
                except (TypeError, ValueError):
                    delay = 0.0
                if delay > 0:
                    console.print_info(
                        f"Warning: '{typed}' is not a renv command. "
                        f"Auto-correcting to '{suggestion}' in {delay:.1f}s (Ctrl-C to cancel)."
                    )
                    try:
                        time.sleep(delay)
                    except KeyboardInterrupt:
                        raise
                else:
                    console.print_info(
                        f"Warning: '{typed}' is not a renv command. Auto-correcting to '{suggestion}'."
                    )
                args[0] = suggestion
                return super().resolve_command(ctx, args)

            raise UsageError(
                f"No such command '{typed}'.",
                hint=(
                    f"Did you mean '{suggestion}'? '{suggestion}' changes state, so it is not "
                    "auto-corrected by default. Run 'renv config autocorrect <seconds>' "
                    "(0 = immediately) to opt in, or type the exact command."
                ),
            ) from None
