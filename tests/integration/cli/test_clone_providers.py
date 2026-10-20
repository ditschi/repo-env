"""``renv clone`` discovery end-to-end against every supported SCM provider.

The real client libraries (PyGithub, python-gitlab, atlassian-python-api)
and the stdlib REST clients talk to an in-process fake API with two items
per page, so multi-page listings are always exercised; discovered repos are
then really cloned from local bare repos.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoenv.adapters.scm import credentials, detect
from repoenv.cli.app import app
from repoenv.domain.scm import ProviderKind
from tests.integration.support.fake_scm import FakeRepo, FakeScmData, FakeScmServer
from tests.integration.support.gitfixtures import RepoFactory

_TOKENS = {
    "GH_ENTERPRISE_TOKEN": "gh-secret",
    "GITLAB_TOKEN": "gl-secret",
    "BITBUCKET_TOKEN": "bb-secret",
    "AZURE_DEVOPS_EXT_PAT": "az-secret",
    "GITEA_TOKEN": "gt-secret",
}
_TOKEN_BY_KIND = {
    ProviderKind.GITHUB: "gh-secret",
    ProviderKind.GITLAB: "gl-secret",
    ProviderKind.BITBUCKET_CLOUD: "bb-secret",
    ProviderKind.BITBUCKET_SERVER: "bb-secret",
    ProviderKind.AZURE_DEVOPS: "az-secret",
    ProviderKind.GITEA: "gt-secret",
}
_LISTING_KINDS = [
    ProviderKind.GITHUB,
    ProviderKind.GITLAB,
    ProviderKind.BITBUCKET_CLOUD,
    ProviderKind.BITBUCKET_SERVER,
    ProviderKind.GITEA,
]
_RADAR = ["radar-a", "radar-b", "radar-c"]
# Matches are spread over pages 1-3 of a 2-item page size.
_ACME = ["other-1", "radar-a", "other-2", "radar-b", "radar-c"]


@pytest.fixture()
def scm_env(repoenv_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GL_TOKEN", "BITBUCKET_USERNAME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in _TOKENS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(credentials.shutil, "which", lambda name: None)
    detect.probe.cache_clear()


@pytest.fixture()
def remotes(repo_factory: RepoFactory) -> Path:
    return repo_factory.remotes


def _server(remotes: Path, repos: list[FakeRepo], memberships=()) -> FakeScmServer:
    return FakeScmServer(FakeScmData(remotes=remotes, repos=repos, memberships=list(memberships)))


def _make_bare(repo_factory: RepoFactory, repos: list[FakeRepo]) -> None:
    for repo in repos:
        repo_factory.make_bare_and_clone(f"{repo.owner}/{repo.name}")


def _clone(kind: ProviderKind, server: FakeScmServer, dest: Path, *args: str, url_path: str = "") -> object:
    host = f"{kind.value}.test"
    runner = CliRunner()
    configured = runner.invoke(app, ["config", f"providers.{host}", f"{kind.value} {server.base_url}"])
    assert configured.exit_code == 0, configured.output
    return runner.invoke(
        app,
        ["clone", "--url", f"https://{host}{url_path}", "--protocol", "https", "--source", str(dest), *args],
    )


def _carries_token(headers: set[str], token: str) -> bool:
    encoded = {base64.b64encode(f"{user}:{token}".encode()).decode() for user in ("", "x-token-auth")}
    return any(token in header or any(e in header for e in encoded) for header in headers)


def _cloned(dest: Path, host: str) -> Iterator[str]:
    root = dest / host
    return (str(p.parent.relative_to(root)) for p in sorted(root.rglob("README.md")))


@pytest.mark.parametrize("kind", _LISTING_KINDS, ids=lambda k: k.value)
def test_clone_repo_glob_across_pages(
    kind: ProviderKind, scm_env: None, repo_factory: RepoFactory, remotes: Path, testenv_root: Path
) -> None:
    repos = [FakeRepo("acme", name) for name in _ACME]
    _make_bare(repo_factory, [r for r in repos if r.name in _RADAR])
    dest = testenv_root / "cloned"

    with _server(remotes, repos) as server:
        result = _clone(kind, server, dest, "--include", "acme/radar-*")

    assert result.exit_code == 0, result.output
    assert sorted(_cloned(dest, f"{kind.value}.test")) == [f"acme/{name}" for name in _RADAR]
    assert _carries_token(server.seen.auth_headers, _TOKEN_BY_KIND[kind])


@pytest.mark.parametrize("kind", _LISTING_KINDS, ids=lambda k: k.value)
def test_clone_wildcard_owner_from_memberships_across_pages(
    kind: ProviderKind, scm_env: None, remotes: Path, testenv_root: Path
) -> None:
    repos = [FakeRepo("acme", name) for name in _ACME] + [FakeRepo("beta", "radar-x")]
    memberships = [("zeta", "member", "active"), ("beta", "member", "active"), ("acme", "admin", "active")]

    with _server(remotes, repos, memberships) as server:
        result = _clone(kind, server, testenv_root / "cloned", "--include", "*/radar-*", "--dry-run")

    assert result.exit_code == 0, result.output
    for name in _RADAR:
        assert f"acme/{name}" in result.output
    assert "beta/radar-x" in result.output
    assert "Resolved 4 repositories" in result.output


def test_clone_gitlab_subgroups_with_server_side_search(
    scm_env: None, repo_factory: RepoFactory, remotes: Path, testenv_root: Path
) -> None:
    repos = [
        FakeRepo("grp", "radar-top"),
        FakeRepo("grp/sub", "radar-a"),
        FakeRepo("grp/sub", "tools"),
        FakeRepo("grp/sub", "radar-b"),
        FakeRepo("grp/sub/deep", "radar-c"),
    ]
    _make_bare(repo_factory, [r for r in repos if r.owner == "grp/sub" and r.name.startswith("radar")])
    dest = testenv_root / "cloned"

    with _server(remotes, repos) as server:
        result = _clone(ProviderKind.GITLAB, server, dest, "--include", "grp/sub/radar-*")

    assert result.exit_code == 0, result.output
    assert sorted(_cloned(dest, "gitlab.test")) == ["grp/sub/radar-a", "grp/sub/radar-b"]
    listing = [p for p in server.seen.paths if p.startswith("/api/v4/groups/grp/projects")]
    assert listing and all("search=radar" in p and "include_subgroups=True" in p for p in listing)


def test_clone_azure_devops_organization(
    scm_env: None, repo_factory: RepoFactory, remotes: Path, testenv_root: Path
) -> None:
    repos = [FakeRepo("acme/web", "frontend"), FakeRepo("acme/svc", "api"), FakeRepo("other/x", "y")]
    _make_bare(repo_factory, repos[:2])
    dest = testenv_root / "cloned"

    with _server(remotes, repos) as server:
        result = _clone(ProviderKind.AZURE_DEVOPS, server, dest, url_path="/acme")

    assert result.exit_code == 0, result.output
    assert sorted(_cloned(dest, "azure-devops.test")) == ["acme/svc/api", "acme/web/frontend"]
    assert _carries_token(server.seen.auth_headers, "az-secret")


def test_clone_github_without_token_uses_paginated_rest(
    scm_env: None, remotes: Path, testenv_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "resolve", lambda kind, host: None)
    repos = [FakeRepo("acme", name) for name in _ACME]

    with _server(remotes, repos) as server:
        result = _clone(
            ProviderKind.GITHUB, server, testenv_root / "cloned", "--include", "acme/radar-*", "--dry-run"
        )

    assert result.exit_code == 0, result.output
    assert "Resolved 3 repositories" in result.output
    assert sum(p.startswith("/api/v3/orgs/acme/repos") for p in server.seen.paths) == 3
    assert server.seen.auth_headers == set()
