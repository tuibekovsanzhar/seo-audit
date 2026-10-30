"""Connect to the exact address validated, preserving HTTP Host and TLS identity."""
from __future__ import annotations

import threading
import httpx

from .urls import public_addresses


class BeforeConnectDeadline(httpx.TimeoutException):
    """The deadline/stop happened during DNS; no connection was attempted."""


class PublicTransport(httpx.BaseTransport):
    def __init__(self, *, allow_loopback=True, verify=True, before_connect=None):
        self.allow_loopback = allow_loopback
        self.verify = verify
        self.before_connect = before_connect
        self._transports = {}
        self._lock = threading.Lock()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        addresses = public_addresses(str(request.url), allow_loopback=self.allow_loopback)
        if self.before_connect is not None:
            try:
                remaining = self.before_connect()
            except httpx.TimeoutException as exc:
                raise BeforeConnectDeadline("overall audit deadline reached before connection") from exc
            request.extensions["timeout"] = {k: min(v, remaining) if v is not None else remaining
                                              for k, v in request.extensions.get("timeout", {}).items()}
        # Separate pools by original origin so two names on one IP cannot share a TLS identity.
        origin = (request.url.scheme, request.url.host, request.url.port)
        with self._lock:
            if origin not in self._transports:
                self._transports[origin] = httpx.HTTPTransport(verify=self.verify, trust_env=False, retries=0)
            transport = self._transports[origin]
        # Every address was validated above, so falling back to the next one stays inside the same
        # safety check. Without the fallback a host that answers on IPv4 only, but also resolves to
        # an unreachable IPv6 address listed first, could not be fetched at all.
        last: httpx.TransportError | None = None
        for address in addresses:
            pinned = httpx.Request(request.method, request.url.copy_with(host=address),
                                   headers=request.headers, stream=request.stream,
                                   extensions={**request.extensions, 'sni_hostname': request.url.host})
            try:
                return transport.handle_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc
        raise last

    def close(self):
        for transport in self._transports.values():
            transport.close()
