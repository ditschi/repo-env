"""``renv clone`` discovery against a paginated ``gh api`` (multi-page orgs/repos).

Regression: ``gh api --paginate --jq '[...]'`` prints one JSON array *per
page*; parsing that as a single JSON document failed silently and every
wildcard ``--include`` reported "No repositories matched".
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.cli.app import app
from tests.integration.support import fake_gh
from tests.integration.support.gitfixtures import RepoFactory

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="fake gh needs 'jq' to emulate --jq")

_RADAR = ["radar-a", "radar-b", "radar-c", "radar-d", "radar-e"]
# Matching repos are spread across pages 1-4 (page size 2).
_ACME_REPOS = ["other-1", "radar-a", "other-2", "radar-b", "radar-c", "other-3", "radar-d", "radar-e"]


def _install_fake_gh(root: Path, monkeypatch: pytest.MonkeyPatch, data: dict[str, list[object]]) -> None:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake_gh.__file__}" "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    data_file = root / "gh-data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_DATA", str(data_file))
    monkeypatch.setenv("FAKE_GH_PAGE_SIZE", "2")


def _redirect_github_to(remotes: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``https://github.com/<owner>/<repo>.git`` clone from local bare repos."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{remotes}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")


def _repo_entries(names: list[str]) -> list[object]:
    return [{"name": name, "full_name": f"acme/{name}"} for name in names]


def test_clone_wildcard_repo_finds_matches_on_every_page(
    repo_factory: RepoFactory, testenv_root: Path, repoenv_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _RADAR:
        repo_factory.make_bare_and_clone(f"acme/{name}")
    _install_fake_gh(testenv_root, monkeypatch, {"orgs/acme/repos": _repo_entries(_ACME_REPOS)})
    _redirect_github_to(repo_factory.remotes, monkeypatch)
    dest = testenv_root / "cloned"

    result = CliRunner().invoke(
        app,
        [
            "clone",
            "--url",
            "https://github.com",
            "--include",
            "acme/radar-*",
            "--protocol",
            "https",
            "--source",
            str(dest),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Resolved 5 repositories" in result.output
    cloned = sorted(p.name for p in (dest / "github.com" / "acme").iterdir())
    assert cloned == _RADAR
    assert all((dest / "github.com" / "acme" / name / "README.md").is_file() for name in _RADAR)


def test_clone_wildcard_owner_finds_org_on_later_membership_page(
    testenv_root: Path, repoenv_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memberships = [
        {"organization": {"login": "zeta"}, "role": "member", "state": "active"},
        {"organization": {"login": "beta"}, "role": "member", "state": "active"},
        {"organization": {"login": "acme"}, "role": "admin", "state": "active"},
    ]
    _install_fake_gh(
        testenv_root,
        monkeypatch,
        {
            "user/memberships/orgs": memberships,
            "orgs/zeta/repos": [{"name": "unrelated"}],
            "orgs/beta/repos": [{"name": "unrelated"}],
            "orgs/acme/repos": _repo_entries(_ACME_REPOS),
        },
    )

    result = CliRunner().invoke(
        app,
        [
            "clone",
            "--url",
            "https://github.com",
            "--include",
            "*/radar-*",
            "--protocol",
            "https",
            "--source",
            str(testenv_root / "cloned"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    for name in _RADAR:
        assert f"github.com/acme/{name}" in result.output
    assert "Resolved 5 repositories" in result.output
