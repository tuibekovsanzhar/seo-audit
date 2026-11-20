"""ACC-4 user-agent differential probes (ownership-verified sites), and the smaller check of a site whose ownership is
not verified (`run_ua_check`: a browser and Googlebot's user agent only, DECISIONS 205).

Each sampled URL is fetched with a browser user agent, then with each search
and live-fetcher bot user agent. Every probe carries `X-Maya-Probe:
ua-differential` (spec §8 Q1) and counts against a per-audit cap.

These requests use a bot's user-agent string from Maya's IP. They are not
requests from the real bot; see the caveat attached to every ACC-4 finding.
"""

from __future__ import annotations

import hashlib
import time

from .analysis import analyze_html, sketch_similarity
from .classify import classify_fetch, empty_response, error_disclosure
from .config import CrawlConfig
from .fetcher import Fetcher
from .html_links import decode_body, is_html
from .models import FetchClass
from .urls import normalize_url
from .registry import REGISTRY, BotEntry, entry

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
PROBE_HEADERS = {"X-Maya-Probe": "ua-differential"}
# Headers that show where a response came from (edge or application) and what it was. Kept for both user agents.
KEPT_HEADERS = ("server", "cf-mitigated", "cf-ray", "x-powered-by", "retry-after", "content-type", "content-length",
                "location", "vary", "cf-cache-status", "x-cache", "age")
DELTA_SAMPLE = 20


def probe_bots() -> list[BotEntry]:
    return [e for e in REGISTRY if e.role in ("search", "live") and e.probe_user_agent]


def _observe(fetcher: Fetcher, url: str, label: str, user_agent: str, cfg: CrawlConfig, purpose: str = "probe") -> dict:
    response = fetcher.get(url, purpose, cfg.max_body_bytes, user_agent=user_agent, extra_headers=PROBE_HEADERS)
    classification = classify_fetch(response.status, response.headers, response.body, response.error)
    content_type = response.headers.get("content-type")
    words, title, text_sha256, sketch, visible = None, None, None, [], ""
    robots_head, robots_outside = None, None
    if response.body:
        text = decode_body(response.body, content_type)
        if is_html(content_type):
            facts = analyze_html(text)
            words, title, text_sha256 = facts["visible_words"], facts["title"], facts["text_sha256"]
            sketch, visible = facts["text_sketch"], facts["_visible_text"]
            # DECISIONS 374: where the robots tag sits for this user agent (in <head>, or after it)
            robots_head = [m.get("content") for m in facts.get("meta") or [] if str(m.get("name") or "").lower() == "robots"]
            robots_outside = list((facts.get("outside_head") or {}).get("robots_content") or [])
        else:
            words = len(text.split())
            text_sha256 = hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest() if text.strip() else None
            visible = text
    return {
        "label": label,
        "user_agent": user_agent,
        "url": url,
        "requested_at": response.started_at,
        "status": response.status,
        "error": response.error,
        "headers": {k: v for k, v in response.headers.items() if k in KEPT_HEADERS},
        "body_sha256": hashlib.sha256(response.body).hexdigest(),
        "body_bytes": len(response.body),
        # Where a redirect points; this fetcher never follows one, so this is the "final URL" the bot was sent to.
        "location": normalize_url(response.headers["location"], url) if response.headers.get("location") else None,
        "content_type": content_type,
        # Visible text, hashed after whitespace and case are normalized: markup noise (nonces, CSRF tokens, build
        # ids) changes body_sha256 on every request, so the visible-text hash is what "same content" is judged on.
        "text_sha256": text_sha256,
        "visible_words": words,
        "title": title,
        "robots_head": robots_head,
        "robots_outside_head": robots_outside,
        "_text_sketch": sketch,
        "_visible_text": visible[:100_000],
        "fetch_class": classification.fetch_class.value,
        "classification_evidence": classification.evidence,
        # A server error message with the server's file path, the account folder masked (IDX-1, DECISIONS 204).
        "error_disclosure": error_disclosure(response.body, response.status, content_type),
        # A 2xx answer with no content (DECISIONS 204): not a page a browser could read.
        "empty_response": empty_response(response.status, content_type, response.body, response.truncated),
    }


def _media(content_type: str | None) -> str | None:
    return content_type.split(";", 1)[0].strip().lower() if content_type else None


