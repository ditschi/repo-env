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
SAFE_AUTOCORRECT_COMMANDS = frozenset({"ls", "repos", "path", "status", "check"})


class RepoEnvGroup(TyperGroup):
    """Typer group with git-like typo suggestions and optional auto-correct."""

    def resolve_command(self, ctx: Any, args: List[str]) -> Tuple[str | None, Any | None, List[str]]:
        try:
            return super().resolve_command(ctx, args)
        except Exception as exc:  # noqa: BLE001 - framework exception surface
            suggestion = self._suggest_command(ctx, args, exc)
            if suggestion is None:
                raise
            typed = args[0]
            if not _autocorrect_to(typed, suggestion):
                raise UsageError(
                    f"No such command '{typed}'.",
                    hint=(
                        f"Did you mean '{suggestion}'? '{suggestion}' changes state, so it is not "
                        "auto-corrected by default. Run 'renv config autocorrect <seconds>' "
                        "(0 = immediately) to opt in, or type the exact command."
                    ),
                ) from None
            args[0] = suggestion
            return super().resolve_command(ctx, args)

    def _suggest_command(self, ctx: Any, args: List[str], exc: Exception) -> str | None:
        """Return the closest command for an unknown-command error, or None to re-raise."""
        if exc.__class__.__name__ != "UsageError" or "No such command" not in str(exc) or not args:
            return None
        matches = difflib.get_close_matches(args[0], list(self.list_commands(ctx)), n=1, cutoff=0.4)
        return matches[0] if matches else None


def _autocorrect_to(typed: str, suggestion: str) -> bool:
    """Announce (and possibly delay) the auto-correction; return False if it is not allowed."""
    from repoenv.ui import console

    if suggestion in SAFE_AUTOCORRECT_COMMANDS:
        console.print_info(f"'{typed}' is not a renv command. Using read-only command '{suggestion}'.")
        return True

    from repoenv.adapters import config_store

    cfg = config_store.load_config()
    if cfg.autocorrect is None:
        return False
    delay = _autocorrect_delay(cfg.autocorrect)
    if delay > 0:
        console.print_info(
            f"Warning: '{typed}' is not a renv command. "
            f"Auto-correcting to '{suggestion}' in {delay:.1f}s (Ctrl-C to cancel)."
        )
        time.sleep(delay)
    else:
        console.print_info(f"Warning: '{typed}' is not a renv command. Auto-correcting to '{suggestion}'.")
    return True


def _autocorrect_delay(setting: float) -> float:
    try:
        return float(setting)
    except (TypeError, ValueError):
        return 0.0
