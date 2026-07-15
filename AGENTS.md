# AGENTS.md

## Cursor Cloud specific instructions

`repo-env` is a Python CLI package (command `renv`, import package `repoenv`) that
builds and operates isolated git-worktree environments across many repositories.
It is a CLI tool, not a long-running service — there is nothing to "serve".

Tooling is managed with **uv** (package manager) and **nox** (task runner). See
`README.md` (Development) and `noxfile.py` for the authoritative command list.

### Environment layout
- A project virtualenv lives at `.venv` (created by the update script via
  `uv sync --extra dev`). It contains `renv`, `nox`, `pytest`, linters, etc.
- Run tools either through the venv (`.venv/bin/<tool>`), after
  `source .venv/bin/activate`, or via `uv run <tool>`.

### Common commands
- Lint: `nox -s lint` (ruff + black --check + isort --check + flake8)
- Types: `nox -s check_types` (mypy)
- Unit tests: `nox -s tests` (parametrized 3.10–3.14) or `.venv/bin/pytest tests/unit/`
- Integration tests: `.venv/bin/pytest -m integration tests/integration/`
  (uses real temp git repos + mocked `gh`; takes ~80s)
- Full default gates: `nox` (adds `format` locally unless `NOX_CI=1`/`CI=1`)

### Non-obvious gotchas
- `nox` uses the **uv backend** and will auto-download the other CPython
  versions (3.10/3.11/3.13/3.14) on first run — the initial `nox` invocation is
  slower while those interpreters download.
- `nox` default sessions include `format`, which **auto-edits files**. Set
  `NOX_CI=1` (or `CI=1`) to skip it and only run read-only checks.
- `renv create` fetches from the `origin` remote by default. For local source
  repos without a remote, pass `--preserve` (skip fetch) **and** `-B <branch>`
  (e.g. `-B main`) so the default branch can be resolved; otherwise every repo
  fails with "Could not determine the default branch for remote 'origin'".
- Machine state lives under `REPOENV_HOME` (JSON registry); user config is YAML.
  Set `REPOENV_HOME` to an isolated temp dir for throwaway experiments.
- `renv pr` requires the GitHub CLI (`gh`), which is preinstalled.
