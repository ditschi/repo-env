from types import SimpleNamespace

# Vulture whitelist: symbols referenced dynamically or via frameworks (Typer/pydantic)
# that static analysis cannot see. Keep entries minimal and justified.

# Typer callbacks and pydantic model fields are resolved at runtime.
_whitelist = SimpleNamespace(
    autocompletion=None,
    no_args_is_help=None,
    model_config=None,
)

_whitelist.autocompletion
_whitelist.no_args_is_help
_whitelist.model_config
