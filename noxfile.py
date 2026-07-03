"""Nox sessions for repo-env.

Ported from the op.cli conventions: uv backend, Python 3.12, the same quality
gates (ruff/black/flake8/isort/pylint/mypy/vulture/fawltydeps). Build/conan/
flashimage sessions from op.cli are intentionally omitted as not applicable.
"""

from __future__ import annotations

import os

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

DEFAULT_PYTHON = "3.12"
PACKAGE = "repoenv"
SRC = "src/repoenv"


def is_ci() -> bool:
    """Return True when running in a CI environment."""
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


# Sessions run by default. Locally we also run `format` before `lint`.
_CI_DEFAULT = [
    "check_syntax",
    "tests",
    "lint",
    "check_types",
    "necessary_imports",
    "dead_code",
    "duplicates",
    "cyclic_imports",
]
nox.options.sessions = _CI_DEFAULT if is_ci() else (["format"] + _CI_DEFAULT)


@nox.session(python=DEFAULT_PYTHON)
def tests(session: nox.Session) -> None:
    """Run unit tests with coverage and xdist."""
    session.install("-e", ".[test]")
    session.run(
        "pytest",
        f"--cov={PACKAGE}",
        "--cov-report=term-missing",
        "-n",
        "auto",
        "--dist=loadscope",
        "tests/unit/",
        *session.posargs,
    )


@nox.session(python=DEFAULT_PYTHON)
def integration(session: nox.Session) -> None:
    """Run all integration tests (real temp git repos, mocked gh)."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def integration_cli(session: nox.Session) -> None:
    """Run CLI integration tests only."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/cli/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def integration_git(session: nox.Session) -> None:
    """Run git-worktree integration tests only."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/git/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def integration_pr(session: nox.Session) -> None:
    """Run PR (mocked gh) integration tests only."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/pr/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def performance(session: nox.Session) -> None:
    """Check CLI completion cold-start latency budget."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "performance", "tests/performance/", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def check_syntax(session: nox.Session) -> None:
    """Byte-compile all sources to catch syntax errors fast."""
    session.run("python", "-m", "compileall", "-q", SRC, external=False)


@nox.session(python=DEFAULT_PYTHON)
def check_types(session: nox.Session) -> None:
    """Static type checking with mypy."""
    session.install("-e", ".[type-check]")
    session.run("mypy", "--package", PACKAGE)


@nox.session(python=DEFAULT_PYTHON)
def lint(session: nox.Session) -> None:
    """Run ruff, black --check, flake8, isort --check."""
    session.install("-e", ".[lint]")
    session.run("ruff", "check", SRC, "tests")
    session.run("black", "--check", SRC, "tests")
    session.run("isort", "--check-only", SRC, "tests")
    session.run("flake8", SRC, "tests")


@nox.session(python=DEFAULT_PYTHON)
def format(session: nox.Session) -> None:  # noqa: A001 - session name mirrors op.cli
    """Auto-format with black, isort, and ruff --fix (local only)."""
    session.install("-e", ".[lint]")
    session.run("isort", SRC, "tests")
    session.run("black", SRC, "tests")
    session.run("ruff", "check", "--fix", SRC, "tests")


@nox.session(python=DEFAULT_PYTHON)
def necessary_imports(session: nox.Session) -> None:
    """Detect undeclared/unused dependencies with fawltydeps."""
    session.install("-e", ".[code-quality]")
    session.run(
        "fawltydeps",
        "--detailed",
        "--code",
        SRC,
        "--deps",
        "pyproject.toml",
        "--deps-parser-choice",
        "pyproject.toml",
        "--ignore-unused",
        "vulture",
        "black",
        "fawltydeps",
        "flake8",
        "isort",
        "mypy",
        "nox",
        "pylint",
        "pytest",
        "pytest-cov",
        "pytest-xdist",
        "ruff",
    )


@nox.session(python=DEFAULT_PYTHON)
def dead_code(session: nox.Session) -> None:
    """Detect dead code with vulture."""
    session.install("-e", ".[code-quality]")
    session.run("vulture")


@nox.session(python=DEFAULT_PYTHON)
def duplicates(session: nox.Session) -> None:
    """Detect duplicate code (pylint R0801)."""
    session.install("-e", ".[code-quality]")
    session.run(
        "pylint",
        "--disable=all",
        "--enable=R0801",
        "--min-similarity-lines=6",
        SRC,
    )


@nox.session(python=DEFAULT_PYTHON)
def cyclic_imports(session: nox.Session) -> None:
    """Detect cyclic imports (pylint R0401)."""
    session.install("-e", ".[code-quality]")
    session.run("pylint", "--disable=all", "--enable=R0401", SRC)


@nox.session(python=DEFAULT_PYTHON, venv_backend="none")
def install_dev(session: nox.Session) -> None:
    """Install the package with all dev extras into the active environment."""
    session.run("python", "-m", "pip", "install", "-e", ".[dev]", external=True)
