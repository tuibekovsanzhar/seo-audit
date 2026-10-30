"""INT-1 fetch classification.

Confidence rules (spec INT-1): classifications from an explicit header or the
HTTP status are Verified; classifications resting only on a body signature are
Estimated.

The signature list is a starting set. It has not been validated against
current vendor challenge pages; treat additions and removals as policy changes.

The 202 rule, the SiteGround marker and the three Cloudflare body markers follow OpenSEO's classify-fetch (MIT,
licenses/OPENSEO-MIT-LICENSE.txt); the list was re-expressed in Maya's own signature table, no code was copied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Classification, Confidence, FetchClass


@dataclass(frozen=True)
class Signature:
    name: str
    pattern: re.Pattern[str]
    # "page": the marker means the whole page is a challenge (e.g. its title).
    # "script": the marker can also appear injected into normal pages, so it
    # only counts alongside a denial status. Cloudflare's JavaScript detections,
    # for example, inject /cdn-cgi/challenge-platform/ scripts into 200 pages.
    strength: str


SIGNATURES = (
    Signature("cloudflare_just_a_moment_title", re.compile(r"<title>\s*Just a moment\.\.\.\s*</title>", re.I), "page"),
    Signature("cloudflare_attention_required_title", re.compile(r"<title>[^<]*Attention Required![^<]*Cloudflare", re.I), "page"),
    Signature("vercel_security_checkpoint", re.compile(r"Vercel Security Checkpoint", re.I), "page"),
    Signature("datadome_captcha", re.compile(r"captcha-delivery\.com", re.I), "page"),
    Signature("perimeterx_captcha", re.compile(r"px-captcha", re.I), "page"),
    # SiteGround's captcha redirect arrives as a 200 or a 202 whose page points at this path.
    Signature("siteground_sgcaptcha", re.compile(r"/\.well-known/sgcaptcha/", re.I), "page"),
    Signature("cloudflare_challenge_platform_script", re.compile(r"/cdn-cgi/challenge-platform/|challenge-platform", re.I), "script"),
    # Cloudflare's older interstitial and its "verifying you are human" page. Beside a denial status or a 503 only:
    # the words can appear in an article about Cloudflare.
    Signature("cloudflare_browser_verification", re.compile(r"cf-browser-verification", re.I), "script"),
    Signature("cloudflare_verifying_human", re.compile(r"verifying you are human", re.I), "script"),
    Signature("cloudflare_just_a_moment_text", re.compile(r"just a moment\.\.\.", re.I), "script"),
    # Akamai's "Access Denied ... Reference #18.xxxx" page. Counts only beside a denial status.
    Signature("akamai_access_denied", re.compile(r"errors\.edgesuite\.net|Reference&#32;&#35;[0-9a-f.]+", re.I), "script"),
)

DENIAL_STATUSES = {401, 403}
SCAN_BYTES = 64 * 1024


def _find_signatures(body: bytes) -> list[tuple[Signature, str]]:
    text = body[:SCAN_BYTES].decode("utf-8", errors="replace")
    found = []
    for sig in SIGNATURES:
        match = sig.pattern.search(text)
        if match:
            found.append((sig, match.group(0)[:80]))
    return found


def classify_fetch(
    status: int | None,
    headers: dict[str, str],
    body: bytes,
    error: str | None,
) -> Classification:
    if error is not None or status is None:
        return Classification(FetchClass.ERROR, Confidence.VERIFIED, [f"transport error: {error}"])

    mitigated = headers.get("cf-mitigated", "").strip().lower()
    # 429 first: a Cloudflare rate-limiting rule sets cf-mitigated too, and a rate limit is the more exact name.
    if status == 429:
        evidence = ["status 429"]
        if "retry-after" in headers:
            evidence.append(f"header retry-after: {headers['retry-after']}")
        if mitigated:
            evidence.append(f"header cf-mitigated: {mitigated}")
        return Classification(FetchClass.RATE_LIMITED, Confidence.VERIFIED, evidence)

    if mitigated:  # Cloudflare says it answered instead of the site ("challenge" is the documented value)
        return Classification(
            FetchClass.BLOCKED,
            Confidence.VERIFIED,
            [f"header cf-mitigated: {mitigated}", f"status {status}"],
        )

    signatures = _find_signatures(body)
    sig_notes = [f"body signature {sig.name}: {snippet!r}" for sig, snippet in signatures]

    if status in DENIAL_STATUSES:
        return Classification(
            FetchClass.BLOCKED,
            Confidence.VERIFIED,
            [f"status {status} (access denied; bot protection vs. restricted page not determined)", *sig_notes],
        )

    if status == 503 and signatures:
        return Classification(FetchClass.BLOCKED, Confidence.ESTIMATED, [f"status {status}", *sig_notes])

    if status == 202:
        # Real pages are not served as 202 Accepted; bot challenges are (SiteGround, AWS WAF). Whatever the body
        # holds is the challenge's, so it is never analysed as the page's content.
        return Classification(FetchClass.BLOCKED, Confidence.ESTIMATED,
                              ["status 202 (Accepted: a bot challenge is served this way, a page is not)", *sig_notes])

    page_level = [(sig, snip) for sig, snip in signatures if sig.strength == "page"]
    if page_level:
        notes = [f"body signature {sig.name}: {snip!r}" for sig, snip in page_level]
        return Classification(FetchClass.BLOCKED, Confidence.ESTIMATED, [f"status {status}", *notes])

    evidence = [f"status {status}"]
    if signatures:
        evidence.append("script-level challenge marker present but page served normally; not treated as blocked")
    return Classification(FetchClass.OK, Confidence.VERIFIED, evidence)


# Who answered instead of the site, worked out from what the response itself says. A name here is a statement
# about one response to Maya's crawler; it does not say what any other crawler receives. (name, how it is known)
_BLOCKER_HEADERS = (
    ("Cloudflare", lambda h: "cf-mitigated" in h or "cf-ray" in h or "cloudflare" in h.get("server", "").lower()),
    ("Akamai", lambda h: "akamai" in h.get("server", "").lower()),
    ("DataDome", lambda h: "x-datadome" in h),
    ("Imperva", lambda h: "x-iinfo" in h or "incapsula" in h.get("x-cdn", "").lower() or "imperva" in h.get("x-cdn", "").lower()),
    ("Vercel", lambda h: h.get("server", "").lower() == "vercel"),
)
_BLOCKER_SIGNATURES = (("cloudflare", "Cloudflare"), ("akamai", "Akamai"), ("datadome", "DataDome"),
                       ("perimeterx", "HUMAN (PerimeterX)"), ("vercel", "Vercel"))


def identify_blocker(status: int | None, headers: dict[str, str], evidence: list[str], fetch_class: str) -> dict | None:
    """Name what blocked or slowed one response, or None when the response was the site's own.

    `kind` is "bot challenge" (a page asking the visitor to prove it is a browser), "rate limit" (429), or
    "access denied" (401/403 with nothing saying a challenge). `name` is the protection service when a header
    or a known challenge page names it, else None: a bare 403 can come from the site itself.
    """
    if fetch_class not in ("blocked", "rate_limited"):
        return None
    headers = {key.lower(): str(value) for key, value in (headers or {}).items()}
    text = " ".join(evidence or []).lower()
    name = next((label for marker, label in _BLOCKER_SIGNATURES if f"body signature {marker}" in text), None)
    if name is None:
        name = next((label for label, test in _BLOCKER_HEADERS if test(headers)), None)
    challenge = "cf-mitigated: challenge" in text or "body signature" in text
    kind = "rate limit" if fetch_class == "rate_limited" else "bot challenge" if challenge else "access denied"
    return {"name": name, "kind": kind, "status": status}


def describe_blockers(rows: list[dict]) -> list[dict]:
    """Group per-response blockers: [{"name", "kind", "status", "responses"}], most frequent first."""
    counts: dict[tuple, int] = {}
    for row in rows:
        key = (row["name"], row["kind"], row["status"])
        counts[key] = counts.get(key, 0) + 1
    return [{"name": name, "kind": kind, "status": status, "responses": n}
            for (name, kind, status), n in sorted(counts.items(), key=lambda item: -item[1])]


# -- empty answers and server error text (DECISIONS 204) ---------------------------------------------------------------

# A 2xx answer this small, with no title and no visible text, is an empty page (CrawlConfig.empty_response_max_bytes).
EMPTY_RESPONSE_MAX_BYTES = 512
_INVISIBLE = re.compile(r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_TAG = re.compile(r"<[^>]*>")
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
_ENTITY_SPACE = re.compile(r"&(?:nbsp|#160|#xa0|zwnj|zwj|#8203|#x200b);", re.I)
# Whitespace and the characters that take no room on the page: zero-width space and joiners, word joiner, BOM.
_BLANK = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff\u00a0]+")


def _blank(text: str) -> bool:
    return not _BLANK.sub("", _ENTITY_SPACE.sub("", text))


def empty_response(status: int | None, content_type: str | None, body: bytes, truncated: bool,
                   limit: int = EMPTY_RESPONSE_MAX_BYTES) -> bool:
    """Whether a response is an empty page: a 2xx answer, HTML or with no content type, not cut short, under `limit`
    bytes, with no non-empty <title> and no visible text once scripts, styles and invisible characters are left out.

    The size alone is not the rule (agent default, DECISIONS 204): a short real page with a title and a sentence is
    a page. A 0-byte answer, or a wrapper such as <html><head></head><body><script>…</script></body></html>, is not."""
    if status is None or not 200 <= status < 300 or truncated or len(body) >= limit:
        return False
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media and media not in ("text/html", "application/xhtml+xml"):
        return False
    text = body.decode("utf-8", errors="replace")
    title = _TITLE.search(text)
    if title and not _blank(_TAG.sub("", title.group(1))):
        return False
    visible = _TAG.sub(" ", _INVISIBLE.sub(" ", _TITLE.sub(" ", text)))
    return _blank(visible)


# An error message the server printed into the page (DECISIONS 204, LG-76). Counted only with a marker AND a path on
# the server, and only where it cannot be an article quoting one: a 5xx answer, a short body, or text before the page.
ERROR_MARKERS = re.compile(
    r"(?:Fatal error|Parse error|Warning)\s*:[^\n]{0,600}? on line \d+|Uncaught|Traceback \(most recent call last\)"
    r"|Stack trace:|Server Error in '/' Application", re.I)
SERVER_PATHS = re.compile(r"/home\d*/[^/\s<>\"']+/|/var/www/|public_html/|C:\\inetpub", re.I)
_PAGE_START = re.compile(r"<html\b|<!doctype", re.I)
ERROR_SCAN_BYTES = 64 * 1024
ERROR_SHORT_BODY = 4 * 1024
_TEXTUAL = ("text/html", "application/xhtml+xml", "text/plain")


def mask_server_path(text: str) -> str:
    """The account folder of a /home/<account>/ path cut to its first two characters: /home/u812345/ -> /home/u8…/."""
    return re.sub(r"(/home\d*/)([^/\s<>\"']+)/", lambda m: f"{m.group(1)}{m.group(2)[:2]}…/", text)


def error_disclosure(body: bytes, status: int | None = None, content_type: str | None = None) -> dict | None:
    """The first server error message in a response, with the server's file path in it, or None.

    Returns {"marker", "line"}: `line` is the line that holds the message, tags left out and the account folder
    masked, at most 300 characters. Any status; an HTML or plain-text body (or one with no content type)."""
    if not body:
        return None
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media and media not in _TEXTUAL:
        return None
    text = body[:ERROR_SCAN_BYTES].decode("utf-8", errors="replace")
    marker = ERROR_MARKERS.search(text)
    if marker is None or not SERVER_PATHS.search(text):
        return None
    start = _PAGE_START.search(text)
    if not ((status is not None and status >= 500) or len(body) < ERROR_SHORT_BODY
            or (start is not None and marker.start() < start.start())):
        return None
    plain = _TAG.sub(" ", text)
    found = ERROR_MARKERS.search(plain) or marker
    at = found.start()
    begin = plain.rfind("\n", 0, at) + 1
    end = plain.find("\n", found.end())
    line = " ".join(plain[begin:end if end != -1 else len(plain)].split())
    if not SERVER_PATHS.search(line):  # the path is on another line: quote the message with the first path line
        path_line = next((ln for ln in plain.splitlines() if SERVER_PATHS.search(ln)), "")
        line = f"{line} … {' '.join(path_line.split())}"
    return {"marker": found.group(0)[:60], "line": mask_server_path(line)[:300]}
