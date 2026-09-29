"""``renv config`` — inspect and edit configuration/state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store, paths, state_store
from repoenv.errors import UsageError
from repoenv.ui import console


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, indent=2)


def _snapshot(cfg: config_store.UserConfig, reg: state_store.Registry) -> dict[str, object]:
    return {
        "paths": {
            "home": str(paths.home_dir()),
            "config": str(paths.config_path()),
            "registry": str(paths.registry_path()),
        },
        "config": cfg.model_dump(mode="json", exclude_none=True),
        "active": reg.get_active(),
    }


def _handle_dict_key(
    cfg: config_store.UserConfig, key: str, value: str | None, unset: bool, *, prefix: str
) -> bool:
    """Return True if handled as a '<prefix>.<name>' operation (aliases./groups.)."""
    if not key.startswith(f"{prefix}."):
        return False
    target: dict[str, str] = getattr(cfg, prefix)
    sub_key = key.split(".", 1)[1]
    if not sub_key:
        raise UsageError(f"Invalid key '{prefix}.'", hint=f"Use e.g. '{prefix}.web'.")
    if unset:
        if sub_key in target:
            target.pop(sub_key, None)
            config_store.save_config(cfg)
        return True
    if value is None:
        console.print_data(target.get(sub_key, ""))
        return True
    target[sub_key] = value
    config_store.save_config(cfg)
    return True


def _set_typed_value(cfg: config_store.UserConfig, key: str, value: str) -> None:
    if key in ("source", "dest"):
        setattr(cfg, key, Path(value).expanduser())
        return
    if key == "install_completion":
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            setattr(cfg, key, True)
            return
        if lowered in ("0", "false", "no", "off"):
            setattr(cfg, key, False)
            return
        raise UsageError(f"Invalid boolean: {value!r}", hint="Use true/false.")
    if key == "autocorrect":
        try:
            cfg.autocorrect = float(value)
        except ValueError as exc:
            raise UsageError(f"Invalid float: {value!r}", hint="Use a number of seconds.") from exc
        return
    # default_branch
    cfg.default_branch = value


def config_command(
    key: Optional[str] = typer.Argument(None, help="Config key (omit to list all)."),
    value: Optional[str] = typer.Argument(None, help="Value to set for the given key."),
    unset: bool = typer.Option(False, "--unset", help="Remove the key from the config."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Show or edit config. Defaults are read from user config; active env from registry."""
    cfg = config_store.load_config()
    reg = state_store.load_registry()

    snapshot = _snapshot(cfg, reg)

    if key is None:
        if as_json:
            console.print_data(json.dumps(snapshot, indent=2))
            return
        console.print_data(json.dumps(snapshot, indent=2))
        return

    if _handle_dict_key(cfg, key, value, unset, prefix="aliases"):
        return
    if _handle_dict_key(cfg, key, value, unset, prefix="groups"):
        return

    if key not in ("source", "dest", "default_branch", "install_completion", "autocorrect"):
        raise UsageError(
            f"Unknown key '{key}'.",
            hint=(
                "Known keys: source, dest, default_branch, install_completion, autocorrect, "
                "aliases.<name>, groups.<name>."
            ),
        )

    if unset:
        setattr(cfg, key, None if key != "install_completion" else False)
        config_store.save_config(cfg)
        return

    if value is None:
        console.print_data(_as_text(getattr(cfg, key)))
        return

    _set_typed_value(cfg, key, value)
    config_store.save_config(cfg)
