import pytest

from maya_audit.analysis import analyze_html
from maya_audit.checks.access import _parse_directive_list
from maya_audit.intent import IntentMarking, find_marking
from maya_audit.probes import compare
from maya_audit.registry import REGISTRY, ROLES, UNVERIFIED_PROBE_UA, by_role, entry


def test_registry_integrity():
    tokens = [e.token.lower() for e in REGISTRY]
    assert len(tokens) == len(set(tokens))
    assert all(e.role in ROLES for e in REGISTRY)
    # A search or live bot with no probe string says so in its launch gate (B14: Meta-ExternalFetcher).
    from maya_audit.registry import NOT_PROBED
    assert all(e.probe_user_agent or NOT_PROBED in e.launch_gate for e in REGISTRY if e.role in ("search", "live"))
    assert all(e.token.lower() in e.probe_user_agent.lower() for e in REGISTRY if e.probe_user_agent)


def test_launch_gate_matches_spec():
    gated = {e.token for e in REGISTRY if any(r != UNVERIFIED_PROBE_UA for r in e.launch_gate)}
    required = {"Applebot", "Applebot-Extended", "Amazonbot", "meta-externalagent", "DuckAssistBot", "MistralAI-User",
                "CCBot"}
    assert required <= gated
    # Rows checked against vendor docs carry no role/robots gate. Anthropic's three were checked against its
    # own support article on 2026-09-22 (LG-04); their probe user-agent strings are still unverified.
    for token in ("OAI-SearchBot", "GPTBot", "PerplexityBot", "Perplexity-User", "Googlebot", "Google-Extended",
                  "Claude-SearchBot", "Claude-User", "ClaudeBot"):
        assert all(r == UNVERIFIED_PROBE_UA for r in entry(token).launch_gate)
    assert UNVERIFIED_PROBE_UA in entry("Claude-SearchBot").launch_gate  # the article gives tokens, not UA strings
    assert {entry(t).ip_ranges_url for t in ("ClaudeBot", "Claude-User", "Claude-SearchBot")} == {
        "https://claude.com/crawling/bots.json"}
    assert not entry("PerplexityBot").launch_gated  # full UA strings verified from Perplexity's docs


def test_intent_marking_rules():
    with pytest.raises(ValueError):
        IntentMarking("x", "IDX-1", "5xx", "/a")  # defects are not markable
    with pytest.raises(ValueError):
        IntentMarking("x", "IDX-7", "orphan", "/a", token="GPTBot")  # tokens only on ACC checks

    pattern = IntentMarking("p", "ACC-3", "noindex", "/tag/*")
    exact = IntentMarking("e", "ACC-3", "noindex", "https://s.test/tag/key")
    key = {"https://s.test/tag/key"}
    assert find_marking((pattern,), "ACC-3", "noindex", "https://s.test/tag/a", None, key)[0] is pattern
    matched, blocked = find_marking((pattern,), "ACC-3", "noindex", "https://s.test/tag/key", None, key)
    assert matched is None and blocked is pattern
    assert find_marking((pattern, exact), "ACC-3", "noindex", "https://s.test/tag/key", None, key)[0] is exact
    assert find_marking((pattern,), "ACC-3", "nosnippet", "https://s.test/tag/a", None, key)[0] is None

    scoped = IntentMarking("t", "ACC-2", "disallow", "/app/*", token="Perplexity-User")
    assert find_marking((scoped,), "ACC-2", "disallow", "https://s.test/app/x", "Perplexity-User", set())[0] is scoped
    assert find_marking((scoped,), "ACC-2", "disallow", "https://s.test/app/x", "GPTBot", set())[0] is None


def test_x_robots_tag_parsing():
    assert _parse_directive_list("googlebot: noindex, nosnippet", "*") == [
        ("googlebot", "noindex", None), ("googlebot", "nosnippet", None)]
    assert _parse_directive_list("max-snippet:20, noarchive", "*") == [("*", "max-snippet", "20"), ("*", "noarchive", None)]
    assert _parse_directive_list("bingbot: noarchive, googlebot: max-snippet:0", "*") == [
        ("bingbot", "noarchive", None), ("googlebot", "max-snippet", "0")]


def test_analysis_counts_data_nosnippet_in_main():
    html = ("<html><head><title>T</title><meta name='robots' content='noindex'>"
            "<meta name='maya-site-verification' content='abc'></head><body><nav>menu</nav>"
            "<main><div data-nosnippet><p>secret words here</p><img src=x></div><p>open</p></main>"
            "<script>var x = 'not text'</script></body></html>")
    a = analyze_html(html)
    assert a["title"] == "T"
    assert {"name": "robots", "content": "noindex"} in a["meta"]
    assert a["verification_tokens"] == ["abc"]
    assert a["has_main_region"] and a["main_region_nosnippet_chars"] == len("secret words here")
    assert a["main_region_chars"] == len("secret words here") + len("open")
    assert a["visible_words"] == 5  # menu, secret, words, here, open


def base(**kw):
    return {"status": 200, "visible_words": 100, "title": "Home", "body_sha256": "a", "headers": {"x-powered-by": "App"},
            "fetch_class": "ok", "classification_evidence": [], "error": None, **kw}


def test_probe_compare_outcomes():
    b = base()
    assert compare(b, base(headers={"x-powered-by": "App"}), 0.5) == ("same", [])
    outcome, notes = compare(b, base(status=403, fetch_class="blocked", classification_evidence=["header cf-mitigated: challenge"], headers={}), 0.5)
    assert outcome == "challenged" and any("X-Powered-By" in n for n in notes)
    assert compare(b, base(status=403, fetch_class="blocked", classification_evidence=["status 403"]), 0.5)[0] == "blocked"
    assert compare(b, base(status=429, fetch_class="rate_limited"), 0.5)[0] == "rate_limited"
    assert compare(b, base(status=None, fetch_class="error", error="timeout"), 0.5)[0] == "blocked"
    # A 4xx to the bot while the browser gets 200: the bot cannot retrieve the page (spec §2.1).
    assert compare(b, base(status=404), 0.5)[0] == "blocked"
    assert compare(b, base(status=301, location="https://s.test/login"), 0.5)[0] == "redirected"
    assert compare(base(status=404), base(status=200), 0.5)[0] == "different_content"
    assert compare(b, base(content_type="text/html"), 0.5)[0] == "same"  # no baseline content type: not compared
    same_text = base(body_sha256="b", text_sha256="t", title="Other")
    assert compare(base(text_sha256="t"), same_text, 0.5)[0] == "same"  # identical visible text wins over markup
    assert compare(b, base(visible_words=10, body_sha256="b"), 0.5)[0] == "degraded"
    assert compare(b, base(body_sha256="b", title="Other"), 0.5)[0] == "different_content"
    assert compare(b, base(body_sha256="b"), 0.5)[0] == "same"  # dynamic tokens alone are not a difference


def test_cloudflare_timestamp_formats_and_unknown_format():
    from maya_audit.logs import _parse_time, parse_log_lines

    assert _parse_time(1757671200000000000).isoformat() == "2025-09-12T10:00:00+00:00"  # unixnano (default)
    assert _parse_time(1757671200).isoformat() == "2025-09-12T10:00:00+00:00"  # unix seconds
    assert _parse_time("2025-09-12T10:00:00Z").isoformat() == "2025-09-12T10:00:00+00:00"  # rfc3339
    with pytest.raises(ValueError):
        parse_log_lines(["{}"], "jsonl")
