"""OAuth 2.0 (authorization-code + PKCE) for Gmail and Outlook/Microsoft.

Desktop apps can't keep a secret, so this uses the loopback-redirect installed-app
flow with PKCE: open the system browser to the provider's consent page, receive
the authorization code on ``http://127.0.0.1:<port>``, exchange it for access +
refresh tokens, and thereafter refresh the short-lived access token on demand.
The access token authenticates IMAP/SMTP via the SASL **XOAUTH2** mechanism.

Corvid must be registered once with each provider to obtain a **client id**
(Google Cloud / Azure) — there is no way around it; the id is read from config.
Network and browser calls are injected so the flow's logic is unit-testable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..errors import AuthError, NetworkError


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    name: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    uses_client_secret: bool
    auth_extra: tuple[tuple[str, str], ...] = ()


GOOGLE = OAuthProvider(
    name="Google",
    auth_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=("https://mail.google.com/",),
    uses_client_secret=True,  # Google issues a (non-confidential) secret for desktop apps
    auth_extra=(("access_type", "offline"), ("prompt", "consent")),
)

MICROSOFT = OAuthProvider(
    name="Microsoft",
    auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
    scopes=(
        "https://outlook.office.com/IMAP.AccessAsUser.All",
        "https://outlook.office.com/SMTP.Send",
        "offline_access",
    ),
    uses_client_secret=False,  # public client, PKCE only
)

PROVIDERS = {"google": GOOGLE, "microsoft": MICROSOFT}


@dataclass(frozen=True, slots=True)
class OAuthClient:
    provider: OAuthProvider
    client_id: str
    client_secret: str = ""


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int = 0


def build_clients(
    google_id: str, google_secret: str, microsoft_id: str
) -> dict[str, OAuthClient]:
    """Assemble the configured provider clients (empty ids are skipped)."""
    clients: dict[str, OAuthClient] = {}
    if google_id:
        clients["google"] = OAuthClient(GOOGLE, google_id, google_secret)
    if microsoft_id:
        clients["microsoft"] = OAuthClient(MICROSOFT, microsoft_id)
    return clients


# -- pure helpers (unit-tested) ---------------------------------------------

def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(
    client: OAuthClient, redirect_uri: str, state: str, code_challenge: str
) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(client.provider.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        **dict(client.provider.auth_extra),
    }
    return f"{client.provider.auth_url}?{urllib.parse.urlencode(params)}"


def parse_redirect(path: str) -> tuple[str, str]:
    """Extract (code, state) from the loopback redirect path; raise on error."""
    query = urllib.parse.urlparse(path).query
    params = urllib.parse.parse_qs(query)
    if "error" in params:
        raise AuthError(f"Authorization denied: {params['error'][0]}")
    if "code" not in params:
        raise AuthError("Authorization response contained no code.")
    return params["code"][0], params.get("state", [""])[0]


def parse_token_response(payload: dict[str, object]) -> OAuthTokens:
    if "error" in payload:
        raise AuthError(f"Token endpoint error: {payload.get('error')}")
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise AuthError("Token response missing access_token.")
    refresh = payload.get("refresh_token")
    raw_expires = payload.get("expires_in", 0)
    return OAuthTokens(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) else "",
        expires_in=int(raw_expires) if isinstance(raw_expires, (int, str)) else 0,
    )


def xoauth2(email: str, access_token: str) -> bytes:
    """Build the SASL XOAUTH2 initial-client-response (raw, un-base64'd)."""
    return f"user={email}\x01auth=Bearer {access_token}\x01\x01".encode()


# -- network ----------------------------------------------------------------

def _post_form(url: str, form: dict[str, str]) -> dict[str, object]:
    data = urllib.parse.urlencode(form).encode("ascii")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https token endpoint
            return json.loads(response.read().decode("utf-8"))  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))  # type: ignore[no-any-return]
        except (ValueError, OSError):
            raise AuthError(f"Token request failed ({exc.code}).") from exc
    except OSError as exc:
        raise NetworkError(str(exc)) from exc


PostForm = Callable[[str, dict[str, str]], dict[str, object]]


def exchange_code(
    client: OAuthClient, code: str, verifier: str, redirect_uri: str,
    *, post: PostForm = _post_form,
) -> OAuthTokens:
    form = {
        "client_id": client.client_id,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client.provider.uses_client_secret and client.client_secret:
        form["client_secret"] = client.client_secret
    return parse_token_response(post(client.provider.token_url, form))


def refresh_access_token(
    client: OAuthClient, refresh_token: str, *, post: PostForm = _post_form
) -> str:
    form = {
        "client_id": client.client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client.provider.uses_client_secret and client.client_secret:
        form["client_secret"] = client.client_secret
    return parse_token_response(post(client.provider.token_url, form)).access_token


# -- interactive loopback flow ----------------------------------------------

@dataclass
class _Capture:
    path: str = ""
    error: str = ""
    done: bool = field(default=False)


def authorize(
    client: OAuthClient,
    *,
    open_browser: Callable[[str], bool] | None = None,
    bind_host: str = "127.0.0.1",
    timeout: float = 180.0,
) -> OAuthTokens:
    """Run the full interactive flow and return tokens (blocks until the user
    approves in the browser or ``timeout`` elapses). Requires network + a browser.
    """
    import webbrowser

    opener = open_browser or webbrowser.open
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(16)
    capture = _Capture()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            capture.path = self.path
            capture.done = True
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif'>"
                b"<h2>Signed in to Corvid</h2>"
                b"<p>You can close this tab and return to the app.</p>"
                b"</body></html>"
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - base API name
            return  # silence default stderr request logging

    server = HTTPServer((bind_host, 0), _Handler)
    server.timeout = timeout
    try:
        redirect_uri = f"http://{bind_host}:{server.server_port}"
        opener(build_auth_url(client, redirect_uri, state, challenge))
        server.handle_request()  # blocks for one callback (or times out)
    finally:
        server.server_close()

    if not capture.done:
        raise AuthError("Sign-in timed out; no response from the browser.")
    code, returned_state = parse_redirect(capture.path)
    if returned_state != state:
        raise AuthError("OAuth state mismatch (possible CSRF); sign-in aborted.")
    return exchange_code(client, code, verifier, redirect_uri)
