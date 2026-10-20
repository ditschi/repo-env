"""API credentials for SCM providers, resolved without ever prompting.

Lookup order per host:

1. Provider environment variables (``GH_TOKEN``, ``GITLAB_TOKEN``, ...).
2. GitHub only: ``gh auth token --hostname <host>`` when the GitHub CLI is installed.
3. ``git credential fill`` for ``https://<host>`` -- whatever credential
   helper already serves your HTTPS clones (Git Credential Manager,
   libsecret, osxkeychain, store, ...). Prompts are disabled.
4. Anonymous (public data only; some listings require authentication).

Secrets are only ever sent to the host they were looked up for.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from repoenv.domain.scm import ProviderKind

_ENV_VARS: dict[ProviderKind, tuple[str, ...]] = {
    ProviderKind.GITHUB: ("GH_TOKEN", "GITHUB_TOKEN"),
    ProviderKind.GITLAB: ("GITLAB_TOKEN", "GL_TOKEN"),
    ProviderKind.BITBUCKET_CLOUD: ("BITBUCKET_TOKEN",),
    ProviderKind.BITBUCKET_SERVER: ("BITBUCKET_TOKEN",),
    ProviderKind.AZURE_DEVOPS: ("AZURE_DEVOPS_EXT_PAT", "AZURE_DEVOPS_TOKEN"),
    ProviderKind.GITEA: ("GITEA_TOKEN", "FORGEJO_TOKEN"),
}
# Same split as the GitHub CLI: enterprise hosts use their own variables.
_GHE_ENV_VARS = ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
_USERNAME_ENV_VARS: dict[ProviderKind, str] = {
    ProviderKind.BITBUCKET_CLOUD: "BITBUCKET_USERNAME",
    ProviderKind.BITBUCKET_SERVER: "BITBUCKET_USERNAME",
}
_VALID_HOST = re.compile(r"^[A-Za-z0-9.-]+(:[0-9]+)?$")
_TIMEOUT_S = 15


@dataclass(frozen=True)
class Credential:
    """A token (or password) plus optional username for basic auth."""

    secret: str = field(repr=False)
    username: str | None = None


def env_vars_for(kind: ProviderKind, host: str) -> tuple[str, ...]:
    """Environment variables consulted for ``kind`` on ``host``."""
    if kind is ProviderKind.GITHUB and host != "github.com":
        return _GHE_ENV_VARS
    return _ENV_VARS[kind]


def resolve(kind: ProviderKind, host: str) -> Credential | None:
    """Return the first credential found for ``host``, or ``None`` for anonymous access."""
    for name in env_vars_for(kind, host):
        value = os.environ.get(name, "").strip()
        if value:
            username_var = _USERNAME_ENV_VARS.get(kind)
            username = os.environ.get(username_var, "").strip() if username_var else ""
            return Credential(value, username or None)
    if not _VALID_HOST.match(host):
        return None
    if kind is ProviderKind.GITHUB:
        credential = _from_gh_cli(host)
        if credential is not None:
            return credential
    return _from_git_credential(host)


def _from_gh_cli(host: str) -> Credential | None:
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603,S607 - argv list, no shell
            ["gh", "auth", "token", "--hostname", host],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = result.stdout.strip()
    return Credential(token) if result.returncode == 0 and token else None


def _from_git_credential(host: str) -> Credential | None:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    }
    try:
        result = subprocess.run(  # noqa: S603,S607 - argv list, no shell
            ["git", "-c", "core.askPass=", "-c", "credential.interactive=false", "credential", "fill"],
            input=f"protocol=https\nhost={host}\n\n",
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    password = fields.get("password", "")
    if not password:
        return None
    return Credential(password, fields.get("username") or None)
