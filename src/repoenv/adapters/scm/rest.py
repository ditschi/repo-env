"""Minimal JSON-over-HTTPS client (stdlib only) for providers without a client library and for probing.

Redirects are never followed so an ``Authorization`` header can't be
forwarded to another host; a 3xx comes back as a normal response.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
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


@dataclass(frozen=True)
class HttpRequest:
    """One JSON request: target URL, verb, optional JSON body, extra headers and timeout."""

    url: str
    method: str = "GET"
    payload: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 15.0

    def to_urllib(self) -> urllib.request.Request:
        headers = {"Accept": "application/json", "User-Agent": "repo-env", **self.headers}
        data = None
        if self.payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(self.payload).encode()
        return urllib.request.Request(  # noqa: S310 - scheme checked by send()
            self.url, headers=headers, method=self.method, data=data
        )


def send(request: HttpRequest) -> HttpResponse:
    """Send ``request`` without following redirects (including for writes).

    Non-2xx statuses are returned, not raised; connection failures raise ``GitError``.
    """
    if urlsplit(request.url).scheme not in ("http", "https"):
        raise GitError(f"Refusing non-HTTP URL: {request.url}")
    urllib_request = request.to_urllib()
    try:
        with _OPENER.open(urllib_request, timeout=request.timeout) as response:
            return HttpResponse(response.status, _lower(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, _lower(exc.headers), exc.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise GitError(f"Could not reach {urlsplit(request.url).netloc}: {reason}") from exc


def _lower(headers: Message) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


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
