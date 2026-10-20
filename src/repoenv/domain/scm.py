"""SCM provider kinds and host-based provider guessing for ``renv clone``.

Pure logic only: which provider a host *probably* is (from well-known SaaS
hosts and hostname labels) and parsing of the ``providers.<host>`` config
value. Network probing lives in ``adapters.scm.detect``.
"""

from __future__ import annotations

from enum import Enum

from repoenv.errors import UsageError


class ProviderKind(str, Enum):
    """Supported SCM hosting products."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET_CLOUD = "bitbucket-cloud"
    BITBUCKET_SERVER = "bitbucket-server"
    AZURE_DEVOPS = "azure-devops"
    GITEA = "gitea"


KNOWN_HOSTS: dict[str, ProviderKind] = {
    "github.com": ProviderKind.GITHUB,
    "gitlab.com": ProviderKind.GITLAB,
    "bitbucket.org": ProviderKind.BITBUCKET_CLOUD,
    "dev.azure.com": ProviderKind.AZURE_DEVOPS,
    "ssh.dev.azure.com": ProviderKind.AZURE_DEVOPS,
    "codeberg.org": ProviderKind.GITEA,
    "gitea.com": ProviderKind.GITEA,
}

# Kinds that can be recognised by probing an unknown self-hosted server, in default probe order.
PROBEABLE_KINDS: tuple[ProviderKind, ...] = (
    ProviderKind.GITHUB,
    ProviderKind.GITLAB,
    ProviderKind.BITBUCKET_SERVER,
    ProviderKind.GITEA,
)

_HOSTNAME_HINTS: tuple[tuple[str, ProviderKind], ...] = (
    ("github", ProviderKind.GITHUB),
    ("ghe", ProviderKind.GITHUB),
    ("gitlab", ProviderKind.GITLAB),
    ("bitbucket", ProviderKind.BITBUCKET_SERVER),
    ("stash", ProviderKind.BITBUCKET_SERVER),
    ("gitea", ProviderKind.GITEA),
    ("forgejo", ProviderKind.GITEA),
)

# Kinds whose repositories can sit below more than one owner level
# (GitLab subgroups, Azure DevOps organization/project).
NESTED_OWNER_KINDS = frozenset({ProviderKind.GITLAB, ProviderKind.AZURE_DEVOPS})


def known_kind(host: str) -> ProviderKind | None:
    """Return the provider of a well-known SaaS host, or ``None``."""
    host = host.lower()
    if host in KNOWN_HOSTS:
        return KNOWN_HOSTS[host]
    if host.endswith(".visualstudio.com"):
        return ProviderKind.AZURE_DEVOPS
    return None


def hinted_kind(host: str) -> ProviderKind | None:
    """Guess a provider from hostname labels, e.g. ``github.corp.example`` -> GitHub Enterprise."""
    labels = host.lower().split(".")
    for label in labels:
        for needle, kind in _HOSTNAME_HINTS:
            if needle in label.split("-"):
                return kind
    return None


def probe_order(host: str) -> list[ProviderKind]:
    """Probe candidates for ``host``: the hostname hint first, then every other probeable kind."""
    hint = hinted_kind(host)
    order = [hint] if hint in PROBEABLE_KINDS else []
    return order + [kind for kind in PROBEABLE_KINDS if kind not in order]


def parse_provider_setting(value: str) -> tuple[ProviderKind, str | None]:
    """Parse a ``providers.<host>`` config value: ``"<kind>"`` or ``"<kind> <api-base-url>"``."""
    parts = value.split()
    kinds = ", ".join(kind.value for kind in ProviderKind)
    if not parts or len(parts) > 2:
        raise UsageError(
            f"Invalid provider setting {value!r}.",
            hint=f"Use '<kind>' or '<kind> <base-url>' where kind is one of: {kinds}.",
        )
    try:
        kind = ProviderKind(parts[0].lower())
    except ValueError as exc:
        raise UsageError(f"Unknown provider {parts[0]!r}.", hint=f"Use one of: {kinds}.") from exc
    base_url = parts[1].rstrip("/") if len(parts) == 2 else None
    if base_url is not None and not base_url.startswith(("https://", "http://")):
        raise UsageError(
            f"Invalid base URL {base_url!r} for provider {kind.value}.", hint="Use an http(s) URL."
        )
    return kind, base_url
