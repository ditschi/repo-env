from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters.scm import detect
from repoenv.adapters.scm.base import OrgMembership, RemoteRepo, ScmProvider
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError, NothingMatchedError, UsageError
from repoenv.services import clone_service
from repoenv.services.clone_service import Action, ResolvedRepo, Role


class FakeProvider(ScmProvider):
    kind = ProviderKind.GITHUB
    label = "Fake"

    def __init__(
        self,
        host: str,
        *,
        repos: dict[str, list[RemoteRepo]] | None = None,
        memberships: list[OrgMembership] | None = None,
        kind: ProviderKind = ProviderKind.GITHUB,
        supports_name_hint: bool = False,
        protocol: str = "ssh",
    ) -> None:
        super().__init__(host, credential_source=lambda: None)
        self.kind = kind
        self.supports_name_hint = supports_name_hint
        self.repos = repos or {}
        self.memberships = memberships or []
        self.protocol = protocol
        self.list_calls: list[tuple[str, str | None]] = []
        self.protocol_calls = 0

    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        self.list_calls.append((owner, name_hint))
        if owner not in self.repos:
            raise GitError(f"unknown owner {owner}")
        return self.repos[owner]

    def list_memberships(self) -> list[OrgMembership]:
        return self.memberships

    def default_protocol(self) -> str:
        self.protocol_calls += 1
        return self.protocol


def _repo(owner: str, name: str, host: str = "github.com") -> RemoteRepo:
    return RemoteRepo(
        owner=owner,
        name=name,
        https_url=f"https://{host}/{owner}/{name}.git",
        ssh_url=f"git@{host}:{owner}/{name}.git",
    )


def _use(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider | None) -> list[ProviderKind]:
    """Route make_provider to ``provider`` (or fail if it's ``None``); returns the kinds requested."""
    kinds: list[ProviderKind] = []

    def _make(kind, host, *, base_url):
        kinds.append(kind)
        if provider is None:
            raise AssertionError("no provider API should be needed")
        return provider

    monkeypatch.setattr(detect, "make_provider", _make)
    return kinds


def _resolve(**kwargs):
    kwargs.setdefault("include", [])
    kwargs.setdefault("exclude", [])
    return clone_service.resolve_clone_targets(**kwargs)


def test_resolve_fully_qualified_url_needs_no_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, None)

    result = _resolve(urls=["https://github.com/owner/repo"], protocol="ssh")

    assert len(result.repos) == 1
    repo = result.repos[0]
    assert (repo.host, repo.owner, repo.repo) == ("github.com", "owner", "repo")
    assert repo.clone_url == "git@github.com:owner/repo.git"
    assert repo.relative_path == "github.com/owner/repo"
    assert result.warnings == []


def test_resolve_literal_owner_literal_repo_needs_no_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, None)

    result = _resolve(urls=["https://github.com"], include=["owner/repo1,owner/repo2"], protocol="https")

    assert sorted((r.owner, r.repo) for r in result.repos) == [("owner", "repo1"), ("owner", "repo2")]


def test_resolve_literal_owner_wildcard_repo_lists_owner_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "github.com",
        repos={"myself": [_repo("myself", n) for n in ("test-alpha", "test-beta", "other")]},
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com"], include=["myself/test-*"], protocol="ssh")

    assert sorted(r.repo for r in result.repos) == ["test-alpha", "test-beta"]
    assert provider.list_calls == [("myself", None)]


def test_resolve_uses_clone_urls_reported_by_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    remote = RemoteRepo(
        owner="PROJ",
        name="svc",
        https_url="https://bb.corp/scm/proj/svc.git",
        ssh_url="ssh://git@bb.corp:7999/proj/svc.git",
    )
    provider = FakeProvider("bb.corp", repos={"PROJ": [remote]}, kind=ProviderKind.BITBUCKET_SERVER)
    _use(monkeypatch, provider)

    result = _resolve(
        urls=["https://bb.corp"],
        include=["PROJ/*"],
        protocol="ssh",
        provider=ProviderKind.BITBUCKET_SERVER,
    )

    assert [r.clone_url for r in result.repos] == ["ssh://git@bb.corp:7999/proj/svc.git"]


