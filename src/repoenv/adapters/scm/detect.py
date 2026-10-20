"""Decide which SCM provider serves a host, and build its adapter.

Order: ``--provider`` flag -> ``providers.<host>`` config -> well-known SaaS
hosts -> unauthenticated probes of the host's API (hostname hint first, e.g.
``github.corp.example`` tries GitHub Enterprise before the others) -> the
hostname hint alone when no probe answers.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from repoenv.adapters.scm import rest
from repoenv.adapters.scm.base import ScmProvider
from repoenv.domain.scm import ProviderKind, hinted_kind, known_kind, parse_provider_setting, probe_order
from repoenv.errors import GitError

_PROBE_TIMEOUT_S = 5.0


def _is_github(base_url: str) -> bool:
    response = rest.get(f"{base_url}/api/v3/meta", timeout=_PROBE_TIMEOUT_S)
    return "x-github-request-id" in response.headers or "x-github-enterprise-version" in response.headers


def _is_gitlab(base_url: str) -> bool:
    response = rest.get(f"{base_url}/api/v4/version", timeout=_PROBE_TIMEOUT_S)
    payload = response.json()
    if "x-gitlab-meta" in response.headers:
        return True
    return isinstance(payload, dict) and (
        payload.get("message") == "401 Unauthorized" or {"version", "revision"} <= payload.keys()
    )


def _is_bitbucket_server(base_url: str) -> bool:
    payload = rest.get(f"{base_url}/rest/api/1.0/application-properties", timeout=_PROBE_TIMEOUT_S).json()
    return isinstance(payload, dict) and payload.get("displayName") == "Bitbucket"


def _is_gitea(base_url: str) -> bool:
    response = rest.get(f"{base_url}/api/v1/version", timeout=_PROBE_TIMEOUT_S)
    payload = response.json()
    return response.ok and isinstance(payload, dict) and set(payload) == {"version"}


_PROBES: dict[ProviderKind, Callable[[str], bool]] = {
    ProviderKind.GITHUB: _is_github,
    ProviderKind.GITLAB: _is_gitlab,
    ProviderKind.BITBUCKET_SERVER: _is_bitbucket_server,
    ProviderKind.GITEA: _is_gitea,
}


def _safe_probe(kind: ProviderKind, base_url: str) -> bool:
    try:
        return _PROBES[kind](base_url)
    except GitError:
        return False


@lru_cache(maxsize=None)
def probe(host: str) -> ProviderKind | None:
    """Identify a self-hosted server by its API, probing all candidates in parallel."""
    order = probe_order(host)
    base_url = f"https://{host}"
    with ThreadPoolExecutor(max_workers=len(order)) as pool:
        results = list(pool.map(lambda kind: _safe_probe(kind, base_url), order))
    return next((kind for kind, matched in zip(order, results) if matched), None)


def detect(
    host: str, *, override: ProviderKind | None, settings: dict[str, str]
) -> tuple[ProviderKind | None, str | None]:
    """Return ``(kind, base_url)`` for ``host``; ``kind`` is ``None`` when it can't be determined."""
    configured = {key.lower(): value for key, value in settings.items()}.get(host)
    if configured is not None:
        kind, base_url = parse_provider_setting(configured)
        return override or kind, base_url
    if override is not None:
        return override, None
    return known_kind(host) or probe(host) or hinted_kind(host), None


def make_provider(kind: ProviderKind, host: str, *, base_url: str | None) -> ScmProvider:
    """Instantiate the adapter for ``kind`` (client libraries are imported on first API call)."""
    from repoenv.adapters.scm.azure_provider import AzureDevOpsProvider
    from repoenv.adapters.scm.bitbucket_provider import BitbucketCloudProvider, BitbucketServerProvider
    from repoenv.adapters.scm.gitea_provider import GiteaProvider
    from repoenv.adapters.scm.github_provider import GitHubProvider
    from repoenv.adapters.scm.gitlab_provider import GitLabProvider

    classes: dict[ProviderKind, type[ScmProvider]] = {
        ProviderKind.GITHUB: GitHubProvider,
        ProviderKind.GITLAB: GitLabProvider,
        ProviderKind.BITBUCKET_CLOUD: BitbucketCloudProvider,
        ProviderKind.BITBUCKET_SERVER: BitbucketServerProvider,
        ProviderKind.AZURE_DEVOPS: AzureDevOpsProvider,
        ProviderKind.GITEA: GiteaProvider,
    }
    return classes[kind](host, base_url=base_url)