def text_delta(baseline: dict, observed: dict) -> dict | None:
    """Words the browser saw that the bot did not, and the reverse (samples), from the visible text."""
    a, b = baseline.get("_visible_text"), observed.get("_visible_text")
    if not a or b is None:
        return None
    words_a, words_b = a.casefold().split(), b.casefold().split()
    set_a, set_b = set(words_a), set(words_b)
    return {"browser_words": len(words_a), "bot_words": len(words_b),
            "only_in_browser_response": [w for w in dict.fromkeys(words_a) if w not in set_b][:DELTA_SAMPLE],
            "only_in_bot_response": [w for w in dict.fromkeys(words_b) if w not in set_a][:DELTA_SAMPLE]}


def compare(baseline: dict, observed: dict, degraded_ratio: float,
            same_similarity: float = 0.9) -> tuple[str, list[str]]:
    """Classify a bot response against the browser baseline (spec ACC-4 step 4).

    Outcomes: same | blocked | challenged | rate_limited | degraded | redirected | different_content.
    "blocked" includes a 4xx/5xx the bot received while the browser got a 2xx: whatever the reason, the bot
    cannot retrieve the page (spec §2.1). "redirected" (the bot was sent elsewhere) and "different_content"
    carry no severity; they become review items.
    """
    notes: list[str] = []
    fetch_class = observed["fetch_class"]
    b_status, o_status = baseline["status"], observed["status"]
    # An empty page to the bot where the browser got a real one (A21): the bot cannot read the page, whatever the status.
    if observed.get("empty_response") and not baseline.get("empty_response") and baseline.get("visible_words"):
        return "blocked", [f"empty {o_status} body to the bot user agent; the browser got {baseline['visible_words']} "
                           "visible words"]
    if fetch_class == FetchClass.BLOCKED.value:
        challenge = any("cf-mitigated" in e or "signature" in e for e in observed["classification_evidence"])
        outcome = "challenged" if challenge else "blocked"
    elif fetch_class == FetchClass.RATE_LIMITED.value:
        outcome = "rate_limited"
    elif fetch_class == FetchClass.ERROR.value:
        outcome = "blocked"
        notes.append(f"transport failure for the bot user agent ({observed['error']}) while the browser request succeeded")
    elif o_status != b_status and o_status and 300 <= o_status < 400:
        outcome = "redirected"
        notes.append(f"status {o_status} to the bot (Location: {observed.get('location')}) vs {b_status} to the browser"
                     + (f" (Location: {baseline.get('location')})" if baseline.get("location") else ""))
    elif (b_status and o_status and 300 <= b_status < 400 and o_status == b_status
          and observed.get("location") != baseline.get("location")):
        outcome = "redirected"
        notes.append(f"both redirected, the bot to {observed.get('location')}, the browser to {baseline.get('location')}")
    elif o_status != b_status and b_status and 200 <= b_status < 300 and o_status and o_status >= 400:
        outcome = "blocked"
        notes.append(f"status {o_status} to the bot user agent, {b_status} to the browser, for the same URL")
    elif o_status != b_status:
        outcome = "different_content"
        notes.append(f"status {o_status} vs browser {b_status}")
    elif _media(observed.get("content_type")) != _media(baseline.get("content_type")) and "content_type" in baseline:
        outcome = "different_content"
        notes.append(f"content type {observed.get('content_type')!r} vs browser {baseline.get('content_type')!r}")
    elif (
        baseline["visible_words"]
        and observed["visible_words"] is not None
        and observed["visible_words"] < degraded_ratio * baseline["visible_words"]
    ):
        outcome = "degraded"
        notes.append(f"{observed['visible_words']} visible words vs browser {baseline['visible_words']}")
    elif baseline.get("text_sha256") and baseline.get("text_sha256") == observed.get("text_sha256"):
        return "same", []
    elif observed["title"] != baseline["title"] and observed["body_sha256"] != baseline["body_sha256"]:
        outcome = "different_content"
        notes.append(f"title {observed['title']!r} vs browser {baseline['title']!r}")
    else:
        similarity = sketch_similarity(baseline.get("_text_sketch") or [], observed.get("_text_sketch") or [])
        if similarity is not None and similarity < same_similarity:
            outcome = "different_content"
            notes.append(f"same title, but the visible text differs: estimated similarity {similarity:.2f} "
                         f"(below {same_similarity:g})")
        else:
            return "same", []  # identical, or only markup noise / tiny text differences

    if baseline["headers"].get("x-powered-by") and not observed["headers"].get("x-powered-by"):
        notes.append(
            "the bot response lacks the X-Powered-By header the browser response had: it was likely answered "
            "at the edge, before the application ran"
        )
    return outcome, notes


