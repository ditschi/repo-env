# Vulture whitelist: symbols referenced dynamically or via frameworks (Typer/pydantic)
# that static analysis cannot see. Keep entries minimal and justified.

# Typer callbacks and pydantic model fields are resolved at runtime.
_.autocompletion
_.no_args_is_help
_.model_config