def test_resolve_wildcard_owner_uses_org_memberships_by_default_role_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        "github.com",
        memberships=[
            OrgMembership(login="acme-core", role="admin", state="active"),
            OrgMembership(login="acme-labs", role="member", state="active"),
            OrgMembership(login="other-corp", role="member", state="active"),
        ],
        repos={
            o: [_repo(o, f"{o}-repo1"), _repo(o, f"{o}-repo2")]
            for o in ("acme-core", "acme-labs", "other-corp")
        },
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com"], include=["acme-*/*"], protocol="ssh")

    assert sorted({r.owner for r in result.repos}) == ["acme-core", "acme-labs"]
    assert result.warnings == []


def test_resolve_wildcard_owner_reports_skipped_orgs(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "github.com",
        memberships=[
            OrgMembership(login="acme-core", role="admin", state="active"),
            OrgMembership(login="acme-pending", role="member", state="pending"),
        ],
        repos={"acme-core": [_repo("acme-core", "r")]},
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com"], include=["acme-*/*"], protocol="ssh")

    assert {r.owner for r in result.repos} == {"acme-core"}
    assert any("acme-pending" in w and "member" in w for w in result.warnings)


def test_resolve_wildcard_owner_falls_back_to_any_role_when_default_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        "github.com",
        memberships=[OrgMembership(login="acme-core", role="member", state="pending")],
        repos={"acme-core": [_repo("acme-core", "r")]},
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com"], include=["acme-*/*"], protocol="ssh")

    assert {r.owner for r in result.repos} == {"acme-core"}
    assert any("automatically retried with --role any" in w for w in result.warnings)


def test_resolve_wildcard_owner_does_not_fall_back_when_role_was_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(
        "github.com", memberships=[OrgMembership(login="acme-core", role="member", state="pending")]
    )
    _use(monkeypatch, provider)

    with pytest.raises(NothingMatchedError):
        _resolve(
            urls=["https://github.com"],
            include=["acme-*/*"],
            protocol="ssh",
            role=Role.MEMBER,
            role_explicit=True,
        )


def test_resolve_role_owner_only_keeps_admin_orgs(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "github.com",
        memberships=[
            OrgMembership(login="acme-core", role="admin", state="active"),
            OrgMembership(login="acme-labs", role="member", state="active"),
        ],
        repos={o: [_repo(o, "r")] for o in ("acme-core", "acme-labs")},
    )
    _use(monkeypatch, provider)

    result = _resolve(
        urls=["https://github.com"], include=["acme-*/*"], protocol="ssh", role=Role.OWNER, role_explicit=True
    )

    assert {r.owner for r in result.repos} == {"acme-core"}


def test_resolve_no_candidate_owners_raises_nothing_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeProvider("github.com"))

    with pytest.raises(NothingMatchedError):
        _resolve(urls=["https://github.com"], include=["acme-*/*"], protocol="ssh")


def test_resolve_exclude_removes_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, None)

    result = _resolve(
        urls=["https://github.com"],
        include=["owner/repo1,owner/repo2"],
        exclude=["owner/repo2"],
        protocol="ssh",
    )

    assert [(r.owner, r.repo) for r in result.repos] == [("owner", "repo1")]


def test_resolve_url_with_owner_segment_restricts_to_that_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "github.com", repos={"my-org": [_repo("my-org", "repo-a"), _repo("my-org", "repo-b")]}
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com/my-org"], include=["*/*"], protocol="ssh")

    assert {r.owner for r in result.repos} == {"my-org"}
    assert sorted(r.repo for r in result.repos) == ["repo-a", "repo-b"]


def test_resolve_default_include_is_match_all(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "github.com",
        memberships=[OrgMembership(login="acme", role="admin", state="active")],
        repos={"acme": [_repo("acme", "repo-a")]},
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com"], protocol="ssh")

    assert {(r.owner, r.repo) for r in result.repos} == {("acme", "repo-a")}


def test_resolve_requires_at_least_one_url() -> None:
    with pytest.raises(UsageError):
        _resolve(urls=[], protocol="ssh")


def test_resolve_without_explicit_protocol_asks_provider_once_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider("github.com", protocol="https")
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://github.com/owner/repo1", "https://github.com/owner/repo2"])

    assert provider.protocol_calls == 1
    assert all(r.clone_url.startswith("https://") for r in result.repos)


def test_resolve_gitlab_nested_groups_listed_once_from_top_level_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = "gitlab.com"
    provider = FakeProvider(
        host,
        kind=ProviderKind.GITLAB,
        supports_name_hint=True,
        repos={
            "grp": [
                _repo("grp", "radar-top", host),
                _repo("grp/sub", "radar-a", host),
                _repo("grp/sub/deeper", "radar-b", host),
                _repo("grp/other", "radar-c", host),
                _repo("grp/sub", "unrelated", host),
            ]
        },
    )
    _use(monkeypatch, provider)

    sub_only = _resolve(urls=["https://gitlab.com"], include=["grp/sub/radar-*"], protocol="ssh")
    everywhere = _resolve(urls=["https://gitlab.com"], include=["grp/*/radar-*"], protocol="ssh")

    assert [(r.owner, r.repo) for r in sub_only.repos] == [("grp/sub", "radar-a")]
    assert sub_only.repos[0].relative_path == "gitlab.com/grp/sub/radar-a"
    assert sorted((r.owner, r.repo) for r in everywhere.repos) == [
        ("grp/other", "radar-c"),
        ("grp/sub", "radar-a"),
        ("grp/sub/deeper", "radar-b"),
    ]
    assert provider.list_calls == [("grp", "radar"), ("grp", "radar")]