def run_probes(fetcher: Fetcher, cfg: CrawlConfig, sample_urls: list[str]) -> dict:
    bots = probe_bots()
    used = 0
    capped = False
    sample_out: list[dict] = []
    pairs: list[dict] = []

    def fetch(url: str, label: str, user_agent: str) -> dict | None:
        nonlocal used, capped
        if used >= cfg.max_probe_requests:
            capped = True
            return None
        used += 1
        return _observe(fetcher, url, label, user_agent, cfg)

    for url in sample_urls:
        baseline = fetch(url, "browser", BROWSER_USER_AGENT)
        if baseline is None:
            break
        if baseline["fetch_class"] != FetchClass.OK.value:
            sample_out.append({
                "url": url, "assessed": False, "baseline": baseline,
                "reason": f"browser baseline was {baseline['fetch_class']}: cannot separate blocking AI bots "
                          "from blocking datacenter traffic in general",
            })
            continue
        sample_out.append({"url": url, "assessed": True, "baseline": baseline})

        for bot in bots:
            first = fetch(url, bot.token, bot.probe_user_agent)
            if first is None:
                break
            first_outcome, notes = compare(baseline, first, cfg.degraded_word_ratio, cfg.same_content_similarity)
            attempts, final, rebaselines, reference = [first], first_outcome, [], baseline
            if first_outcome != "same":
                for retry in range(cfg.probe_retries):
                    if cfg.probe_retry_cooldown_s:
                        if not fetcher.sleep(cfg.probe_retry_cooldown_s):
                            break
                    # Re-take the browser baseline right before each retry: a page that changes between two
                    # browser loads (rotating content, A/B tests) must not be read as the bot being treated
                    # differently. The retry is judged against this fresh baseline.
                    fresh = fetch(url, "browser", BROWSER_USER_AGENT)
                    if fresh is None:
                        break
                    rebaselines.append(fresh)
                    if fresh["fetch_class"] == FetchClass.OK.value:
                        reference = fresh
                    again = fetch(url, bot.token, bot.probe_user_agent)
                    if again is None:
                        break
                    attempts.append(again)
                    outcome, retry_notes = compare(reference, again, cfg.degraded_word_ratio,
                                                   cfg.same_content_similarity)
                    if outcome == "same":
                        final = "same"
                        notes.append(f"retry {retry + 1} matched the browser; the first result ({first_outcome}) was transient")
                        break
                    final, notes = outcome, retry_notes or notes
            pairs.append({
                "url": url,
                "token": bot.token,
                "role": bot.role,
                "engine": bot.engine,
                "outcome": final,
                "first_outcome": first_outcome,
                "confirmed": final != "same" and len(attempts) == 1 + cfg.probe_retries,
                "attempts": attempts,
                "browser_rebaselines": rebaselines,
                "text_delta": text_delta(reference, attempts[-1]) if final != "same" else None,
                "notes": notes,
                "launch_gate": list(bot.launch_gate),
            })
        if capped:
            break

    return {
        "browser_user_agent": BROWSER_USER_AGENT,
        "probe_headers": PROBE_HEADERS,
        "bots": [b.token for b in bots],
        "sample": sample_out,
        "pairs": pairs,
        "requests_used": used,
        "cap": cfg.max_probe_requests,
        "capped": capped,
        "retries": cfg.probe_retries,
        "retry_cooldown_s": cfg.probe_retry_cooldown_s,
    }


# -- ACC-4 without ownership (DECISIONS 205) ----------------------------------------------------------------------------

UA_CHECK_PURPOSE = "ua_check"
UA_CHECK_BOT = "Googlebot"
# Same status, but the bot's body is under half or over twice the browser's: recorded as Info (LG-77).
SIZE_RATIO = 2.0
# The browser's answer was not a real page (DECISIONS 216): the pair says nothing about a difference made for Googlebot.
BROWSER_NOT_REAL = "browser_not_real"
BROWSER_NOT_REAL_REASON = ("the browser also got an empty or error page: a server fault (see IDX-1), not a difference "
                           "made for Googlebot")


def browser_real(browser: dict) -> bool:
    """Whether the browser was answered with a real page: 2xx, not an empty page, no server error text (DECISIONS 216)."""
    status = browser.get("status")
    return (status is not None and 200 <= status < 300 and not browser.get("empty_response")
            and not browser.get("error_disclosure"))


def size_differs(browser_bytes: int, bot_bytes: int) -> bool:
    if browser_bytes == bot_bytes:
        return False
    if not browser_bytes:
        return True
    return bot_bytes * SIZE_RATIO < browser_bytes or bot_bytes > SIZE_RATIO * browser_bytes


