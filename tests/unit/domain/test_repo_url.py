from __future__ import annotations

import pytest

from repoenv.domain.repo_url import UrlSpec, build_clone_url, parse_url
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
