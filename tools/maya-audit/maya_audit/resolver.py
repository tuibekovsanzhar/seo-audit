"""Looking up a host's addresses without letting this computer's resolver decide what is true about a website.

The system resolver is asked first. If it gives no answer it is asked once more after a pause, and then the name is
looked up through DNS over HTTPS: Cloudflare, then Google, each reached by its published IP address so that the
fallback does not itself need a working resolver. Which method answered is recorded.

Three outcomes are kept apart, because they mean different things:

- addresses: the caller checks them (private and reserved addresses stay refused) and connects to exactly those;
- `HostNotFoundError`: a public resolver answered that the name has no address;
- `LocalDnsError`: nothing could be looked up from this computer. That is a statement about this computer's network,
  never about the website.

The shape follows OpenSEO's url-policy (MIT, licenses/OPENSEO-MIT-LICENSE.txt): a JSON DNS-over-HTTPS query for A and
AAAA with a short timeout, where a lookup that returns nothing is not treated as an unsafe destination. No code was
copied. The system-resolver-first order, the retry and the second provider are Maya's own.
"""
from __future__ import annotations

import os
import queue
import socket
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from . import clock as _clock

SYSTEM_TIMEOUT_S = 4.0        # macOS's own resolver gives up after about 30 seconds; an audit does not wait that long
SYSTEM_ATTEMPTS = 2
BACKOFF_S = 0.75              # the pause before the system resolver is asked again
DOH_TIMEOUT_S = 2.5
# (name, TLS host, path, published addresses). Reached by address: the fallback must work when the resolver does not.
DOH_PROVIDERS = (("cloudflare", "cloudflare-dns.com", "/dns-query", ("1.1.1.1", "1.0.0.1")),
                 ("google", "dns.google", "/resolve", ("8.8.8.8", "8.8.4.4")))
DOH_VAR = "MAYA_AUDIT_DNS_OVER_HTTPS"   # "off": never send a host name to a public resolver
CACHE_S = 60.0                # an answer is reused this long, so one audit does not look the same name up for every request
FAILURE_CACHE_S = 15.0
SYSTEM_DOWN_S = 60.0          # after the system resolver failed, it is skipped this long and the fallback is asked first
PUBLIC_CHECK_HOST = "example.com"  # the pre-flight's "can this computer look up anything" name (IANA's reserved example)
# Names that are never public: they are not sent to a public resolver.
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test", ".example", ".invalid", ".onion")
_A, _AAAA = 1, 28

# Replaced in tests. `system_lookup(host, port)` returns addresses or raises OSError; `doh_transport` answers the
# DNS-over-HTTPS requests; `sleep` is the pause between attempts.
system_lookup: Callable[[str, int], list[str]] | None = None
doh_transport: httpx.BaseTransport | None = None
sleep: Callable[[float], None] = _clock.sleep


class LookupFailed(OSError):
    """No address was found. `kind` is "local" (nothing could be looked up from this computer), "not_found" (a
    resolver answered that the name has no address) or "unresolved" (the system resolver failed and the name is not
    one that may be sent to a public resolver)."""

    def __init__(self, kind: str, host: str, detail: str, attempts: list[dict[str, Any]]):
        super().__init__(detail)
        self.kind, self.host, self.detail, self.attempts = kind, host, detail, attempts


@dataclass
class Lookup:
    host: str
    addresses: list[str]
    method: str                      # "system" | "doh:cloudflare" | "doh:google"
    attempts: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    at: str = ""


_lock = threading.Lock()
_cache: dict[str, tuple[float, Lookup | LookupFailed]] = {}
_system_down_until = 0.0
LOG: deque[dict[str, Any]] = deque(maxlen=500)


def reset() -> None:
    """Forget cached answers and the record (tests, and the start of an audit)."""
    global _system_down_until
    with _lock:
        _cache.clear()
        LOG.clear()
        _system_down_until = 0.0


def never_public(host: str) -> bool:
    """A single-label or reserved name: it is never sent to a public resolver."""
    return "." not in host or host.endswith(_PRIVATE_SUFFIXES) or host == "localhost"


def doh_allowed(host: str) -> bool:
    if os.environ.get(DOH_VAR, "").strip().lower() in ("off", "0", "false", "no"):
        return False
    return not never_public(host)


