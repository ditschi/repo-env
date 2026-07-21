# Development Setup

## Prerequisites

- Python 3.10+ (3.12 recommended for local dev; nox installs other versions on demand via uv)
- [uv](https://docs.astral.sh/uv/) — used by nox as the venv backend
- [nox](https://nox.thea.codes/) — task runner for all quality gates
- Git 2.38+

## Install nox and uv

```sh
pip install uv
uv tool install nox
```

Or with pipx:

```sh
pipx install nox
pipx install uv
```

## Clone and set up

```sh
git clone https://github.com/ditschi/repo-env.git
cd repo-env
nox -s install_dev   # installs all dev extras into the active venv
```

## Run quality gates

```sh
nox                  # default sessions: syntax, tests (3.12/3.13/3.14), lint, types, imports, dead code, dupes, cycles
nox -s tests         # unit tests, all Python versions
nox -s tests-3.12    # unit tests, specific Python version
nox -s integration   # integration tests (real temp git repos, mocked gh)
nox -s lint          # ruff + black + flake8 + isort
nox -s check_types   # mypy
nox -s docs          # build docs strict (fails on any warning)
nox -s docs_serve    # live-reload local docs at http://127.0.0.1:8000
```

### Troubleshooting: missing Python interpreter in nox

If nox prints `Session tests-3.14 skipped: Python interpreter 3.14 not found`:

```sh
uv self update
uv python install 3.14
nox -s tests-3.14 --download-python always
```

Notes:

- First run can take longer while uv downloads Python builds.
- `--download-python always` forces nox to ask uv to provision the interpreter.

CI runs integration tests in a separate job on Python 3.12 only (see [Quality Gates](quality-gates.md#ci-jobs)).

## Install pre-commit hooks

```sh
pre-commit install --hook-type commit-msg --hook-type pre-commit --hook-type pre-push
```

This installs:

- `pre-commit`: formatting + lint on every commit
- `commit-msg`: validates your commit message follows [Conventional Commits](commit-convention.md)
- `pre-push`: runs mypy

## Project structure

```
src/repoenv/       Core package
  adapters/        External system adapters (git, gh, filesystem)
  cli/             Typer command definitions
  domain/          Pure domain models + logic
  services/        Orchestration between domain + adapters
  ui/              Rich terminal output helpers
tests/
  unit/            Fast, no I/O
  integration/     Real temp git repos, mocked gh
  performance/     CLI cold-start latency budgets (help + bash completion)
docs/              This site
.github/workflows/ CI/CD pipelines
```

## Code style

- Line length: **110**
- Formatter: **black** (primary) + **isort** (import order) + **ruff --fix** (auto-fixable lint)
- Type hints required on all public interfaces (enforced by mypy strict)
- Docstrings: Google style (enforced by mkdocstrings rendering)

See [Quality Gates](quality-gates.md) for the full list of tools.
