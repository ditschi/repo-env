"""Nox sessions for repo-env.

Uses uv backend, Python 3.10 default, and quality gates
(ruff/pylint/mypy/vulture/fawltydeps/ai-health code-health).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

DEFAULT_PYTHON = "3.10"
CI_PYTHON = "3.12"  # primary CI version for single-version sessions (integration, performance, lint, …)
PYTHON_VERSIONS = ["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"]
PACKAGE = "repoenv"
SRC = "src/repoenv"
AIHEALTH_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".aihealth.toml")
# Components whose ai-health project score must not drop between merge-base and HEAD.
AIHEALTH_COMPONENTS = (".", "src", "tests")
GENERATED_VERSION_FILE = "src/repoenv/_version.py"


def _env_truthy(name: str) -> bool:
    """Return True when ``name`` is set to a common truthy string."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_ci() -> bool:
    """Return True when running in a CI environment.

    Detection order:
    1) ``NOX_LOCAL=1`` forces local (default sessions include ``format``).
    2) ``NOX_CI=1`` forces CI (skip ``format``).
    3) Generic ``CI=true`` (GitHub Actions, GitLab, CircleCI, …).
    4) Provider-specific flags when ``CI`` is missing or unreliable.
    """
    if _env_truthy("NOX_LOCAL"):
        return False
    if _env_truthy("NOX_CI"):
        return True
    if _env_truthy("CI"):
        return True
    if os.environ.get("JENKINS_URL", "").strip():
        return True
    return any(
        _env_truthy(name)
        for name in (
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "BUILDKITE",
            "CIRCLECI",
            "TRAVIS",
            "TF_BUILD",  # Azure Pipelines
        )
    )


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
    "code-health",
]
nox.options.sessions = _CI_DEFAULT if is_ci() else (["format"] + _CI_DEFAULT)


@nox.session(python=PYTHON_VERSIONS, tags=["unit", "tests"])
def tests(session: nox.Session) -> None:
    """Run unit tests with coverage and xdist (all supported Python versions)."""
    session.install("-e", ".[test,all]")
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


