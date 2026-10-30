"""ACC-5 (T3): read server/CDN access logs and verify bot IPs against vendor ranges.

Nothing here touches the network. IP ranges must be supplied as local files
(e.g. downloaded copies of https://openai.com/searchbot.json).

Supported log formats, and exactly what was checked:
- "combined": the nginx predefined `combined` log_format (checked against
  nginx.org docs, 2026-09-14). Apache's "combined" uses the same layout but was
  not re-checked.
- "cloudflare_logpush": Cloudflare Logpush `http_requests` records, one JSON
  object per line. The five field names in CLOUDFLARE_FIELDS were checked against
  Cloudflare's field reference (2026-09-14), as were the three timestamp formats
  (unixnano default, unix, rfc3339). The one-object-per-line record layout was NOT
  confirmed on the pages checked. Other CDNs' JSON logs are not supported.

IP range files: JSON {"prefixes": [{"ipv4Prefix": ...} | {"ipv6Prefix": ...} | "cidr"]}
or plain text with one CIDR per line. The JSON layout follows Google's and
OpenAI's published files; other vendors' layouts were not checked.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections import Counter
from datetime import datetime, timezone

from .registry import REGISTRY

COMBINED = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) \S+ "[^"]*" "(?P<ua>[^"]*)"'
)
CLOUDFLARE_FIELDS = {
    "ip": "ClientIP",
    "time": "EdgeStartTimestamp",
    "path": "ClientRequestURI",
    "status": "EdgeResponseStatus",
    "ua": "ClientRequestUserAgent",
}
LOG_FORMATS = ("combined", "cloudflare_logpush")
_TOKENS_LONGEST_FIRST = sorted(REGISTRY, key=lambda e: -len(e.token))


def load_ip_ranges(path: str, malformed: list[str] | None = None) -> list[ipaddress._BaseNetwork]:
    """The networks a range file lists. An entry that is not a network is skipped and, when `malformed` is given,
    added to it (D-15): one bad line must not end the log analysis, and must not be read as "no address matches"."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    items: list = []
    try:
        data = json.loads(text)
        for prefix in (data.get("prefixes") or [] if isinstance(data, dict) else data if isinstance(data, list) else []):
            if isinstance(prefix, str):
                items.append(prefix)
            elif isinstance(prefix, dict):
                items.extend(v for k, v in prefix.items() if k in ("ipv4Prefix", "ipv6Prefix"))
    except json.JSONDecodeError:
        items = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    networks = []
    for item in items:
        try:
            networks.append(ipaddress.ip_network(str(item).strip(), strict=False))
        except ValueError:
            if malformed is not None:
                malformed.append(str(item)[:80])
    return networks


def _parse_time(value: str | int | float) -> datetime | None:
    if isinstance(value, (int, float)):
        # Cloudflare timestamp_format: unixnano (default, ~1.7e18) or unix seconds (~1.7e9).
        seconds = value / 1e9 if value > 1e15 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    for fmt in ("%d/%b/%Y:%H:%M:%S %z",):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_log_lines(lines, fmt: str) -> tuple[list[dict], int]:
    if fmt not in LOG_FORMATS:
        raise ValueError(f"unsupported log format {fmt!r}; supported: {LOG_FORMATS}")
    entries, unparsed = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if fmt == "combined":
            match = COMBINED.match(line)
            if not match:
                unparsed += 1
                continue
            raw = match.groupdict()
        else:
            try:
                record = json.loads(line)
                raw = {key: record.get(field) for key, field in CLOUDFLARE_FIELDS.items()}
            except json.JSONDecodeError:
                unparsed += 1
                continue
        when = _parse_time(raw["time"]) if raw.get("time") is not None else None
        try:
            status = int(raw["status"])
            ip = ipaddress.ip_address(str(raw["ip"]))
        except (TypeError, ValueError):
            unparsed += 1
            continue
        entries.append({"ip": ip, "time": when, "path": raw.get("path") or "/", "status": status, "ua": raw.get("ua") or ""})
    return entries, unparsed


def match_token(user_agent: str) -> str | None:
    lowered = user_agent.lower()
    for entry in _TOKENS_LONGEST_FIRST:
        if entry.token.lower() in lowered:
            return entry.token
    return None


def analyze_logs(paths: tuple[str, ...], fmt: str, range_files: tuple[tuple[str, str], ...]) -> dict:
    malformed: dict[str, list[str]] = {}
    ranges = {token: load_ip_ranges(path, malformed.setdefault(token, [])) for token, path in range_files}
    # A range file that yields no network (empty, another layout, every entry malformed) verifies nothing: requests are
    # then "unverifiable", never "spoofed" (D-15). A token with no usable range is treated as if no file were given.
    ranges = {token: networks for token, networks in ranges.items() if networks}
    entries, unparsed = [], 0
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            parsed, bad = parse_log_lines(fh, fmt)
        entries.extend(parsed)
        unparsed += bad

    times = [e["time"] for e in entries if e["time"]]
    bots: dict[str, dict] = {}
    for e in entries:
        token = match_token(e["ua"])
        if token is None:
            continue
        stats = bots.setdefault(token, {
            "token": token, "requests": 0, "verified": 0, "spoofed": 0, "unverifiable": 0,
            "verified_status": Counter(), "verified_paths": set(), "last_seen_verified": None,
            "ip_ranges_loaded": token in ranges, "spoofed_ip_sample": [],
        })
        stats["requests"] += 1
        if token not in ranges:
            stats["unverifiable"] += 1
            continue
        if any(e["ip"] in net for net in ranges[token]):
            stats["verified"] += 1
            stats["verified_status"][e["status"]] += 1
            stats["verified_paths"].add(e["path"])
            if e["time"] and (stats["last_seen_verified"] is None or e["time"] > stats["last_seen_verified"]):
                stats["last_seen_verified"] = e["time"]
        else:
            stats["spoofed"] += 1
            if len(stats["spoofed_ip_sample"]) < 5:
                stats["spoofed_ip_sample"].append(str(e["ip"]))

    for stats in bots.values():
        stats["verified_status"] = dict(sorted(stats["verified_status"].items()))
        stats["last_seen_verified"] = stats["last_seen_verified"].isoformat() if stats["last_seen_verified"] else None

    return {
        "files": list(paths),
        "format": fmt,
        "entries_parsed": len(entries),
        "lines_unparsed": unparsed,
        "window": {
            "start": min(times).isoformat() if times else None,
            "end": max(times).isoformat() if times else None,
        },
        "ip_range_files": [{"token": t, "path": p, "prefixes": len(ranges.get(t, [])),
                            "malformed_entries": len(malformed.get(t, [])), "malformed_sample": malformed.get(t, [])[:5],
                            **({} if ranges.get(t) else {"unusable": "no network could be read from this file; the bot's "
                                                                     "requests are counted as unverifiable"})}
                           for t, p in range_files],
        "bots": bots,
    }
