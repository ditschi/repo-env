# repo-env

Build and operate isolated **git-worktree environments** across many
repositories. The command is `renv`; the distribution is `repo-env`.

An *environment* is a named directory containing one git worktree per selected
repository. Create it from repos matching a glob in a source directory, run
commands across every worktree, and open bulk pull requests — all from one CLI.

## Install

```sh
uv tool install repo-env      # or: pipx install repo-env
renv --help
```

## Quick start

```sh
renv init                                  # first-run setup wizard
renv new web --source ~/src --branch feature/x   # create env from repos
renv ls                                    # list environments
cd "$(renv path web)"                       # cd into an environment
renv run web -- git status                 # run a command across worktrees
renv pr web --title "Migrate X" --draft    # open bulk PRs (never auto-pushes)
```

## Design

- Command: `renv` · Distribution: `repo-env` · Import package: `repoenv`
- POSIX-first (Linux/macOS), Python 3.12+, Typer CLI.
- User config = YAML (safe, 1.2 core schema); machine state = JSON/JSONL.
- Source clones are treated as **read-only**. Destructive ops require explicit
  flags and never run in non-interactive mode.

## Development

```sh
uv tool install nox
nox                 # default gates: syntax, tests, lint, types, imports, dead code, dupes, cycles
nox -s tests        # unit tests with coverage
nox -s integration  # integration tests (temp git repos, mocked gh)
```

Quality settings mirror the RA6 `op.cli` conventions: line length 110,
target py312, ruff + black + flake8 + isort + pylint + mypy + vulture +
fawltydeps.
