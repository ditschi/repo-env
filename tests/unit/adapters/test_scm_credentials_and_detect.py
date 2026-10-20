from __future__ import annotations

import subprocess
import sys

import pytest

from repoenv.adapters.scm import credentials, detect, rest
from repoenv.adapters.scm.credentials import Credential
from repoenv.domain.scm import ProviderKind
from repoenv.errors import UsageError

_ALL_TOKEN_VARS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GITLAB_TOKEN",
    "GL_TOKEN",
    "BITBUCKET_TOKEN",
    "BITBUCKET_USERNAME",
    "AZURE_DEVOPS_EXT_PAT",
    "AZURE_DEVOPS_TOKEN",
    "GITEA_TOKEN",
    "FORGEJO_TOKEN",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ALL_TOKEN_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(credentials.shutil, "which", lambda name: None)


class _Completed:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_env_token_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-x")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no subprocess expected"))

    assert credentials.resolve(ProviderKind.GITLAB, "gitlab.com") == Credential("glpat-x")


def test_github_enterprise_uses_enterprise_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "public")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "enterprise")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(1))

    assert credentials.resolve(ProviderKind.GITHUB, "github.com") == Credential("public")
    assert credentials.resolve(ProviderKind.GITHUB, "ghe.corp") == Credential("enterprise")


def test_bitbucket_username_is_paired_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BITBUCKET_TOKEN", "app-pw")
    monkeypatch.setenv("BITBUCKET_USERNAME", "alice")

    assert credentials.resolve(ProviderKind.BITBUCKET_CLOUD, "bitbucket.org") == Credential("app-pw", "alice")


def test_git_credential_fill_is_non_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return _Completed(0, "protocol=https\nhost=git.corp\nusername=bob\npassword=s3cret\n")

    monkeypatch.setattr(subprocess, "run", _run)

    assert credentials.resolve(ProviderKind.GITEA, "git.corp") == Credential("s3cret", "bob")
    assert seen["input"] == "protocol=https\nhost=git.corp\n\n"
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "" and env["SSH_ASKPASS"] == ""
    assert "credential.interactive=false" in seen["argv"]


def test_gh_cli_token_used_for_github_when_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credentials.shutil, "which", lambda name: "/usr/bin/gh")
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(argv)
        return _Completed(0, "gho_token\n")

    monkeypatch.setattr(subprocess, "run", _run)

    assert credentials.resolve(ProviderKind.GITHUB, "ghe.corp") == Credential("gho_token")
    assert calls == [["gh", "auth", "token", "--hostname", "ghe.corp"]]


def test_no_credential_means_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(128))

    assert credentials.resolve(ProviderKind.GITLAB, "gitlab.com") is None


def test_suspicious_host_is_never_passed_to_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("must not run"))

    assert credentials.resolve(ProviderKind.GITLAB, "evil\nhost=other") is None


def test_secret_is_not_in_repr() -> None:
    assert "s3cret" not in repr(Credential("s3cret", "bob"))


def test_auth_headers() -> None:
    assert rest.auth_headers(None) == {}
    assert rest.auth_headers(Credential("t")) == {"Authorization": "Bearer t"}
    assert rest.auth_headers(Credential("t"), token_scheme="token") == {"Authorization": "token t"}
    assert rest.auth_headers(Credential("pw", "u")) == {"Authorization": "Basic dTpwdw=="}
    assert rest.auth_headers(Credential("pat"), token_scheme="Basic") == {"Authorization": "Basic OnBhdA=="}


def _fake_get(responses: dict[str, rest.HttpResponse]):
    def _get(url: str, *, headers=None, timeout=15.0) -> rest.HttpResponse:
        for suffix, response in responses.items():
            if url.endswith(suffix):
                return response
        return rest.HttpResponse(404, {}, b"")

    return _get


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (
            {"/api/v3/meta": rest.HttpResponse(401, {"x-github-request-id": "1"}, b"{}")},
            ProviderKind.GITHUB,
        ),
        (
            {"/api/v4/version": rest.HttpResponse(401, {}, b'{"message":"401 Unauthorized"}')},
            ProviderKind.GITLAB,
        ),
        (
            {
                "/rest/api/1.0/application-properties": rest.HttpResponse(
                    200, {}, b'{"version":"8.9.0","displayName":"Bitbucket"}'
                )
            },
            ProviderKind.BITBUCKET_SERVER,
        ),
        ({"/api/v1/version": rest.HttpResponse(200, {}, b'{"version":"1.21.0"}')}, ProviderKind.GITEA),
        ({}, None),
    ],
)
def test_probe_identifies_server(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, rest.HttpResponse], expected: ProviderKind | None
) -> None:
    detect.probe.cache_clear()
    monkeypatch.setattr(rest, "get", _fake_get(responses))

    assert detect.probe("scm.corp.example") == expected


def test_probe_treats_unreachable_host_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    detect.probe.cache_clear()

    def _unreachable(url, **kwargs):
        raise detect.GitError("Could not reach")

    monkeypatch.setattr(rest, "get", _unreachable)

    assert detect.probe("offline.corp.example") is None


def test_detect_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "probe", lambda host: ProviderKind.GITEA)
    settings = {"Git.Corp": "gitlab https://git.corp/gl"}

    assert detect.detect("git.corp", override=None, settings=settings) == (
        ProviderKind.GITLAB,
        "https://git.corp/gl",
    )
    assert detect.detect("git.corp", override=ProviderKind.GITHUB, settings=settings) == (
        ProviderKind.GITHUB,
        "https://git.corp/gl",
    )
    assert detect.detect("other.corp", override=ProviderKind.GITHUB, settings={}) == (
        ProviderKind.GITHUB,
        None,
    )
    assert detect.detect("gitlab.com", override=None, settings={}) == (ProviderKind.GITLAB, None)
    assert detect.detect("other.corp", override=None, settings={}) == (ProviderKind.GITEA, None)


def test_detect_falls_back_to_hostname_hint_when_probes_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "probe", lambda host: None)

    assert detect.detect("gitlab.corp", override=None, settings={}) == (ProviderKind.GITLAB, None)
    assert detect.detect("git.corp", override=None, settings={}) == (None, None)


def test_make_provider_does_not_resolve_credentials_eagerly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credentials, "resolve", lambda kind, host: pytest.fail("resolved too early"))

    provider = detect.make_provider(ProviderKind.GITLAB, "gitlab.com", base_url=None)

    assert provider.kind is ProviderKind.GITLAB
    assert provider.base_url == "https://gitlab.com"


@pytest.mark.parametrize(
    ("kind", "module", "extra"),
    [
        (ProviderKind.GITLAB, "gitlab", "gitlab"),
        (ProviderKind.BITBUCKET_CLOUD, "atlassian", "bitbucket"),
        (ProviderKind.BITBUCKET_SERVER, "atlassian", "bitbucket"),
    ],
)
def test_missing_extra_names_the_extra_to_install(
    monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, module: str, extra: str
) -> None:
    for name in [m for m in sys.modules if m == module or m.startswith(f"{module}.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, module, None)  # makes `import <module>` raise ImportError
    provider = detect.make_provider(kind, "scm.example", base_url=None)

    with pytest.raises(UsageError, match="support is not installed") as excinfo:
        provider.list_repos("acme")
    assert f"repo-env[{extra}]" in (excinfo.value.hint or "")
