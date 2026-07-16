from __future__ import annotations

from pathlib import Path

import pytest

from repoenv.adapters.gh_adapter import OrgMembership
from repoenv.errors import GitError, NothingMatchedError, UsageError
from repoenv.services import clone_service
from repoenv.services.clone_service import Action, Role


def test_resolve_fully_qualified_url_needs_no_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clone_service.gh_adapter,
        "list_org_memberships",
        lambda **_: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        clone_service.gh_adapter,
        "list_owner_repos",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com/owner/repo"],
        include=[],
        exclude=[],
        protocol="ssh",
    )

    assert len(result.repos) == 1
    repo = result.repos[0]
    assert (repo.host, repo.owner, repo.repo) == ("github.com", "owner", "repo")
    assert repo.clone_url == "git@github.com:owner/repo.git"
    assert repo.relative_path == "github.com/owner/repo"
    assert result.warnings == []


def test_resolve_literal_owner_literal_repo_needs_no_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clone_service.gh_adapter,
        "list_org_memberships",
        lambda **_: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        clone_service.gh_adapter,
        "list_owner_repos",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["owner/repo1,owner/repo2"],
        exclude=[],
        protocol="https",
    )

    assert sorted((r.owner, r.repo) for r in result.repos) == [("owner", "repo1"), ("owner", "repo2")]


def test_resolve_literal_owner_wildcard_repo_lists_owner_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_list_owner_repos(owner, *, host=None):
        assert owner == "myself"
        return ["test-alpha", "test-beta", "other"]

    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", _fake_list_owner_repos)

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["myself/test-*"],
        exclude=[],
        protocol="ssh",
    )

    assert sorted(r.repo for r in result.repos) == ["test-alpha", "test-beta"]


def test_resolve_wildcard_owner_uses_org_memberships_by_default_role_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = [
        OrgMembership(login="acme-core", role="admin", state="active"),
        OrgMembership(login="acme-labs", role="member", state="active"),
        OrgMembership(login="other-corp", role="member", state="active"),
    ]
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: memberships)
    monkeypatch.setattr(
        clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: [f"{owner}-repo1", f"{owner}-repo2"]
    )

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["acme-*/*"],
        exclude=[],
        protocol="ssh",
    )

    owners = sorted({r.owner for r in result.repos})
    assert owners == ["acme-core", "acme-labs"]
    assert result.warnings == []


def test_resolve_wildcard_owner_reports_skipped_orgs(monkeypatch: pytest.MonkeyPatch) -> None:
    memberships = [
        OrgMembership(login="acme-core", role="admin", state="active"),
        OrgMembership(login="acme-pending", role="member", state="pending"),
    ]
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: memberships)
    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: [f"{owner}-repo"])

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["acme-*/*"],
        exclude=[],
        protocol="ssh",
    )

    assert {r.owner for r in result.repos} == {"acme-core"}
    assert any("acme-pending" in w for w in result.warnings)
    assert any("member" in w for w in result.warnings)


def test_resolve_wildcard_owner_falls_back_to_any_role_when_default_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = [OrgMembership(login="acme-core", role="member", state="pending")]
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: memberships)
    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: [f"{owner}-repo"])

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["acme-*/*"],
        exclude=[],
        protocol="ssh",
        role=Role.MEMBER,
        role_explicit=False,
    )

    assert {r.owner for r in result.repos} == {"acme-core"}
    assert any("automatically retried with --role any" in w for w in result.warnings)


def test_resolve_wildcard_owner_does_not_fall_back_when_role_was_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = [OrgMembership(login="acme-core", role="member", state="pending")]
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: memberships)

    with pytest.raises(NothingMatchedError):
        clone_service.resolve_clone_targets(
            urls=["https://github.com"],
            include=["acme-*/*"],
            exclude=[],
            protocol="ssh",
            role=Role.MEMBER,
            role_explicit=True,
        )


def test_resolve_role_owner_only_keeps_admin_orgs(monkeypatch: pytest.MonkeyPatch) -> None:
    memberships = [
        OrgMembership(login="acme-core", role="admin", state="active"),
        OrgMembership(login="acme-labs", role="member", state="active"),
    ]
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: memberships)
    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: [f"{owner}-repo"])

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["acme-*/*"],
        exclude=[],
        protocol="ssh",
        role=Role.OWNER,
        role_explicit=True,
    )

    assert {r.owner for r in result.repos} == {"acme-core"}


def test_resolve_no_candidate_owners_raises_nothing_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clone_service.gh_adapter, "list_org_memberships", lambda **_: [])

    with pytest.raises(NothingMatchedError):
        clone_service.resolve_clone_targets(
            urls=["https://github.com"],
            include=["acme-*/*"],
            exclude=[],
            protocol="ssh",
        )


def test_resolve_exclude_removes_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=["owner/repo1,owner/repo2"],
        exclude=["owner/repo2"],
        protocol="ssh",
    )

    assert [(r.owner, r.repo) for r in result.repos] == [("owner", "repo1")]


def test_resolve_url_with_owner_segment_restricts_to_that_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: ["repo-a", "repo-b"])

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com/my-org"],
        include=["*/*"],
        exclude=[],
        protocol="ssh",
    )

    assert {r.owner for r in result.repos} == {"my-org"}
    assert sorted(r.repo for r in result.repos) == ["repo-a", "repo-b"]


def test_resolve_default_include_is_match_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clone_service.gh_adapter,
        "list_org_memberships",
        lambda **_: [OrgMembership(login="acme", role="admin", state="active")],
    )
    monkeypatch.setattr(clone_service.gh_adapter, "list_owner_repos", lambda owner, **_: ["repo-a"])

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com"],
        include=[],
        exclude=[],
        protocol="ssh",
    )

    assert {(r.owner, r.repo) for r in result.repos} == {("acme", "repo-a")}


def test_resolve_requires_at_least_one_url() -> None:
    with pytest.raises(UsageError):
        clone_service.resolve_clone_targets(urls=[], include=[], exclude=[], protocol="ssh")


def test_resolve_without_explicit_protocol_queries_gh_config_once_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def _fake_git_protocol(host=None):
        calls.append(host)
        return "https"

    monkeypatch.setattr(clone_service.gh_adapter, "git_protocol", _fake_git_protocol)

    result = clone_service.resolve_clone_targets(
        urls=["https://github.com/owner/repo1", "https://github.com/owner/repo2"],
        include=[],
        exclude=[],
    )

    assert calls == ["github.com"]  # queried once, cached for the second repo on the same host
    assert all(r.clone_url.startswith("https://") for r in result.repos)


def test_resolve_deduplicates_across_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    result = clone_service.resolve_clone_targets(
        urls=["https://github.com/owner/repo", "https://github.com/owner/repo"],
        include=[],
        exclude=[],
        protocol="ssh",
    )

    assert len(result.repos) == 1


def _resolved_repo(**kwargs) -> clone_service.ResolvedRepo:
    defaults = dict(host="github.com", owner="owner", repo="repo", clone_url="git@github.com:owner/repo.git")
    defaults.update(kwargs)
    return clone_service.ResolvedRepo(**defaults)


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