def test_resolve_name_hint_only_for_a_single_repo_glob(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(
        "gitlab.com",
        kind=ProviderKind.GITLAB,
        supports_name_hint=True,
        repos={"grp": [_repo("grp", "radar-a"), _repo("grp", "tool-b")]},
    )
    _use(monkeypatch, provider)

    result = _resolve(urls=["https://gitlab.com"], include=["grp/radar-*,grp/tool-*"], protocol="ssh")

    assert sorted(r.repo for r in result.repos) == ["radar-a", "tool-b"]
    assert provider.list_calls == [("grp", None)]


def test_resolve_no_name_hint_when_provider_cannot_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider("github.com", repos={"acme": [_repo("acme", "radar-a")]})
    _use(monkeypatch, provider)

    _resolve(urls=["https://github.com"], include=["acme/radar-*"], protocol="ssh")

    assert provider.list_calls == [("acme", None)]


def test_resolve_azure_org_url_includes_all_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    host = "dev.azure.com"
    provider = FakeProvider(
        host,
        kind=ProviderKind.AZURE_DEVOPS,
        repos={"org": [_repo("org/proj-a", "svc", host), _repo("org/proj-b", "lib", host)]},
    )
    kinds = _use(monkeypatch, provider)

    result = _resolve(urls=["https://dev.azure.com/org"], protocol="https")

    assert sorted((r.owner, r.repo) for r in result.repos) == [("org/proj-a", "svc"), ("org/proj-b", "lib")]
    assert kinds == [ProviderKind.AZURE_DEVOPS]


def test_resolve_azure_literal_repo_url_needs_no_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, None)

    result = _resolve(urls=["https://dev.azure.com/org/My%20Project/_git/svc"], protocol="https")

    assert [(r.owner, r.repo) for r in result.repos] == [("org/My Project", "svc")]
    assert result.repos[0].clone_url == "https://dev.azure.com/org/My%20Project/_git/svc"


def test_resolve_unknown_host_discovery_asks_for_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "probe", lambda host: None)
    _use(monkeypatch, None)

    with pytest.raises(UsageError, match="Could not determine which SCM provider") as excinfo:
        _resolve(urls=["https://git.corp.example"], include=["team/*"], protocol="ssh")
    assert "providers.git.corp.example" in (excinfo.value.hint or "")


def test_resolve_unknown_host_literal_repo_uses_generic_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "probe", lambda host: None)
    _use(monkeypatch, None)

    result = _resolve(urls=["git@git.corp.example:team/repo.git"], protocol="ssh")

    assert [r.clone_url for r in result.repos] == ["git@git.corp.example:team/repo.git"]


def test_resolve_provider_setting_from_config_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "probe", lambda host: pytest.fail("configured hosts must not be probed"))
    provider = FakeProvider(
        "git.corp.example", kind=ProviderKind.GITLAB, repos={"team": [_repo("team", "a")]}
    )
    seen: dict[str, object] = {}

    def _make(kind, host, *, base_url):
        seen.update(kind=kind, base_url=base_url)
        return provider

    monkeypatch.setattr(detect, "make_provider", _make)

    result = _resolve(
        urls=["https://git.corp.example"],
        include=["team/*"],
        protocol="ssh",
        provider_settings={"git.corp.example": "gitlab https://git.corp.example/gitlab"},
    )

    assert [r.repo for r in result.repos] == ["a"]
    assert seen == {"kind": ProviderKind.GITLAB, "base_url": "https://git.corp.example/gitlab"}


def test_resolve_deduplicates_across_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, None)

    result = _resolve(urls=["https://github.com/owner/repo", "https://github.com/owner/repo"], protocol="ssh")

    assert len(result.repos) == 1


def _resolved_repo(**kwargs) -> ResolvedRepo:
    defaults = dict(host="github.com", owner="owner", repo="repo", clone_url="git@github.com:owner/repo.git")
    defaults.update(kwargs)
    return ResolvedRepo(**defaults)


