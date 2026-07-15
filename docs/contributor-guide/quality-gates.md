# Quality Gates

All gates run via `nox`. They also run in CI on every PR and push to `main`.

## CI jobs

| Job | Workflow(s) | Nox session(s) | Python |
|-----|-------------|----------------|--------|
| Quality gates | PR, main | `check_syntax`, `lint`, `check_types`, `necessary_imports`, `dead_code`, `duplicates`, `cyclic_imports` | 3.12 |
| Unit tests | PR, main | `tests` | 3.12, 3.13, 3.14 (matrix) |
| Integration tests | PR, main | `integration` | 3.12 |
| Performance budgets | PR | `performance` | 3.12 |
| Docs build | PR | `docs` | 3.12 |
| Docs deploy | main | — | 3.12 |

On `main`, the quality job runs `nox` with default sessions (same gates as above, minus `format`).

### Why integration runs on one Python version

Unit tests run on a multi-Python matrix because they exercise language-level and library compatibility across supported versions.

Integration tests are slower (real temp git repos, subprocess CLI invocations) and focus on end-to-end workflows — git worktrees, CLI commands, mocked `gh`. Python-version differences are already covered by the unit matrix; repeating integration on 3.13/3.14 would mostly add CI time without catching new failure modes.

CI uses **3.12** for integration — the same primary version as lint, types, and docs.

## Gate summary

| Session | Tool(s) | Python | What it checks |
|---------|---------|--------|----------------|
| `check_syntax` | `compileall` | 3.12 | Byte-compile; catches syntax errors fast |
| `tests` | pytest + pytest-cov + pytest-xdist | 3.12, 3.13, 3.14 | Unit tests with coverage |
| `integration` | pytest | 3.12 | Real temp git repos + mocked gh |
| `performance` | pytest | 3.12 | CLI cold-start latency budgets (help + bash completion) |
| `lint` | ruff + black + flake8 + isort | 3.12 | Style + lint |
| `check_types` | mypy | 3.12 | Static type checking |
| `necessary_imports` | fawltydeps | 3.12 | Undeclared / unused dependencies |
| `dead_code` | vulture | 3.12 | Unused code |
| `duplicates` | pylint R0801 | 3.12 | Duplicate code blocks |
| `cyclic_imports` | pylint R0401 | 3.12 | Circular import detection |
| `docs` | mkdocs build --strict | 3.12 | Docs build with zero warnings |

## Coverage

Coverage is reported on `tests` session only. The project targets ≥ 80% coverage on `src/repoenv`. PRs must not reduce coverage.

## Type strictness

mypy is configured in `mypy.ini`. Key settings:

- `strict = True` on `src/repoenv`
- Integration and test files: relaxed (no strict)

## Line length

110 characters. Configured uniformly in `pyproject.toml` (black, isort), `ruff.toml`, and `.flake8`.

## Running a single gate

```sh
nox -s lint
nox -s check_types
nox -s tests-3.13   # specific Python version
```

## Running only new tests (fast feedback)

```sh
nox -s tests -- tests/unit/domain/
nox -s integration -- tests/integration/cli/
```

## Bypassing formatting for a line

```python
some_long_line = value  # noqa: E501  # fmt: skip
```

Use sparingly. Prefer refactoring over bypasses.
