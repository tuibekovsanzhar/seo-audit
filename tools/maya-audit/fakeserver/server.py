"""A tiny HTTP server that plays one scripted website on 127.0.0.1.

The server keeps its own request log, independent of the crawler's, so tests
can check crawler behavior from the site's side (what actually arrived).
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Union


@dataclass
class Response:
    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "text/html; charset=utf-8"
    delay_s: float = 0.0
    drop_connection: bool = False


@dataclass
class RequestSeen:
    seq: int
    path: str
    user_agent: str
    at: float
    cookie: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "GET"
    body: bytes = b""

    @property
    def route_path(self) -> str:
        return self.path.split("?", 1)[0]

    @property
    def query(self) -> dict[str, str]:
        from urllib.parse import parse_qsl

        return dict(parse_qsl(self.path.split("?", 1)[1])) if "?" in self.path else {}


Route = Union[Response, Callable[["Site", RequestSeen], Response]]


@dataclass
class Site:
    routes: dict[str, Route]
    fallback: Route = field(default_factory=lambda: Response(404, "<html><title>Not found</title></html>"))
    state: dict = field(default_factory=dict)
    # Runs before routing, e.g. a fake WAF that answers some user agents itself.
    intercept: Callable[["Site", RequestSeen], "Response | None"] | None = None

    def resolve(self, request: RequestSeen) -> Response:
        if self.intercept is not None:
            answer = self.intercept(self, request)
            if answer is not None:
                return answer
        route = self.routes.get(request.path, self.routes.get(request.route_path, self.fallback))
        return route(self, request) if callable(route) else route


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:  # quiet: timeouts/drops are intentional
        pass


class FakeServer:
    def __init__(self, site: Site, tls: tuple[str, str] | None = None, host: str = "127.0.0.1") -> None:
        """`tls` = (certfile, keyfile) serves HTTPS; use host="localhost" so the name matches test certificates."""
        self.site = site
        self.tls = tls
        self.host = host
        self.requests: list[RequestSeen] = []
        self._lock = threading.Lock()
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "FakeServer":
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with server._lock:
                    seen = RequestSeen(
                        len(server.requests) + 1, self.path, self.headers.get("User-Agent", ""), time.time(),
                        self.headers.get("Cookie"),
                        {k.lower(): v for k, v in self.headers.items()},
                        self.command, body,
                    )
                    server.requests.append(seen)
                response = server.site.resolve(seen)
                if response.delay_s:
                    time.sleep(response.delay_s)
                if response.drop_connection:
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
                # A body given as bytes is sent as it is (a page in another encoding than UTF-8).
                body = (response.body if isinstance(response.body, bytes)
                        else response.body.replace("{base}", server.base_url).encode("utf-8"))
                try:
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.content_type)
                    self.send_header("Content-Length", str(len(body)))
                    for key, value in response.headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self._httpd = _Server(("127.0.0.1", 0), Handler)
        port = self._httpd.server_address[1]
        if self.tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*self.tls)
            self._httpd.socket = context.wrap_socket(self._httpd.socket, server_side=True)
        scheme = "https" if self.tls else "http"
        self.port = port
        self.base_url = f"{scheme}://{self.host}:{port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._httpd is not None
        self._httpd.shutdown()
        self._httpd.server_close()

    def paths(self) -> list[str]:
        return [r.path for r in self.requests]