@nox.session(python=CI_PYTHON, tags=["int-int", "integration", "int"])
def integration(session: nox.Session) -> None:
    """Run integration tests with real temp git repos and mocked external APIs."""
    session.install("-e", ".[test,all]")
    session.run("pytest", "-m", "integration", "tests/integration/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["int-cli", "integration", "int"])
def integration_cli(session: nox.Session) -> None:
    """Run CLI integration tests only."""
    session.install("-e", ".[test,all]")
    session.run("pytest", "-m", "integration", "tests/integration/cli/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["int-git", "integration", "int"])
def integration_git(session: nox.Session) -> None:
    """Run git-worktree integration tests only."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/git/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["int-pr", "integration", "int"])
def integration_pr(session: nox.Session) -> None:
    """Run PR integration tests with provider API calls mocked."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/pr/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["int-workflows", "integration", "int"])
def integration_workflows(session: nox.Session) -> None:
    """Run power-user workflow integration tests only."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "integration", "tests/integration/workflows/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["performance"])
def performance(session: nox.Session) -> None:
    """Check CLI cold-start latency budgets (help and bash completion)."""
    session.install("-e", ".[test]")
    session.run("pytest", "-m", "performance", "tests/performance/", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["docs"])
def docs(session: nox.Session) -> None:
    """Build documentation with mkdocs --strict (zero warnings)."""
    session.env["NO_MKDOCS_2_WARNING"] = "1"
    session.install("-e", ".[docs]")
    session.run("mkdocs", "build", "--strict", *session.posargs)


@nox.session(python=CI_PYTHON, tags=["docs"])
def docs_serve(session: nox.Session) -> None:
    """Serve docs locally with live reload (http://127.0.0.1:8000)."""
    session.env["NO_MKDOCS_2_WARNING"] = "1"
    session.install("-e", ".[docs]")
    session.run("mkdocs", "serve", *session.posargs)


@nox.session(python=DEFAULT_PYTHON)
def check_syntax(session: nox.Session) -> None:
    """Byte-compile all sources to catch syntax errors fast."""
    session.run("python", "-m", "compileall", "-q", SRC, external=False)


@nox.session(python=DEFAULT_PYTHON)
def check_types(session: nox.Session) -> None:
    """Static type checking with mypy."""
    session.install("-e", ".[type-check,all]")
    session.run("mypy", "--package", PACKAGE)


@nox.session(python=DEFAULT_PYTHON, tags=["quality", "lint"])
def lint(session: nox.Session) -> None:
    """Run ruff lint (pycodestyle, pyflakes, isort rules) and ruff format --check."""
    session.install("-e", ".[lint]")
    session.run("ruff", "check", SRC, "tests", "noxfile.py")
    session.run("ruff", "format", "--check", SRC, "tests", "noxfile.py")


@nox.session(python=DEFAULT_PYTHON, tags=["quality", "format"])
def format(session: nox.Session) -> None:  # noqa: A001 - keep conventional session name
    """Auto-fix with ruff (incl. import order) and format with ruff format (local only)."""
    session.install("-e", ".[lint]")
    session.run("ruff", "check", "--fix", SRC, "tests", "noxfile.py")
    session.run("ruff", "format", SRC, "tests", "noxfile.py")


@nox.session(python=DEFAULT_PYTHON)
def necessary_imports(session: nox.Session) -> None:
    """Detect undeclared/unused dependencies with fawltydeps."""
    session.install("-e", ".[code-quality,all]")
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
        "aihealth",
        "vulture",
        "commitizen",
        "fawltydeps",
        "mike",
        "mkdocs",
        "mkdocs-material",
        "mkdocs-snippets",
        "mkdocstrings",
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


@nox.session(name="code-health", python=CI_PYTHON, tags=["quality"])
def code_health(session: nox.Session) -> None:
    """Run ai-health (profile in .aihealth.toml); arguments go straight to ``aihealth``.

    Default: ``delta`` (working tree vs HEAD). Examples: ``nox -s code-health -- scan .``,
    ``nox -s code-health -- delta --base origin/main --format json``.
    See docs/contributor-guide/code-health.md.
    """
    _install_aihealth(session)
    command, *rest = session.posargs or ["delta"]
    # scan/delta read <path>/.aihealth.toml and silently fall back to defaults without --config;
    # the other subcommands reject the option.
    options = ("--config", AIHEALTH_CONFIG) if command in ("scan", "delta") else ()
    session.run("aihealth", command, *options, *rest)


def _install_aihealth(session: nox.Session) -> None:
    """Install exactly the locked ``code-health`` dependency group (the single ai-health pin)."""
    session.run_install(
        "uv",
        "sync",
        "--frozen",
        "--only-group",
        "code-health",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )


def _component_scores(session: nox.Session) -> dict[str, float]:
    scores = {}
    for component in AIHEALTH_COMPONENTS:
        out = session.run(
            "aihealth", "scan", component, "--config", AIHEALTH_CONFIG, "--format", "json", silent=True
        )
        scores[component] = json.loads(str(out))["score"]
    return scores


@nox.session(name="code-health-components", python=CI_PYTHON, tags=["quality"])
def code_health_components(session: nox.Session) -> None:
    """Fail when an ai-health component score (repo, src, tests) drops vs the merge-base.

    ai-health compares files (``delta``) but not component scores between two commits, so the
    base commit is exported and scanned with the same profile. Base ref defaults to origin/main.
    """
    _install_aihealth(session)
    ref = session.posargs[0] if session.posargs else "origin/main"
    base = subprocess.run(["git", "merge-base", ref, "HEAD"], capture_output=True, text=True, check=False)
    if base.returncode != 0:
        session.error(f"git merge-base {ref} HEAD failed: {base.stderr.strip()}")
    head_scores = _component_scores(session)
    with tempfile.TemporaryDirectory(prefix="aihealth-base-") as tmp:
        archive = subprocess.run(["git", "archive", base.stdout.strip()], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
        with session.chdir(tmp):
            base_scores = _component_scores(session)
    dropped = []
    for component in AIHEALTH_COMPONENTS:
        before, after = base_scores[component], head_scores[component]
        session.log(f"component {component}: {before:.2f} -> {after:.2f}")
        if after < before:
            dropped.append(component)
    if dropped:
        session.error(f"component score dropped: {', '.join(dropped)}")


@nox.session(python=DEFAULT_PYTHON, venv_backend="none")
def install_dev(session: nox.Session) -> None:
    """Install the package with all dev extras into the active environment."""
    session.run("python", "-m", "pip", "install", "-e", ".[dev]", external=True)
