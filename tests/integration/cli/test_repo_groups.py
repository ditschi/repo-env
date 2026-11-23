"""Named repo groups: ``renv config groups.<name> <pattern>`` + ``--include @name``.

Feature idea, not a regression: saves retyping a glob you use constantly
(e.g. "every backend service") across ``create``/``add``/``repair`` instead
of hand-writing the same pattern every time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support.gitfixtures import RepoFactory
from tests.integration.support.renv_helpers import init_renv


def test_config_groups_set_get_unset(repoenv_home: Path) -> None:
    runner = CliRunner()

    set_result = runner.invoke(app, ["config", "groups.backend", "*/backend-*"])
    assert set_result.exit_code == 0, set_result.output

    get_result = runner.invoke(app, ["config", "groups.backend"])
    assert get_result.exit_code == 0
    assert get_result.output.strip() == "*/backend-*"

    unset_result = runner.invoke(app, ["config", "groups.backend", "--unset"])
    assert unset_result.exit_code == 0

    get_after_unset = runner.invoke(app, ["config", "groups.backend"])
    assert get_after_unset.output.strip() == ""


GROUP_CASES = [
    # (repos in source, --include value, repos expected in the environment)
    (("backend-alpha", "backend-beta", "frontend-app"), "@backend", {"backend-alpha", "backend-beta"}),
    (("backend-alpha", "frontend-app", "tool-x"), "@backend,frontend-*", {"backend-alpha", "frontend-app"}),
]


@pytest.mark.usefixtures("repoenv_home")
@pytest.mark.parametrize("case", GROUP_CASES, ids=["group-only", "group-and-literal-glob"])
def test_create_include_expands_repo_group(
    repo_factory: RepoFactory, source_dir: Path, worktrees_dir: Path, case: tuple
) -> None:
    repos, include, expected = case
    for name in repos:
        repo_factory.make_bare_and_clone(name)

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["config", "groups.backend", "backend-*"]).exit_code == 0

    create = runner.invoke(app, ["create", "svc", "--include", include])
    assert create.exit_code == 0, create.output
    assert {name for name in repos if (worktrees_dir / "svc" / name).exists()} == expected


def test_unknown_group_errors_clearly(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("alpha")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)

    result = runner.invoke(app, ["create", "svc", "--include", "@nope"])
    assert result.exit_code != 0
    assert result.exception is not None
    message = getattr(result.exception, "message", str(result.exception))
    assert "nope" in message


def test_add_include_also_expands_repo_group(
    repo_factory: RepoFactory, repoenv_home: Path, source_dir: Path, worktrees_dir: Path
) -> None:
    repo_factory.make_bare_and_clone("backend-alpha")
    repo_factory.make_bare_and_clone("backend-beta")

    runner = CliRunner()
    init_renv(runner, source=source_dir, worktrees=worktrees_dir)
    assert runner.invoke(app, ["config", "groups.backend", "backend-*"]).exit_code == 0
    assert runner.invoke(app, ["create", "svc", "--include", "backend-alpha"]).exit_code == 0

    add = runner.invoke(app, ["add", "svc", "--include", "@backend"])
    assert add.exit_code == 0, add.output
    assert (worktrees_dir / "svc" / "backend-beta").exists()
