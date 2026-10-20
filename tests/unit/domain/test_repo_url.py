from __future__ import annotations

import pytest

from repoenv.domain.repo_url import UrlSpec, build_clone_url, parse_url, url_host
from repoenv.domain.scm import ProviderKind
from repoenv.errors import UsageError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com", UrlSpec(host="github.com")),
        ("https://github.com/", UrlSpec(host="github.com")),
        ("https://github.company.com", UrlSpec(host="github.company.com")),
        ("https://github.com/my-org", UrlSpec(host="github.com", owner="my-org")),
        (
            "https://github.com/owner/repo",
            UrlSpec(host="github.com", owner="owner", repo="repo"),
        ),
        (
            "https://github.com/owner/repo.git",
            UrlSpec(host="github.com", owner="owner", repo="repo"),
        ),
        (
            "git@github.com:owner/repo.git",
            UrlSpec(host="github.com", owner="owner", repo="repo"),
        ),
        (
            "ssh://git@github.com/owner/repo.git",
            UrlSpec(host="github.com", owner="owner", repo="repo"),
        ),
    ],
)
def test_parse_url(raw: str, expected: UrlSpec) -> None:
    assert parse_url(raw) == expected


def test_url_spec_is_fully_qualified() -> None:
    assert UrlSpec(host="github.com", owner="o", repo="r").is_fully_qualified is True
    assert UrlSpec(host="github.com", owner="o").is_fully_qualified is False
    assert UrlSpec(host="github.com").is_fully_qualified is False


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url at all !!",
        "https://github.com/owner/repo/extra",
    ],
)
def test_parse_url_rejects_invalid(raw: str) -> None:
    with pytest.raises(UsageError):
        parse_url(raw)


def test_build_clone_url_ssh() -> None:
    assert build_clone_url("github.com", "owner", "repo", protocol="ssh") == "git@github.com:owner/repo.git"


def test_build_clone_url_https() -> None:
    assert (
        build_clone_url("github.com", "owner", "repo", protocol="https")
        == "https://github.com/owner/repo.git"
    )


def test_build_clone_url_unknown_protocol() -> None:
    with pytest.raises(UsageError):
        build_clone_url("github.com", "owner", "repo", protocol="ftp")


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        # GitLab: nested groups, web UI paths
        ("https://gitlab.com/grp", ProviderKind.GITLAB, UrlSpec("gitlab.com", "grp")),
        ("https://gitlab.com/grp/sub/repo", ProviderKind.GITLAB, UrlSpec("gitlab.com", "grp/sub", "repo")),
        ("git@gitlab.com:grp/sub/repo.git", ProviderKind.GITLAB, UrlSpec("gitlab.com", "grp/sub", "repo")),
        (
            "https://gitlab.com/grp/repo/-/tree/main",
            ProviderKind.GITLAB,
            UrlSpec("gitlab.com", "grp", "repo"),
        ),
        # Bitbucket Server: /scm, /projects, /users, ssh with port
        (
            "https://bb.corp/scm/PROJ/repo.git",
            ProviderKind.BITBUCKET_SERVER,
            UrlSpec("bb.corp", "PROJ", "repo"),
        ),
        (
            "https://bb.corp/projects/PROJ/repos/repo/browse",
            ProviderKind.BITBUCKET_SERVER,
            UrlSpec("bb.corp", "PROJ", "repo"),
        ),
        ("https://bb.corp/projects/PROJ", ProviderKind.BITBUCKET_SERVER, UrlSpec("bb.corp", "PROJ")),
        (
            "https://bb.corp/users/alice/repos/dots",
            ProviderKind.BITBUCKET_SERVER,
            UrlSpec("bb.corp", "~alice", "dots"),
        ),
        (
            "ssh://git@bb.corp:7999/proj/repo.git",
            ProviderKind.BITBUCKET_SERVER,
            UrlSpec("bb.corp", "proj", "repo"),
        ),
        # Bitbucket Cloud / Gitea: GitHub-style
        (
            "https://user@bitbucket.org/ws/repo.git",
            ProviderKind.BITBUCKET_CLOUD,
            UrlSpec("bitbucket.org", "ws", "repo"),
        ),
        ("https://codeberg.org/org/repo", ProviderKind.GITEA, UrlSpec("codeberg.org", "org", "repo")),
    ],
)
def test_parse_url_provider_layouts(raw: str, kind: ProviderKind, expected: UrlSpec) -> None:
    assert parse_url(raw, kind) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://dev.azure.com/org", UrlSpec("dev.azure.com", "org")),
        ("https://dev.azure.com/org/proj", UrlSpec("dev.azure.com", "org/proj")),
        ("https://dev.azure.com/org/proj/_git/repo", UrlSpec("dev.azure.com", "org/proj", "repo")),
        (
            "https://org@dev.azure.com/org/My%20Proj/_git/repo",
            UrlSpec("dev.azure.com", "org/My Proj", "repo"),
        ),
        ("git@ssh.dev.azure.com:v3/org/proj/repo", UrlSpec("dev.azure.com", "org/proj", "repo")),
        ("https://org.visualstudio.com/proj/_git/repo", UrlSpec("dev.azure.com", "org/proj", "repo")),
    ],
)
def test_parse_url_azure_devops_is_detected_from_host(raw: str, expected: UrlSpec) -> None:
    assert parse_url(raw) == expected
    assert url_host(raw) == "dev.azure.com"


@pytest.mark.parametrize(
    ("kind", "host", "owner", "protocol", "expected"),
    [
        (ProviderKind.GITLAB, "gitlab.com", "grp/sub", "ssh", "git@gitlab.com:grp/sub/repo.git"),
        (ProviderKind.BITBUCKET_SERVER, "bb.corp", "PROJ", "https", "https://bb.corp/scm/PROJ/repo.git"),
        (ProviderKind.BITBUCKET_SERVER, "bb.corp", "PROJ", "ssh", "ssh://git@bb.corp:7999/PROJ/repo.git"),
        (
            ProviderKind.AZURE_DEVOPS,
            "dev.azure.com",
            "org/My Proj",
            "https",
            "https://dev.azure.com/org/My%20Proj/_git/repo",
        ),
        (
            ProviderKind.AZURE_DEVOPS,
            "dev.azure.com",
            "org/proj",
            "ssh",
            "git@ssh.dev.azure.com:v3/org/proj/repo",
        ),
        (ProviderKind.AZURE_DEVOPS, "tfs.corp", "coll/proj", "ssh", "ssh://tfs.corp:22/coll/proj/_git/repo"),
    ],
)
def test_build_clone_url_provider_layouts(
    kind: ProviderKind, host: str, owner: str, protocol: str, expected: str
) -> None:
    assert build_clone_url(host, owner, "repo", protocol=protocol, kind=kind) == expected
