# Quality Gates

All gates run via `nox`. They also run in CI on every PR and push to `main`.

## Gate summary

| Session | Tool(s) | Python | What it checks |
|---------|---------|--------|----------------|
| `check_syntax` | `compileall` | 3.12 | Byte-compile; catches syntax errors fast |
| `tests` | pytest + pytest-cov + pytest-xdist | 3.12, 3.13, 3.14 | Unit tests with coverage |
| `integration` | pytest | 3.12 | Real temp git repos + mocked gh |
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