def _getaddrinfo(host: str, port: int) -> list[str]:
    return [item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _ask_system(host: str, port: int) -> tuple[list[str] | None, str | None, str | None]:
    """(addresses, failure kind, detail). The lookup runs in its own thread, because the system call cannot be given
    a time limit; a lookup that does not return is left behind and counted as a timeout."""
    lookup = system_lookup or _getaddrinfo
    answer: queue.Queue = queue.Queue(maxsize=1)

    def work() -> None:
        try:
            answer.put((lookup(host, port), None))
        except Exception as exc:  # noqa: BLE001 - whatever the resolver raised is the finding
            answer.put((None, exc))

    threading.Thread(target=work, name="maya-dns", daemon=True).start()
    try:
        addresses, error = answer.get(timeout=SYSTEM_TIMEOUT_S)
    except queue.Empty:
        return None, "timeout", f"the system resolver gave no answer in {SYSTEM_TIMEOUT_S:g} s"
    if error is None:
        return (addresses, None, None) if addresses else (None, "not_found", "the system resolver returned no address")
    code = getattr(error, "errno", None)
    not_found = isinstance(error, socket.gaierror) and code in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5))
    return None, ("not_found" if not_found else "resolver_error"), f"{type(error).__name__}: {error}"


def _doh_once(name: str, tls_host: str, path: str, address: str, host: str, record: str) -> tuple[int, list[str]]:
    """(DNS status, addresses) from one DNS-over-HTTPS JSON query. Raises httpx.HTTPError or ValueError."""
    with httpx.Client(transport=doh_transport, timeout=DOH_TIMEOUT_S, trust_env=False) as client:
        response = client.get(f"https://{address}{path}", params={"name": host, "type": record},
                              headers={"Host": tls_host, "Accept": "application/dns-json"},
                              extensions={"sni_hostname": tls_host})
    if response.status_code != 200:
        raise ValueError(f"{name} answered HTTP {response.status_code}")
    body = response.json()
    wanted = _A if record == "A" else _AAAA
    return int(body.get("Status", 2)), [str(row["data"]) for row in body.get("Answer") or []
                                         if row.get("type") == wanted and row.get("data")]


def _ask_doh(host: str, attempts: list[dict[str, Any]]) -> tuple[list[str] | None, str | None, bool]:
    """(addresses, provider that answered, whether a provider answered that the name does not exist)."""
    for name, tls_host, path, addresses in DOH_PROVIDERS:
        for address in addresses:
            began = _clock.monotonic()
            try:
                status, found = _doh_once(name, tls_host, path, address, host, "A")
            except Exception as exc:  # noqa: BLE001 - unreachable, refused, not JSON: try the next address or provider
                attempts.append({"method": f"doh:{name}", "via": address, "outcome": "unreachable",
                                 "detail": f"{type(exc).__name__}: {exc}"[:200], "ms": round((_clock.monotonic() - began) * 1000, 1)})
                continue
            try:
                _status6, six = _doh_once(name, tls_host, path, address, host, "AAAA")
            except Exception:  # noqa: BLE001 - the IPv4 answer stands on its own
                six = []
            found = [*found, *six]
            outcome = "answered" if found else "no_such_name" if status == 3 else "no_address"
            attempts.append({"method": f"doh:{name}", "via": address, "outcome": outcome, "dns_status": status,
                             "addresses": len(found), "ms": round((_clock.monotonic() - began) * 1000, 1)})
            if found:
                return found, name, False
            if status in (0, 3):
                return None, name, True   # a resolver answered: the name has no address
            break                          # a resolver error (SERVFAIL): ask the other provider
    return None, None, False


