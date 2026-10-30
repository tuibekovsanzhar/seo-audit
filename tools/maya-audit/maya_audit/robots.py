"""robots.txt parsing and matching per RFC 9309.

Written in-house rather than using urllib.robotparser (first-match semantics,
not RFC 9309's longest match) because every decision must carry evidence: the
group that matched and the exact rule line that decided it (spec §1, ACC-2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote

from .urls import request_target


@dataclass(frozen=True)
class Rule:
    directive: str  # "allow" | "disallow"
    pattern: str
    line: int


@dataclass
class Group:
    agents: list[tuple[str, int]] = field(default_factory=list)  # (token, line)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: tuple[float, int] | None = None


@dataclass
class RobotsTxt:
    groups: list[Group]
    sitemaps: list[tuple[str, int]]
    invalid_lines: list[int]
    # Rules (Allow, Disallow, Crawl-delay) written before any User-agent line: (line number, the line as written).
    # RFC 9309 ties a rule to the group above it, so these belong to no group and no crawler applies them (ACC-1).
    ungrouped: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str
    group_kind: str  # "specific" | "*" | "none" | "unavailable" | "implicit"
    group_lines: tuple[int, ...] = ()
    rule: Rule | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "group_kind": self.group_kind,
            "group_lines": list(self.group_lines),
            "rule": (
                {"directive": self.rule.directive, "pattern": self.rule.pattern, "line": self.rule.line}
                if self.rule
                else None
            ),
        }


def parse_robots(text: str) -> RobotsTxt:
    groups: list[Group] = []
    sitemaps: list[tuple[str, int]] = []
    invalid: list[int] = []
    ungrouped: list[tuple[int, str]] = []
    current: Group | None = None
    in_agent_run = False

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            invalid.append(number)
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()

        if key == "user-agent":
            # Consecutive user-agent lines share one group; a user-agent line
            # after any rule starts a new group.
            if current is None or not in_agent_run:
                current = Group()
                groups.append(current)
            current.agents.append((value.split("/", 1)[0].strip().lower(), number))
            in_agent_run = True
        elif key in ("allow", "disallow"):
            in_agent_run = False
            if current is None:
                invalid.append(number)
                ungrouped.append((number, raw.strip()[:200]))
                continue
            if value == "":  # empty pattern matches nothing
                continue
            current.rules.append(Rule(key, value, number))
        elif key == "crawl-delay":
            in_agent_run = False
            if current is None:
                ungrouped.append((number, raw.strip()[:200]))
                continue
            try:
                current.crawl_delay = (float(value), number)
            except ValueError:
                invalid.append(number)
        elif key == "sitemap":
            sitemaps.append((value, number))
        # Unknown keys are ignored and do not end an agent run.

    return RobotsTxt(groups=groups, sitemaps=sitemaps, invalid_lines=invalid, ungrouped=ungrouped)


_PCT = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalize_octets(value: str) -> str:
    """Percent-encode non-ASCII, uppercase escapes, decode unreserved escapes."""
    value = quote(value, safe="/?:@!$&'()*+,;=[]%~-._#")

    def fix(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

    return _PCT.sub(fix, value)


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = _normalize_octets(pattern[:-1] if anchored else pattern)
    regex = ".*".join(re.escape(piece) for piece in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def _matches(pattern: str, target: str) -> bool:
    return _compile(pattern).match(target) is not None


def select_groups(robots: RobotsTxt, product_token: str) -> tuple[list[Group], str]:
    """RFC 9309: obey only the groups matching the product token, else `*`."""
    token = product_token.lower()
    specific = [g for g in robots.groups if any(a == token for a, _ in g.agents)]
    if specific:
        return specific, "specific"
    star = [g for g in robots.groups if any(a == "*" for a, _ in g.agents)]
    return (star, "*") if star else ([], "none")


def decide(robots: RobotsTxt, product_token: str, url: str) -> RobotsDecision:
    target = _normalize_octets(request_target(url))
    if target == "/robots.txt":
        return RobotsDecision(True, "/robots.txt is always allowed", "implicit")

    groups, kind = select_groups(robots, product_token)
    group_lines = tuple(line for g in groups for _, line in g.agents)
    best: Rule | None = None
    for group in groups:
        for rule in group.rules:
            if not _matches(rule.pattern, target):
                continue
            longer = best is None or len(rule.pattern) > len(best.pattern)
            tie_allow = (
                best is not None
                and len(rule.pattern) == len(best.pattern)
                and rule.directive == "allow"
            )
            if longer or tie_allow:
                best = rule

    if kind == "none":
        return RobotsDecision(True, "no group matches this user agent and there is no * group", kind)
    if best is None:
        return RobotsDecision(True, "no rule in the matched group matches this path", kind, group_lines)
    allowed = best.directive == "allow"
    verb = "allowed" if allowed else "disallowed"
    reason = f"{verb} by line {best.line}: {best.directive.capitalize()}: {best.pattern}"
    return RobotsDecision(allowed, reason, kind, group_lines, best)


def crawl_delay(robots: RobotsTxt, product_token: str) -> tuple[float, int] | None:
    groups, _ = select_groups(robots, product_token)
    delays = [g.crawl_delay for g in groups if g.crawl_delay]
    return max(delays, key=lambda d: d[0]) if delays else None


@dataclass
class RobotsPolicy:
    """The fetched robots.txt plus how RFC 9309 says to treat the result."""

    url: str
    # "parsed" | "allow_all" | "disallow_all" | "not_checked". "not_checked": no answer from the site reached this
    # computer, so nothing is known about its rules. Maya then makes no further direct request, as with disallow_all,
    # but it is not RFC 9309's "assume complete disallow": that is kept for a robots.txt the site answered with 5xx.
    mode: str
    reason: str
    status: int | None
    error: str | None
    bytes_read: int
    truncated: bool
    redirect_hops: list[str]
    robots: RobotsTxt | None
    content_type: str | None = None
    looks_like_html: bool = False
    fetched_at: str | None = None
    # sha256 of the robots.txt body, so a resumed crawl can notice the policy changed under it.
    fingerprint: str | None = None
    # Why a "not_checked" policy was not checked: "local_network" (this computer could not look the host up),
    # "host_not_found", "refused_address" (a private or reserved address) or "no_answer" (a timeout or a failed
    # connection, where the site and the connection cannot be told apart).
    cause: str | None = None

    @property
    def stops_requests(self) -> bool:
        """Maya's own crawler asks this origin for nothing more."""
        return self.mode in ("disallow_all", "not_checked")

    def decide(self, product_token: str, url: str) -> RobotsDecision:
        if request_target(url) == "/robots.txt":
            return RobotsDecision(True, "/robots.txt is always allowed", "implicit")
        if self.mode == "allow_all":
            return RobotsDecision(True, self.reason, "unavailable")
        if self.stops_requests:
            return RobotsDecision(False, self.reason, "unavailable")
        assert self.robots is not None
        return decide(self.robots, product_token, url)


