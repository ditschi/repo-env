"""Minimal JSON-over-HTTPS client (stdlib only) for providers without a client library and for probing.

Redirects are never followed so an ``Authorization`` header can't be
forwarded to another host; a 3xx comes back as a normal response.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from repoenv.adapters.scm.credentials import Credential
from repoenv.errors import GitError


@dataclass(frozen=True)
class HttpResponse:
    """Status, lower-cased headers, and raw body of one request."""

    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def ok(self) -> bool:
        """True for 2xx responses."""
        return 200 <= self.status < 300

    def json(self) -> Any:
        """Decode the body as JSON; returns ``None`` when it isn't JSON (e.g. an HTML login page)."""
        try:
            return json.loads(self.body)
        except ValueError:
            return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002 - signature fixed by urllib
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 15.0) -> HttpResponse:
    """GET ``url``. Non-2xx statuses are returned, not raised; connection failures raise ``GitError``."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise GitError(f"Refusing non-HTTP URL: {url}")
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, headers={"Accept": "application/json", "User-Agent": "repo-env", **(headers or {})}
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return HttpResponse(response.status, _lower(response.headers.items()), response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, _lower(exc.headers.items()), exc.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise GitError(f"Could not reach {urlsplit(url).netloc}: {reason}") from exc


def _lower(items: Any) -> dict[str, str]:
    return {key.lower(): value for key, value in items}


def auth_headers(credential: Credential | None, *, token_scheme: str = "Bearer") -> dict[str, str]:
    """``Authorization`` header: basic auth when a username is known, else ``<token_scheme> <token>``.

    ``token_scheme="Basic"`` sends a bare token as basic-auth password with an empty username.
    """
    if credential is None:
        return {}
    if credential.username is not None or token_scheme == "Basic":
        pair = f"{credential.username or ''}:{credential.secret}".encode()
        return {"Authorization": f"Basic {base64.b64encode(pair).decode()}"}
    return {"Authorization": f"{token_scheme} {credential.secret}"}
