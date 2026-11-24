"""Named repo groups: ``renv config groups.<name> <pattern>`` + ``--include @name``.

Feature idea, not a regression: saves retyping a glob you use constantly
(e.g. "every backend service") across ``create``/``add``/``repair`` instead
of hand-writing the same pattern every time.
"""

from __future__ import annotations

import pytest

from tests.integration.support.gitfixtures import existing_repos
from tests.integration.support.renv_helpers import Renv


def _setup_with_backend_group(renv: Renv, *names: str) -> None:
    renv.setup(*names)
    renv.ok("config", "groups.backend", "backend-*")


def test_config_groups_set_get_unset(renv: Renv) -> None:
    renv.ok("config", "groups.backend", "*/backend-*")

    get_result = renv.ok("config", "groups.backend")
    assert get_result.output.strip() == "*/backend-*"

    renv.ok("config", "groups.backend", "--unset")

    get_after_unset = renv.invoke("config", "groups.backend")
    assert get_after_unset.output.strip() == ""


GROUP_CASES = [
    # (repos in source, --include value, repos expected in the environment)
    (("backend-alpha", "backend-beta", "frontend-app"), "@backend", {"backend-alpha", "backend-beta"}),
    (("backend-alpha", "frontend-app", "tool-x"), "@backend,frontend-*", {"backend-alpha", "frontend-app"}),
]


@pytest.mark.parametrize("case", GROUP_CASES, ids=["group-only", "group-and-literal-glob"])
def test_create_include_expands_repo_group(renv: Renv, case: tuple) -> None:
    repos, include, expected = case
    _setup_with_backend_group(renv, *repos)

    renv.ok("create", "svc", "--include", include)
    assert existing_repos(renv.worktrees / "svc", repos) == expected


def test_unknown_group_errors_clearly(renv: Renv) -> None:
    renv.setup("alpha")

    result = renv.invoke("create", "svc", "--include", "@nope")
    assert result.exit_code != 0
    assert result.exception is not None
    message = getattr(result.exception, "message", str(result.exception))
    assert "nope" in message


def test_add_include_also_expands_repo_group(renv: Renv) -> None:
    _setup_with_backend_group(renv, "backend-alpha", "backend-beta")
    renv.ok("create", "svc", "--include", "backend-alpha")

    renv.ok("add", "svc", "--include", "@backend")
    assert (renv.worktrees / "svc" / "backend-beta").exists()