def resolve(host: str, port: int = 443) -> Lookup:
    """Addresses for a host name, with how they were found. Raises LookupFailed."""
    global _system_down_until
    host = host.rstrip(".").lower()
    now = _clock.monotonic()
    with _lock:
        held = _cache.get(host)
        skip_system = now < _system_down_until
    if held and held[0] > now:
        if isinstance(held[1], LookupFailed):
            raise held[1]
        return held[1]
    began = _clock.monotonic()
    attempts: list[dict[str, Any]] = []
    fallback = doh_allowed(host)
    result: Lookup | LookupFailed | None = None
    system_kind = None
    if not (skip_system and fallback):
        for attempt in range(SYSTEM_ATTEMPTS):
            started = _clock.monotonic()
            addresses, system_kind, detail = _ask_system(host, port)
            attempts.append({"method": "system", "outcome": "answered" if addresses else system_kind, "detail": detail,
                             "ms": round((_clock.monotonic() - started) * 1000, 1)})
            if addresses:
                result = Lookup(host, list(dict.fromkeys(addresses)), "system")
                break
            if system_kind == "not_found" or attempt + 1 == SYSTEM_ATTEMPTS:
                break  # "no such name" may be true, or this computer may be offline: a public resolver decides
            sleep(BACKOFF_S * (attempt + 1))
    else:
        attempts.append({"method": "system", "outcome": "skipped", "detail": "it failed less than a minute ago"})
    if result is None and fallback:
        found, provider, said_no = _ask_doh(host, attempts)
        if found:
            result = Lookup(host, list(dict.fromkeys(found)), f"doh:{provider}")
            if system_kind in ("timeout", "resolver_error"):
                with _lock:
                    _system_down_until = _clock.monotonic() + SYSTEM_DOWN_S
        elif said_no:
            result = LookupFailed("not_found", host, f"{host} has no address (answered by the {provider} public resolver)", attempts)
        else:
            result = LookupFailed("local", host, f"DNS lookup failed on this computer for {host}: the system resolver "
                                  f"{_said(attempts)}, and neither public resolver could be reached", attempts)
    elif result is None:
        result = LookupFailed("unresolved", host, f"{host} could not be looked up: the system resolver {_said(attempts)}", attempts)
    elapsed = round((_clock.monotonic() - began) * 1000, 1)
    at = datetime.now(timezone.utc).isoformat()
    if isinstance(result, Lookup):
        result.attempts, result.elapsed_ms, result.at = attempts, elapsed, at
    with _lock:
        _cache[host] = (_clock.monotonic() + (CACHE_S if isinstance(result, Lookup) else FAILURE_CACHE_S), result)
        LOG.append({"host": host, "at": at, "ms": elapsed,
                    "answered_by": result.method if isinstance(result, Lookup) else None,
                    "failure": None if isinstance(result, Lookup) else result.kind, "attempts": attempts})
    if isinstance(result, LookupFailed):
        raise result
    return result


def _said(attempts: list[dict[str, Any]]) -> str:
    system = [a for a in attempts if a["method"] == "system" and a["outcome"] != "skipped"]
    if not system:
        return "had failed less than a minute earlier"
    last = system[-1]
    words = {"timeout": "gave no answer", "not_found": "found no such name", "resolver_error": "returned an error"}
    return f"{words.get(last['outcome'], 'failed')} ({len(system)} attempt(s))"


def record() -> list[dict[str, Any]]:
    """Every lookup made since the last reset, oldest first: which method answered, and each attempt."""
    with _lock:
        return [dict(row) for row in LOG]


def summary() -> dict[str, Any]:
    """For the report: per host, the method that answered last and how often each method was needed."""
    hosts: dict[str, dict[str, Any]] = {}
    for row in record():
        entry = hosts.setdefault(row["host"], {"host": row["host"], "lookups": 0, "answered_by": None, "failures": 0,
                                               "system_resolver_failed": False})
        entry["lookups"] += 1
        entry["answered_by"] = row["answered_by"] or entry["answered_by"]
        entry["failures"] += 1 if row["failure"] else 0
        if any(a["method"] == "system" and a["outcome"] in ("timeout", "resolver_error", "not_found") for a in row["attempts"]):
            entry["system_resolver_failed"] = True
            entry["system_resolver_said"] = next(a["outcome"] for a in row["attempts"] if a["method"] == "system" and a["outcome"] != "answered")
    return {"hosts": list(hosts.values())}


def preflight(host: str, port: int = 443) -> dict[str, Any]:
    """Before anything is spent: can this computer look up the target, and failing that, anything at all?

    `status`: "ok"; "host_not_found" (the name has no address: a spelling mistake, most often); "local_network_problem"
    (neither the target nor a well-known public name could be looked up); "target_unresolved" (the public name was
    found and the target was not, without a resolver saying the target does not exist)."""
    try:
        found = resolve(host, port)
        return {"status": "ok", "host": host, "answered_by": found.method, "addresses": found.addresses}
    except LookupFailed as failed:
        target = failed
    if target.kind == "not_found":
        return {"status": "host_not_found", "host": host, "detail": target.detail}
    try:
        other = resolve(PUBLIC_CHECK_HOST, 443)
        return {"status": "target_unresolved", "host": host, "detail": target.detail, "public_host_answered_by": other.method}
    except LookupFailed as nothing:
        return {"status": "local_network_problem", "host": host, "detail": target.detail, "public_host": nothing.detail}