LOCAL_NETWORK_MESSAGE = ("Network problem on this computer (DNS lookup failed). Check VPN / iCloud Private Relay / Wi-Fi "
                         "and try again.")
NOT_CHECKED_REASONS = {
    "local_network": "robots.txt was not checked: network problem on this computer ({error}). This says nothing about "
                     "the site; Maya's own crawler requested no page",
    "host_not_found": "robots.txt was not checked: the address does not exist ({error}); no page was requested",
    "refused_address": "robots.txt was not requested: the address is not a public one ({error}); no page was requested",
    "no_answer": "robots.txt was not checked: no answer reached this computer ({error}). Whether the site or the "
                 "connection failed is not known; Maya's own crawler requested no page",
}


def failure_cause(error: str | None) -> str:
    """Which kind of "no answer" a fetch error is. Only a 5xx the site sent is the site's failure; none of these is."""
    kind = (error or "").split(" ", 1)[0]
    return {"local_dns_failure": "local_network", "unresolved_host": "local_network", "host_not_found": "host_not_found",
            "unsafe_target": "refused_address"}.get(kind, "no_answer")


def is_local_failure(error: str | None) -> bool:
    return bool(error) and failure_cause(error) == "local_network"


def looks_like_html(body: bytes, content_type: str | None) -> bool:
    if content_type and content_type.split(";", 1)[0].strip().lower() in ("text/html", "application/xhtml+xml"):
        return True
    head = body[:512].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html"))


def policy_from_response(
    url: str,
    status: int | None,
    error: str | None,
    body: bytes,
    max_bytes: int,
    redirect_hops: list[str],
) -> RobotsPolicy:
    """Map a robots.txt fetch result to RFC 9309 §2.3.1 behavior.

    2xx: parse. 4xx: unavailable, crawl allowed. 5xx: assume complete disallow. 429 temporarily stops requests:
    back off and retry later (a Maya politeness choice, not an RFC rule that the site disallows crawling).

    No answer at all (a failed DNS lookup on this computer, a timeout, a refused connection) is "not_checked": the
    site said nothing, so no rule of the site's is assumed and nothing is reported against the site. Maya still
    makes no further direct request to an origin whose rules it could not read (Owner, 2026-10-09).
    """
    truncated = len(body) > max_bytes
    common = dict(
        url=url,
        status=status,
        error=error,
        bytes_read=min(len(body), max_bytes),
        truncated=truncated,
        redirect_hops=redirect_hops,
    )
    if error is not None or status is None:
        cause = failure_cause(error)
        return RobotsPolicy(mode="not_checked", reason=NOT_CHECKED_REASONS[cause].format(error=error), robots=None,
                            cause=cause, **common)
    if 200 <= status < 300:
        # utf-8-sig: a byte-order mark would otherwise glue onto the first "User-agent" and drop the whole group.
        text = body[:max_bytes].decode("utf-8-sig", errors="replace")
        return RobotsPolicy(mode="parsed", reason="robots.txt parsed", robots=parse_robots(text), **common)
    if status == 429:
        return RobotsPolicy(
            mode="disallow_all",
            reason="robots.txt returned 429; rate limited: back off and retry later; no page requests in this run",
            robots=None,
            **common,
        )
    if status >= 500:
        return RobotsPolicy(
            mode="disallow_all",
            reason=f"robots.txt returned {status}; RFC 9309: assume complete disallow",
            robots=None,
            **common,
        )
    if 400 <= status < 500:
        return RobotsPolicy(
            mode="allow_all",
            reason=f"robots.txt returned {status}; RFC 9309: unavailable, crawling allowed",
            robots=None,
            **common,
        )
    if 300 <= status < 400:
        # Still a redirect after the hops Maya follows, or one with no usable Location (A5). RFC 9309 §2.3.1.2: a crawler
        # follows at least five redirects and may then treat robots.txt as unavailable, which allows crawling.
        return RobotsPolicy(
            mode="allow_all",
            reason=(f"robots.txt still answered {status} after {len(redirect_hops)} redirect(s) (limit {5}, or no usable "
                    "Location); RFC 9309 §2.3.1.2: unavailable, crawling allowed"),
            robots=None,
            **common,
        )
    return RobotsPolicy(
        mode="disallow_all",
        reason=f"robots.txt returned unexpected status {status} after redirects; treated as unreachable",
        robots=None,
        **common,
    )
