"""Common types for SCM provider adapters used by ``renv clone`` discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from urllib.parse import urlsplit, urlunsplit

from repoenv.adapters.scm import credentials
from repoenv.adapters.scm.credentials import Credential, env_vars_for
from repoenv.domain.scm import ProviderKind
from repoenv.errors import GitError, UsageError


@dataclass(frozen=True)
class OrgMembership:
    """One top-level owner (org, group, workspace, project) the authenticated user belongs to."""

    login: str
    role: str  # "admin" or "member"
    state: str  # "active" or "pending"


@dataclass(frozen=True)
class RemoteRepo:
    """One repository reported by a provider API."""

    owner: str  # may be nested, e.g. "group/sub" or "org/project"
    name: str
    https_url: str
    ssh_url: str

    def clone_url(self, protocol: str) -> str:
        """Return the provider-reported clone URL for ``protocol`` ('ssh' or 'https')."""
        return self.ssh_url if protocol == "ssh" and self.ssh_url else self.https_url


class ScmProvider(ABC):
    """Repository discovery for one host.

    Implementations import their (optional) client library lazily so that
    literal clones and unrelated commands never pay for it.
    """

    kind: ProviderKind
    label: str
    # True when ``list_repos(name_hint=...)`` narrows results server-side.
    supports_name_hint = False

    def __init__(
        self,
        host: str,
        *,
        base_url: str | None = None,
        credential_source: Callable[[], Credential | None] | None = None,
    ) -> None:
        self.host = host
        self.base_url = (base_url or f"https://{host}").rstrip("/")
        self._credential_source = credential_source

    @cached_property
    def credential(self) -> Credential | None:
        """API credential, looked up on first use (see ``credentials.resolve``)."""
        if self._credential_source is not None:
            return self._credential_source()
        return credentials.resolve(self.kind, self.host)

    @abstractmethod
    def list_repos(self, owner: str, *, name_hint: str | None = None) -> list[RemoteRepo]:
        """Return every repo below top-level ``owner`` (including nested owners where supported).

        ``name_hint`` is an optional server-side pre-filter; callers still match
        the exact glob on the result.
        """

    @abstractmethod
    def list_memberships(self) -> list[OrgMembership]:
        """Return the top-level owners the authenticated user belongs to."""

    def default_protocol(self) -> str:
        """Clone protocol to use when ``--protocol`` isn't given."""
        return "ssh"

    def auth_hint(self) -> str:
        """Hint shown when the API rejects or requires authentication."""
        names = " or ".join(env_vars_for(self.kind, self.host))
        return (
            f"Set {names}, or store credentials for https://{self.host} in a git "
            "credential helper (e.g. 'git credential approve' / Git Credential Manager)."
        )

    def api_error(self, action: str, exc: Exception) -> GitError:
        """Wrap a client-library failure without leaking request details such as tokens."""
        return GitError(f"{self.label} API error on {self.host} while {action}: {exc}", hint=self.auth_hint())


def missing_extra(extra: str, label: str) -> UsageError:
    """Error for a provider whose optional client library isn't installed."""
    return UsageError(
        f"{label} support is not installed.",
        hint=(
            f"Install the extra: uv tool install --reinstall 'repo-env[{extra}]' "
            f"(or pip install 'repo-env[{extra}]')."
        ),
    )


def strip_userinfo(url: str) -> str:
    """Drop ``user@`` from an https clone URL (Bitbucket/Azure embed the account name)."""
    parts = urlsplit(url)
    if not parts.username or parts.scheme not in ("http", "https"):
        return url
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))
