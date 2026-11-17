"""Request checks for a server that must only ever be used from this computer.

Binding to 127.0.0.1 keeps other computers out. It does not keep out a web page: any site open in the
browser can make that browser send requests to http://127.0.0.1. These checks are what stop such a page
from reading history or starting (possibly paid) audits.

- Host: must be this server's own loopback address and port. A site that points its own name at 127.0.0.1
  (DNS rebinding) sends its own name here and is refused.
- Origin and Sec-Fetch-Site: a request the browser marks as coming from another site is refused. No CORS
  header is ever sent, so another site could not read an answer anyway.
- Session cookie: everything under /api/ except the health check needs the cookie this server sets when
  its own page is opened (HttpOnly, SameSite=Strict). That covers reads, the progress stream and evidence.
- Action token: anything that changes state also needs a token that only this server's page can fetch, in
  a header a cross-site form cannot set, with a JSON body a form cannot send.
- Requests with no Origin at all come from a local program, not a browser page. They are held to the same
  rule: cookie for reads, cookie and token for changes. There is no path that is trusted for being local.

This is a single-user, local design. It is not authentication for a hosted service; see
docs/DASHBOARD-INTEGRATION.md.
"""

from __future__ import annotations

import hmac
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_HEADER = "x-maya-token"
MAYA_UPLOAD = __import__("re").compile(r"^/api/v1/audits/[0-9a-f]{32}/maya-data/files/[^/]+$")
MAX_UPLOAD_BYTES = 2 * 1024 ** 3  # one Maya export file
COOKIE = "maya_session"
SAFE_METHODS = {"GET", "HEAD"}
CHANGING_METHODS = {"POST", "PUT", "DELETE"}
OPEN_PATHS = {"/api/v1/health"}
MAX_BODY_BYTES = 64 * 1024
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
           "Cross-Origin-Resource-Policy": "same-origin",
           "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()"}


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    """The one shape every error has: a stable code, a sentence for a person, and safe details."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def loopback_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


class Guard:
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self.allowed_origins = frozenset(f"http://{host}" for host in self.allowed_hosts)
        self.token = secrets.token_urlsafe(32)
        self.session = secrets.token_urlsafe(32)

    def refusal(self, request: Request) -> tuple[int, str, str] | None:
        """(status, code, message) when this request is refused, else None."""
        if request.headers.get("host", "").lower() not in self.allowed_hosts:
            return 403, "host_not_allowed", "This server only answers on its own local address."
        origin = request.headers.get("origin")
        if origin is not None and origin.lower() not in self.allowed_origins:
            return 403, "cross_site_request", "Requests from other sites are not accepted."
        # Following a link opens our own document, not another site's access to our API.
        # Never extend this exception to embedded documents, assets or saved reports.
        landing_navigation = (request.method == "GET" and request.url.path == "/"
                              and request.headers.get("sec-fetch-mode") == "navigate"
                              and request.headers.get("sec-fetch-dest") == "document")
        if (request.headers.get("sec-fetch-site", "same-origin").lower() not in ("same-origin", "none")
                and not landing_navigation):
            return 403, "cross_site_request", "Requests from other sites are not accepted."
        path, method = request.url.path, request.method
        if method not in SAFE_METHODS | CHANGING_METHODS:
            return 405, "method_not_allowed", "That method is not supported."
        if not path.startswith("/api/") or path in OPEN_PATHS:
            return (405, "method_not_allowed", "That method is not supported.") if method not in SAFE_METHODS else None
        if not hmac.compare_digest(request.cookies.get(COOKIE, ""), self.session):
            return 401, "not_authenticated", "Open the app's page in this browser first, then try again."
        if method in SAFE_METHODS:
            return None
        if not hmac.compare_digest(request.headers.get(TOKEN_HEADER, ""), self.token):
            return 403, "bad_action_token", "The action token is missing or out of date. Reload the page."
        length = request.headers.get("content-length")
        if length is None and method != "DELETE":
            return 411, "length_required", "The request must say how long its body is."
        kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
        # DECISIONS 352: one Maya export file, sent as it is (citation-mentions can be 400 MB), to its own path only;
        # the cookie and the action token above are still required, which no cross-site form can send.
        upload = method == "PUT" and MAYA_UPLOAD.match(path) is not None and kind == "application/octet-stream"
        limit = MAX_UPLOAD_BYTES if upload else MAX_BODY_BYTES
        # isascii: str.isdigit() also accepts "²", which int() then refuses with a 500 (D-19).
        if length is not None and (not (length.isascii() and length.isdigit()) or int(length) > limit):
            return 413, "request_too_large", "The request is too large."
        if method != "DELETE" and kind != "application/json" and not upload:
            return 415, "json_required", "Actions must be sent as JSON."
        return None

    def set_cookie(self, response: Response) -> None:
        response.set_cookie(COOKIE, self.session, httponly=True, samesite="strict", path="/")

    async def middleware(self, request: Request, call_next) -> Response:
        refused = self.refusal(request)
        if refused is not None:
            status, code, message = refused
            response: Response = JSONResponse(error_body(code, message), status_code=status)
        else:
            response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
