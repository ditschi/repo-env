"""``renv config`` — inspect and edit configuration/state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from repoenv.adapters import config_store, paths, state_store
from repoenv.domain.scm import parse_provider_setting
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


_DICT_PREFIXES = ("aliases", "groups", "providers")
_SCALAR_KEYS = ("source", "dest", "default_branch", "install_completion", "autocorrect")
_TRUE_WORDS = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


@dataclass(frozen=True)
class _KeyOperation:
    """One ``renv config KEY [VALUE] [--unset]`` request."""

    key: str
    value: str | None
    unset: bool


def _handle_dict_key(cfg: config_store.UserConfig, op: _KeyOperation, *, prefix: str) -> bool:
    """Return True if handled as a '<prefix>.<name>' operation (aliases./groups./providers.)."""
    if not op.key.startswith(f"{prefix}."):
        return False
    target: dict[str, str] = getattr(cfg, prefix)
    sub_key = op.key.split(".", 1)[1]
    if not sub_key:
        raise UsageError(f"Invalid key '{prefix}.'", hint=f"Use e.g. '{prefix}.web'.")
    if op.unset:
        if sub_key in target:
            target.pop(sub_key, None)
            config_store.save_config(cfg)
        return True
    if op.value is None:
        console.print_data(target.get(sub_key, ""))
        return True
    target[sub_key] = op.value
    config_store.save_config(cfg)
    return True


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE_WORDS:
        return True
    if lowered in _FALSE_WORDS:
        return False
    raise UsageError(f"Invalid boolean: {value!r}", hint="Use true/false.")


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise UsageError(f"Invalid float: {value!r}", hint="Use a number of seconds.") from exc


def _set_typed_value(cfg: config_store.UserConfig, key: str, value: str) -> None:
    if key in ("source", "dest"):
        setattr(cfg, key, Path(value).expanduser())
    elif key == "install_completion":
        setattr(cfg, key, _parse_bool(value))
    elif key == "autocorrect":
        cfg.autocorrect = _parse_float(value)
    else:  # default_branch
        cfg.default_branch = value


def _handle_scalar_key(cfg: config_store.UserConfig, op: _KeyOperation) -> None:
    if op.key not in _SCALAR_KEYS:
        raise UsageError(
            f"Unknown key '{op.key}'.",
            hint=(
                "Known keys: source, dest, default_branch, install_completion, autocorrect, "
                "aliases.<name>, groups.<name>, providers.<host>."
            ),
        )

    if op.unset:
        setattr(cfg, op.key, None if op.key != "install_completion" else False)
        config_store.save_config(cfg)
        return

    if op.value is None:
        console.print_data(_as_text(getattr(cfg, op.key)))
        return

    _set_typed_value(cfg, op.key, op.value)
    config_store.save_config(cfg)


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
        # The snapshot is always JSON, so ``--json`` does not change the output.
        console.print_data(json.dumps(snapshot, indent=2))
        return

    op = _KeyOperation(key=key, value=value, unset=unset)
    if key.startswith("providers.") and value is not None and not unset:
        parse_provider_setting(value)
    if any(_handle_dict_key(cfg, op, prefix=prefix) for prefix in _DICT_PREFIXES):
        return
    _handle_scalar_key(cfg, op)
