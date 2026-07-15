"""User configuration store: safe YAML load/save with hard guardrails.

The user config is YAML for human authoring, but YAML's implicit typing and
advanced features are dangerous for a config that carries identity strings
(repo/branch/alias/path). Guardrails:

- ``typ="safe"`` loader only (never full/unsafe -> no arbitrary object
  construction).
- YAML 1.2 core schema, so ``no``/``on``/``yes`` stay strings and ``1.20``
  stays a string, not a coerced float.
- Reject anchors/aliases, merge keys, explicit ``!!`` tags, and multi-document
  streams -- none belong in a simple config and all invite surprises.
- Validate the parsed mapping with a pydantic model using ``StrictStr``.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from repoenv.adapters import paths
from repoenv.adapters.atomic import atomic_write_text
from repoenv.errors import ConfigError
from repoenv.typing_compat import patch_typing_eval_type

_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(^|\s)&[\w-]+", "YAML anchors are not allowed in the config"),
    (r"(^|\s)\*[\w-]+", "YAML aliases are not allowed in the config"),
    (r"<<\s*:", "YAML merge keys are not allowed in the config"),
    (r"!!", "YAML explicit tags are not allowed in the config"),
)

patch_typing_eval_type()


class UserConfig(BaseModel):
    """User-authored settings. All optional with safe defaults."""

    model_config = ConfigDict(extra="forbid")

    source: Path | None = None
    dest: Path | None = None
    default_branch: StrictStr | None = None
    install_completion: StrictBool = False
    autocorrect: float | None = None
    aliases: dict[StrictStr, StrictStr] = Field(default_factory=dict)


def _yaml() -> YAML:
    yaml = YAML(typ="safe", pure=True)
    yaml.version = (1, 2)
    yaml.default_flow_style = False
    yaml.allow_duplicate_keys = False
    return yaml


def _reject_forbidden_features(text: str) -> None:
    for pattern, message in _FORBIDDEN_PATTERNS:
        if re.search(pattern, text, flags=re.MULTILINE):
            raise ConfigError(
                message,
                hint="Remove the flagged YAML feature; the config only needs plain keys and values.",
            )
    # Reject multi-document streams (a lone leading '---' is fine).
    doc_markers = re.findall(r"^---\s*$", text, flags=re.MULTILINE)
    if len(doc_markers) > 1:
        raise ConfigError(
            "Multiple YAML documents are not allowed in the config",
            hint="Keep a single document; remove extra '---' separators.",
        )


def load_config(path: Path | None = None) -> UserConfig:
    """Load and validate the user config, returning defaults when absent."""
    cfg_path = path or paths.config_path()
    if not cfg_path.exists():
        return UserConfig()

    text = cfg_path.read_text(encoding="utf-8")
    _reject_forbidden_features(text)

    try:
        data = _yaml().load(text)
    except YAMLError as exc:
        raise ConfigError(
            f"Could not parse config at {cfg_path}: {exc}",
            hint="Run 'renv config edit' to fix it, or 'renv config restore' to roll back.",
        ) from exc

    if data is None:
        return UserConfig()
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config at {cfg_path} must be a mapping of keys to values, not {type(data).__name__}.",
            hint="The top level should be 'key: value' pairs.",
        )

    try:
        return UserConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"Config at {cfg_path} is invalid:\n{exc}",
            hint="Run 'renv config edit' to correct the flagged fields.",
        ) from exc


_HEADER = (
    "# repo-env user config. Plain YAML only: no anchors, aliases, tags, or\n"
    "# multiple documents. Quote values that look like numbers or booleans.\n"
)


def save_config(config: UserConfig, path: Path | None = None) -> Path:
    """Atomically write the config with a commented header and a .bak backup."""
    cfg_path = path or paths.config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    payload = config.model_dump(mode="json", exclude_none=True)
    body = _dump_yaml(payload)
    atomic_write_text(cfg_path, _HEADER + body, mode=0o600, backup=True)
    return cfg_path


def _dump_yaml(payload: dict[str, object]) -> str:
    import io

    yaml = _yaml()
    yaml.default_flow_style = False
    buffer = io.StringIO()
    yaml.dump(payload, buffer)
    return buffer.getvalue()