def ua_verdict(browser: dict, bot: dict, cfg: CrawlConfig) -> tuple[str, list[str]]:
    """What one browser/Googlebot pair shows: "browser_not_real" (the browser itself got no real page: not assessed,
    DECISIONS 216), "server_error" (Googlebot 5xx, browser a real page), "refused" (Googlebot 403, 429 or a
    challenge), "size" (same status, body under half or over twice the browser's), "same", or another outcome of
    `compare` that this check does not report (it stays in the evidence)."""
    if not browser_real(browser):
        return BROWSER_NOT_REAL, [BROWSER_NOT_REAL_REASON]
    outcome, notes = compare(browser, bot, cfg.degraded_word_ratio, cfg.same_content_similarity)
    b_status, o_status = browser.get("status"), bot.get("status")
    browser_ok = b_status is not None and 200 <= b_status < 300
    # A challenge the CDN puts in front of an unverified "Googlebot" (A22): Cloudflare and others let the real Googlebot
    # through by its verified addresses, so a challenge to Maya's spoofed one says little about Google's crawler.
    if outcome == "challenged":
        return "challenged", [*notes, "a CDN challenge (such as cf-mitigated) to a Googlebot user agent from an address "
                                      "that is not Google's; the real Googlebot may be on the CDN's verified-bot allowlist"]
    if outcome == "rate_limited" or (outcome == "blocked" and o_status in (401, 403)):
        return "refused", notes
    # The bot was told the page does not exist, or sent an empty page, where the browser read it (A21).
    if browser_ok and o_status in (404, 410):
        return "not_found_for_bot", notes
    if browser_ok and bot.get("empty_response") and o_status is not None and 200 <= o_status < 300:
        return "empty_for_bot", notes
    if browser_ok and o_status is not None and o_status >= 500:
        return "server_error", notes
    if b_status == o_status and size_differs(browser.get("body_bytes") or 0, bot.get("body_bytes") or 0):
        return "size", [*notes, f"{bot.get('body_bytes')} bytes to Googlebot's user agent, {browser.get('body_bytes')} "
                                 "bytes to the browser"]
    return outcome, notes


def run_ua_check(fetcher: Fetcher, cfg: CrawlConfig, urls: list[str], policy) -> dict:
    """ACC-4 on a site whose ownership is not verified (DECISIONS 205, amending spec §8 Q1).

    Per URL one request with a browser user agent and one with Googlebot's, both tagged `X-Maya-Probe:
    ua-differential`, purpose `ua_check`, never retried. The Googlebot request is sent only where robots.txt allows
    both Googlebot and Maya's own token; otherwise the pair is not assessed and neither request is sent."""
    bot = entry(UA_CHECK_BOT)
    pairs: list[dict] = []
    used = 0
    for url in urls[: cfg.ua_check_urls]:
        if not (policy.decide(bot.token, url).allowed and policy.decide(cfg.product_token, url).allowed):
            pairs.append({"url": url, "assessed": False, "reason": "not assessed (robots.txt)"})
            continue
        browser = _observe(fetcher, url, "browser", BROWSER_USER_AGENT, cfg, UA_CHECK_PURPOSE)
        used += 1
        if browser["fetch_class"] != FetchClass.OK.value:
            pairs.append({"url": url, "assessed": False, "browser": browser,
                          "reason": f"browser baseline was {browser['fetch_class']}: cannot separate blocking Googlebot "
                                    "from blocking datacenter traffic in general"})
            continue
        googlebot = _observe(fetcher, url, bot.token, bot.probe_user_agent, cfg, UA_CHECK_PURPOSE)
        used += 1
        verdict, notes = ua_verdict(browser, googlebot, cfg)
        if verdict == BROWSER_NOT_REAL:  # both answers kept: Googlebot's error text still goes to IDX-1
            pairs.append({"url": url, "assessed": False, "outcome": verdict, "browser": browser, "googlebot": googlebot,
                          "notes": notes, "reason": BROWSER_NOT_REAL_REASON})
            continue
        pairs.append({"url": url, "assessed": True, "outcome": verdict, "browser": browser, "googlebot": googlebot,
                      "notes": notes})
    return {
        "browser_user_agent": BROWSER_USER_AGENT,
        "bot": bot.token,
        "bot_user_agent": bot.probe_user_agent,
        "probe_headers": PROBE_HEADERS,
        "urls": list(urls[: cfg.ua_check_urls]),
        "pairs": pairs,
        "requests_used": used,
        "cap": 2 * cfg.ua_check_urls,
        "retries": 0,
        "launch_gate": ["LG-77"],
    }
