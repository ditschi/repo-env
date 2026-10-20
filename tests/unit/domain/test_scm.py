from __future__ import annotations

import pytest

from repoenv.domain.scm import ProviderKind, hinted_kind, known_kind, parse_provider_setting, probe_order
from repoenv.errors import UsageError


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("github.com", ProviderKind.GITHUB),
        ("GitLab.com", ProviderKind.GITLAB),
        ("bitbucket.org", ProviderKind.BITBUCKET_CLOUD),
        ("dev.azure.com", ProviderKind.AZURE_DEVOPS),
        ("myorg.visualstudio.com", ProviderKind.AZURE_DEVOPS),
        ("codeberg.org", ProviderKind.GITEA),
        ("git.corp.example", None),
        ("github.corp.example", None),
    ],
)
def test_known_kind(host: str, expected: ProviderKind | None) -> None:
    assert known_kind(host) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("github.corp.example", ProviderKind.GITHUB),
        ("github-enterprise.corp.example", ProviderKind.GITHUB),
        ("ghe.corp.example", ProviderKind.GITHUB),
        ("gitlab.corp.example", ProviderKind.GITLAB),
        ("bitbucket.corp.example", ProviderKind.BITBUCKET_SERVER),
        ("stash.corp.example", ProviderKind.BITBUCKET_SERVER),
        ("forgejo.corp.example", ProviderKind.GITEA),
        ("git.corp.example", None),
        ("mygithubby.corp.example", None),
    ],
)
def test_hinted_kind(host: str, expected: ProviderKind | None) -> None:
    assert hinted_kind(host) == expected


def test_probe_order_tries_hostname_hint_first() -> None:
    assert probe_order("gitlab.corp.example")[0] is ProviderKind.GITLAB
    assert probe_order("git.corp.example")[0] is ProviderKind.GITHUB
    assert len(set(probe_order("gitlab.corp.example"))) == len(probe_order("gitlab.corp.example"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("gitlab", (ProviderKind.GITLAB, None)),
        ("GitHub", (ProviderKind.GITHUB, None)),
        (
            "bitbucket-server https://bb.corp/bitbucket/",
            (ProviderKind.BITBUCKET_SERVER, "https://bb.corp/bitbucket"),
        ),
    ],
)
def test_parse_provider_setting(value: str, expected: tuple[ProviderKind, str | None]) -> None:
    assert parse_provider_setting(value) == expected


@pytest.mark.parametrize("value", ["", "svn", "gitlab ftp://x", "gitlab https://a https://b"])
def test_parse_provider_setting_rejects_invalid(value: str) -> None:
    with pytest.raises(UsageError):
        parse_provider_setting(value)