def test_clone_or_update_clones_missing_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _resolved_repo()
    calls: dict[str, object] = {}

    def _fake_clone(url, dest):
        calls["url"] = url
        calls["dest"] = dest
        dest.mkdir(parents=True)

    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: False)
    monkeypatch.setattr(clone_service.git_adapter, "clone", _fake_clone)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=False, reset_default=False, force=False
    )

    assert outcome.action == Action.CLONED
    assert calls["url"] == repo.clone_url


def test_clone_or_update_clone_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: False)

    def _fail_clone(url, dest):
        raise GitError("boom")

    monkeypatch.setattr(clone_service.git_adapter, "clone", _fail_clone)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=False, reset_default=False, force=False
    )

    assert outcome.action == Action.FAILED
    assert "boom" in outcome.detail


def test_clone_or_update_existing_repo_without_flags_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(
        clone_service.git_adapter, "fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch"))
    )

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=False, reset_default=False, force=False
    )

    assert outcome.action == Action.UNCHANGED


def test_clone_or_update_update_fast_forwards_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "current_branch", lambda path: "main")
    monkeypatch.setattr(clone_service.git_adapter, "fast_forward", lambda path, ref: True)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=True, reset_default=False, force=False
    )

    assert outcome.action == Action.UPDATED
    assert "origin/main" in outcome.detail


def test_clone_or_update_update_skips_when_dirty_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: False)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=True, reset_default=False, force=False
    )

    assert outcome.action == Action.SKIPPED
    assert "local changes" in outcome.detail


def test_clone_or_update_update_skips_when_diverged_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "current_branch", lambda path: "main")
    monkeypatch.setattr(clone_service.git_adapter, "fast_forward", lambda path, ref: False)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=True, reset_default=False, force=False
    )

    assert outcome.action == Action.SKIPPED
    assert "diverged" in outcome.detail


def test_clone_or_update_update_force_resets_hard_when_diverged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    calls: dict[str, object] = {}
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: False)
    monkeypatch.setattr(clone_service.git_adapter, "current_branch", lambda path: "main")
    monkeypatch.setattr(
        clone_service.git_adapter, "reset_hard", lambda path, ref: calls.setdefault("ref", ref)
    )

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=True, reset_default=False, force=True
    )

    assert outcome.action == Action.UPDATED
    assert calls["ref"] == "origin/main"


def test_clone_or_update_update_skips_detached_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _resolved_repo()
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "current_branch", lambda path: None)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=True, reset_default=False, force=False
    )

    assert outcome.action == Action.SKIPPED
    assert "detached" in outcome.detail


def test_execute_clone_plan_sequential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos = [_resolved_repo(repo="repo-a"), _resolved_repo(repo="repo-b")]
    cloned: list[str] = []

    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: False)
    monkeypatch.setattr(clone_service.git_adapter, "clone", lambda url, dest: cloned.append(dest.name))

    outcomes = clone_service.execute_clone_plan(
        repos, source=tmp_path, update=False, reset_default=False, force=False, jobs=1
    )

    assert {o.action for o in outcomes} == {Action.CLONED}
    assert sorted(cloned) == ["repo-a", "repo-b"]


def test_execute_clone_plan_parallel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos = [_resolved_repo(repo="repo-a"), _resolved_repo(repo="repo-b"), _resolved_repo(repo="repo-c")]

    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: False)
    monkeypatch.setattr(clone_service.git_adapter, "clone", lambda url, dest: None)

    outcomes = clone_service.execute_clone_plan(
        repos, source=tmp_path, update=False, reset_default=False, force=False, jobs=4
    )

    assert len(outcomes) == 3
    assert [o.repo.repo for o in outcomes] == ["repo-a", "repo-b", "repo-c"]


def test_clone_or_update_reset_default_checks_out_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _resolved_repo()
    calls: dict[str, object] = {}
    monkeypatch.setattr(clone_service.git_adapter, "is_git_repo", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(clone_service.git_adapter, "is_clean", lambda path: True)
    monkeypatch.setattr(clone_service.git_adapter, "default_branch", lambda path, remote: "main")

    def _fake_checkout_tracking(path, branch, *, remote, force):
        calls["branch"] = branch
        calls["force"] = force

    monkeypatch.setattr(clone_service.git_adapter, "checkout_tracking", _fake_checkout_tracking)

    outcome = clone_service.clone_or_update(
        repo, source=tmp_path, update=False, reset_default=True, force=False
    )

    assert outcome.action == Action.UPDATED
    assert calls["branch"] == "main"
    assert calls["force"] is False
    assert "main" in outcome.detail
