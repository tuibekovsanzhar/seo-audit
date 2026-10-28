"""ACC-1..ACC-8 against the local fake websites, checked from both sides."""

import json

from maya_audit.intent import DeclaredPolicy, IntentMarking
from maya_audit.registry import REGISTRY

BOT_TOKENS = [e.token.lower() for e in REGISTRY]


def entry_ua(token):
    from maya_audit.registry import entry
    return entry(token).probe_user_agent


def probe_requests(run):
    return [r for r in run.requests if any(t in r.user_agent.lower() for t in BOT_TOKENS) or "Chrome/" in r.user_agent]


def test_ai_friendly_site_passes_everything(run_audit_scenario):
    run = run_audit_scenario("acc_ai_friendly")
    statuses = {cid: c.status for cid, c in run.checks.items() if cid.startswith("ACC-")}
    assert statuses == {
        "ACC-1": "pass", "ACC-2": "pass", "ACC-3": "pass", "ACC-4": "pass",
        "ACC-5": "not_assessed", "ACC-6": "pass", "ACC-7": "pass", "ACC-8": "pass", "ACC-9": "pass",
    }
    assert len(run.result.access.robots_samples) == 3
    assert run.checks["ACC-4"].evidence["ownership"]["verified"] is True
    # Server side: every probe carried the header, and Maya's own requests did not.
    probes = probe_requests(run)
    assert probes and all(r.headers.get("x-maya-probe") == "ua-differential" for r in probes)
    own = [r for r in run.requests if r.user_agent == run.config.user_agent]
    assert own and all("x-maya-probe" not in r.headers for r in own)
    assert run.gates["INT-4"].state == "compliant", run.gates["INT-4"].summary


def test_robots_rules_per_role(run_audit_scenario):
    run = run_audit_scenario("acc_robots_rules")
    by_line = {(f.evidence["rule"]["line"], f.severity.value): f for f in run.findings("ACC-2") if "rule" in f.evidence}

    perplexity = by_line[(15, "S1")]
    assert "PerplexityBot" in perplexity.title and perplexity.engines == ["Perplexity search"]
    assert perplexity.evidence["reproduce"].endswith("sed -n '15p'")

    oai = by_line[(11, "S1")]
    assert oai.scope["urls"] == [run.url("/pricing")]
    assert by_line[(18, "S3")].title.count("ChatGPT-User") == 1
    training = by_line[(8, "S4")]
    assert {"GPTBot", "ClaudeBot", "Google-Extended", "CCBot"} <= set(training.title.replace(",", "").split())

    precedence = [f for f in run.findings("ACC-2", "Info") if f.title.startswith("Group precedence")]
    assert precedence and "line 2" in precedence[0].title and "OAI-SearchBot" in precedence[0].title

    # Launch-gate labels on robots findings never cite the probe user-agent string.
    assert all("probe user-agent" not in g for f in run.findings("ACC-2") for g in f.launch_gated)

    acc4 = run.checks["ACC-4"]
    # Ownership not verified: only a browser and Googlebot's user agent were compared (DECISIONS 205).
    assert acc4.status == "partial" and acc4.summary.startswith("Firewall blocking was only partly assessed")
    from maya_audit.probes import BROWSER_USER_AGENT
    assert {r.user_agent for r in probe_requests(run)} <= {BROWSER_USER_AGENT, entry_ua("Googlebot")}
    assert len(probe_requests(run)) <= 6

    lines = run.checks["ACC-6"].evidence["vendor_lines"]
    assert any(l.startswith("OpenAI: Training (GPTBot): blocked") for l in lines)
    google = next(f for f in run.findings("ACC-6") if f.title.startswith("Google"))
    assert any("does not remove the site from AI Overviews" in n for n in google.notes)

    [delay] = run.findings("ACC-7", "S4")
    assert "120s" in delay.title and "line 12" in delay.title and delay.engines == ["ChatGPT search"]


def test_declared_policy_and_intent_marking_move_findings_to_info(run_audit_scenario):
    marking = IntentMarking("m-pricing", "ACC-2", "disallow", "/pricing", token="OAI-SearchBot", marked_by="owner")
    run = run_audit_scenario(
        "acc_robots_rules", policy=DeclaredPolicy(training_bots="block"), intent_markings=(marking,)
    )
    info = [f for f in run.findings("ACC-2", "Info") if f.intent]
    training = next(f for f in info if f.intent["kind"] == "declared_policy" and "GPTBot" in f.title)
    assert training.intent["severity_otherwise"] == "S4"
    assert not [f for f in run.findings("ACC-2", "S4")]  # every training block now matches the declared policy
    marked = next(f for f in info if f.intent["kind"] == "intent_marking")
    assert marked.intent == {**marked.intent, "marking_id": "m-pricing", "severity_otherwise": "S1"}
    assert "OAI-SearchBot" in marked.title
    # Unmarked search-bot blocks keep their severity.
    assert any("PerplexityBot" in f.title for f in run.findings("ACC-2", "S1"))


def test_policy_mismatch_both_directions(run_audit_scenario):
    allow = run_audit_scenario("acc_robots_rules", policy=DeclaredPolicy(training_bots="allow"))
    s4 = next(f for f in allow.findings("ACC-2", "S4") if "GPTBot" in f.title)
    assert s4.evidence.get("policy_mismatch") is True

    block = run_audit_scenario("acc_ai_friendly", policy=DeclaredPolicy(training_bots="block"))
    [mismatch] = [f for f in block.findings("ACC-2") if f.title.startswith("Policy mismatch")]
    assert mismatch.severity.value == "Info" and "GPTBot" in mismatch.title


def test_page_level_controls(run_audit_scenario):
    run = run_audit_scenario("acc_meta_controls")
    titles = {f.title: f for f in run.findings("ACC-3")}

    critical_noindex = next(f for t, f in titles.items()
                            if t.startswith("noindex via meta") and f.severity.value == "S1")
    reviewed_noindex = next(f for t, f in titles.items()
                            if t.startswith("noindex via meta") and f.severity.value == "Info")
    assert critical_noindex.scope["urls"] == [run.url("/tag/featured")]
    assert set(reviewed_noindex.scope["urls"]) == {run.url(p) for p in ("/noindex", "/tag/a", "/tag/b", "/cart")}
    assert critical_noindex.importance_tier == 0

    header = next(f for t, f in titles.items() if t.startswith("nosnippet via X-Robots-Tag (googlebot)"))
    assert header.severity.value == "S1" and header.engines == ["Google AI Overviews / AI Mode"]
    assert next(f for t, f in titles.items() if t.startswith("max-snippet:0")).severity.value == "S1"
    assert next(f for t, f in titles.items() if t.startswith("max-snippet below 50")).severity.value == "S2"
    data = next(f for t, f in titles.items() if t.startswith("main content inside data-nosnippet"))
    assert data.severity.value == "S2" and data.scope["urls"] == [run.url("/datanosnippet")]
    bing = next(f for t, f in titles.items() if t.startswith("noarchive via meta (bingbot)"))
    assert bing.severity.value == "S2" and bing.launch_gated
    # A PDF's only way to be withheld is its header, so non-HTML documents are checked too.
    pdf = next(f for t, f in titles.items() if t.startswith("noindex via X-Robots-Tag"))
    assert pdf.severity.value == "Info" and pdf.scope["urls"] == [run.url("/terms.pdf")]
    acc3 = run.checks["ACC-3"]
    assert acc3.evidence["non_html_documents_checked"] == 2
    assert {d["url"].rsplit("/", 1)[-1] for d in acc3.evidence["non_html_documents"]} == {"terms.pdf", "brochure.pdf"}


def test_pattern_marking_never_covers_key_page(run_audit_scenario):
    marking = IntentMarking("m-tags", "ACC-3", "noindex", "/tag/*", marked_by="owner")
    run = run_audit_scenario("acc_meta_controls", intent_markings=(marking,))
    noindex = [f for f in run.findings("ACC-3") if f.title.startswith("noindex via meta")]
    marked = next(f for f in noindex if f.intent)
    assert set(marked.scope["urls"]) == {run.url("/tag/a"), run.url("/tag/b")}
    assert marked.severity.value == "Info" and marked.intent["severity_otherwise"] == "Info"
    unmarked = next(f for f in noindex if not f.intent and f.severity.value == "Info")
    assert set(unmarked.scope["urls"]) == {run.url("/noindex"), run.url("/cart")}
    assert any(f.scope["urls"] == [run.url("/tag/featured")] and f.severity.value == "S1"
               for f in noindex if not f.intent)

    exact = IntentMarking("m-featured", "ACC-3", "noindex", "{base}/tag/featured", marked_by="owner")
    run = run_audit_scenario("acc_meta_controls", intent_markings=(marking, exact))
    marked_featured = [f for f in run.findings("ACC-3") if f.title.startswith("noindex via meta") and f.intent]
    assert any(f.scope["urls"] == [run.url("/tag/featured")] and f.severity.value == "Info"
               for f in marked_featured)


def test_waf_differential_on_verified_site(run_audit_scenario):
    run = run_audit_scenario("acc_waf_verified")
    acc4 = run.checks["ACC-4"]
    found = {(f.severity.value, f.title.split(" were ")[1].split(" on ")[0]): f for f in acc4.findings}

    challenged = found[("S1", "challenged")]
    assert "OAI-SearchBot" in challenged.title and "PerplexityBot" in challenged.title
    assert any("X-Powered-By" in n for n in challenged.notes)
    assert challenged.notes[0].startswith("Maya sent these requests with each bot's user-agent string")
    assert challenged.evidence["pairs"][0]["reproduce_bot"].count("X-Maya-Probe") == 1
    assert "ChatGPT-User" in found[("S2", "rate limited")].title
    assert "Claude-SearchBot" in found[("S2", "degraded")].title

    # Different content has no severity but must be visible as a review item, not an Info finding.
    [review] = acc4.review_items
    assert "Bingbot" in review.title and "different content" in review.title
    assert not any("different content" in f.title for f in acc4.findings)
    assert review.evidence["pairs"][0]["attempts"][0]["title"] == "Welcome, crawler"

    transient = [o for o in acc4.observations if o["token"] == "Perplexity-User"]
    assert transient and all(o["first_outcome"] == "rate_limited" for o in transient)

    probes = probe_requests(run)
    assert all(r.headers.get("x-maya-probe") == "ua-differential" for r in probes)
    int4 = run.gates["INT-4"]
    assert int4.state == "compliant" and int4.evidence["probes"]["count"] == len(probes)
    assert int4.evidence["probes"]["count"] <= run.config.max_probe_requests


def test_differential_v2_status_redirect_text_and_a_page_that_changed(run_audit_scenario):
    run = run_audit_scenario("acc_waf_v2")
    acc4 = run.checks["ACC-4"]
    pricing, changing = run.url("/pricing"), run.url("/changing")

    # A 404 only for the bot while the browser gets 200: the bot cannot retrieve the page.
    blocked = next(f for f in acc4.findings if "MistralAI-User" in f.title)
    assert blocked.severity.value == "S2" and "blocked" in blocked.title and blocked.confidence.value == "verified"
    row = blocked.evidence["pairs"][0]
    assert row["url"] == pricing and row["browser"]["status"] == 200 and row["attempts"][0]["status"] == 404
    assert any("404 to the bot" in n for n in row["notes"])
    assert row["browser"]["text_sha256"] and row["browser"]["content_type"].startswith("text/html")
    assert len(row["browser_rebaselines"]) == run.config.probe_retries  # a fresh browser look before each retry

    reviews = {r.title.split(" user agents ")[1].split(" on ")[0]: r for r in acc4.review_items}
    redirected = reviews["were redirected somewhere a browser was not sent"]
    assert "Amazonbot" in redirected.title
    assert redirected.evidence["pairs"][0]["attempts"][0]["location"] == run.url("/bot-landing")

    different = reviews["received different content than a browser"]
    assert "Applebot" in different.title
    delta = different.evidence["pairs"][0]["text_delta"]
    assert "crawler," in delta["only_in_bot_response"] and delta["browser_words"] and delta["bot_words"]

    # The page changed after the first probe. Against a fresh browser baseline the bots match, so this is a
    # transient observation, never "different content".
    assert not any(changing in item.scope["urls"] for item in acc4.review_items + acc4.findings)
    assert any(o["url"] == changing and o["first_outcome"] == "different_content" for o in acc4.observations)


def test_waf_site_without_ownership_gets_no_probes(run_audit_scenario):
    """Without ownership only the small check runs (DECISIONS 205): at most 6 tagged requests, a browser and Googlebot's
    user agent, none retried. No other AI crawler's user agent reaches the server."""
    from maya_audit.probes import BROWSER_USER_AGENT
    from maya_audit.registry import entry

    run = run_audit_scenario("acc_waf_not_owned")
    acc4 = run.checks["ACC-4"]
    assert acc4.status == "partial" and acc4.findings == []
    assert acc4.summary.startswith("Firewall blocking was only partly assessed")
    seen = probe_requests(run)
    assert 0 < len(seen) <= 6
    assert {r.user_agent for r in seen} == {BROWSER_USER_AGENT, entry("Googlebot").probe_user_agent}
    assert all(r.headers.get("x-maya-probe") == "ua-differential" for r in seen)
    pairs = [(r.path, r.user_agent) for r in seen]
    assert len(pairs) == len(set(pairs))  # one request each: nothing was retried
    assert "not done" in run.checks["ACC-1"].evidence["per_bot_user_agent_fetches"]
    assert run.gates["INT-4"].state == "compliant", run.gates["INT-4"].summary


def test_probe_cap_is_enforced(run_audit_scenario):
    run = run_audit_scenario("acc_waf_verified", max_probe_requests=10)
    assert run.result.access.probes["capped"] is True
    assert len(probe_requests(run)) == 10
    assert run.gates["INT-4"].state == "compliant"


def test_intermittent_robots_503(run_audit_scenario):
    run = run_audit_scenario("acc_robots_flaky")
    [finding] = run.findings("ACC-1", "S1")
    assert "1 of 3" in finding.title and finding.scope["kind"] == "sitewide"
    assert finding.evidence["statuses_in_order"] == [200, 503, 200]


def test_robots_html_and_huge(run_audit_scenario):
    html = run_audit_scenario("acc_robots_html")
    assert [f.severity.value for f in html.findings("ACC-1")] == ["Info"]
    huge = run_audit_scenario("acc_robots_huge")
    assert [f.severity.value for f in huge.findings("ACC-1")] == ["S3"]


def test_robots_unavailable_everywhere(run_audit_scenario):
    run = run_audit_scenario("robots_503")
    [finding] = run.findings("ACC-1", "S1")
    assert "3 of 3" in finding.title
    assert run.checks["ACC-2"].status == "not_assessed"
    assert run.checks["ACC-6"].status == "not_assessed"
    assert all(not d["fetched"] for d in run.result.access.llms)
    assert [r.path for r in run.requests] == ["/robots.txt"] * 3  # nothing but robots.txt samples


def test_llms_txt_is_recorded_not_scored(run_audit_scenario):
    run = run_audit_scenario("acc_llms_txt")
    [finding] = run.findings("ACC-8")
    assert finding.severity.value == "Info" and finding.title == "llms.txt is present"
    assert finding.rationale == "Hypothesis"


def test_crawl_delay_is_capped_and_reported(run_audit_scenario):
    run = run_audit_scenario("acc_crawl_delay_capped")
    int4 = run.gates["INT-4"]
    assert int4.state == "compliant"
    [delay] = int4.evidence["politeness"]["crawl_delay"]
    assert (delay["seconds"], delay["honored_seconds"], delay["capped"]) == (2.0, 0.3, True)
    assert int4.evidence["politeness"]["min_observed_gap_ms"] >= 300 - 25
    assert "honored it up to its 0.3s cap" in int4.summary
    [info] = [f for f in run.findings("ACC-7") if "Maya-Audit" in f.title]
    assert {k: v for k, v in info.evidence.items() if k != "severity_assessment"} == {"declared_seconds": 2.0, "honored_seconds": 0.3, "line": 2}
    assert info.evidence["severity_assessment"]["severity"] == "Info"


def _write_logs(tmp_path, base_host="example.test"):
    ranges = tmp_path / "searchbot.json"
    ranges.write_text(json.dumps({"prefixes": [{"ipv4Prefix": "20.171.0.0/16"}]}))
    ua = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"
    lines = [
        f'20.171.1.1 - - [10/Sep/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 512 "-" "{ua}"',
        f'20.171.1.2 - - [11/Sep/2026:10:00:00 +0000] "GET /pricing HTTP/1.1" 200 512 "-" "{ua}"',
        f'20.171.1.2 - - [12/Sep/2026:10:00:00 +0000] "GET /pricing HTTP/1.1" 503 12 "-" "{ua}"',
        f'1.2.3.4 - - [12/Sep/2026:11:00:00 +0000] "GET / HTTP/1.1" 200 512 "-" "{ua}"',
        '5.6.7.8 - - [12/Sep/2026:12:00:00 +0000] "GET / HTTP/1.1" 200 512 "-" "PerplexityBot/1.0"',
        "garbage line",
    ]
    log = tmp_path / "access.log"
    log.write_text("\n".join(lines))
    return str(log), str(ranges)


def test_access_logs(run_audit_scenario, tmp_path):
    log, ranges = _write_logs(tmp_path)
    run = run_audit_scenario("acc_ai_friendly", access_logs=(log,), ip_range_files=(("OAI-SearchBot", ranges),))
    acc5 = run.checks["ACC-5"]
    assert acc5.evidence["entries_parsed"] == 5 and acc5.evidence["lines_unparsed"] == 1
    obs = {(o["bot"], o["metric"]): o for o in acc5.observations}
    share = obs[("OAI-SearchBot", "non-2xx share of IP-verified requests")]
    assert share["value"] == "1/3 (33.3%)" and share["threshold"].startswith("not set")
    assert obs[("OAI-SearchBot", "last seen (IP-verified)")]["value"].startswith("2026-09-12T10:00:00")
    assert obs[("OAI-SearchBot", "requests claiming this bot from IPs outside its published ranges")]["value"] == 1
    assert obs[("PerplexityBot", "requests that could not be IP-verified (no range file loaded)")]["value"] == 1

    [never] = acc5.findings
    assert never.severity.value == "S4" and never.cost_tier == "T3"
    assert set(never.scope["urls"]) == {run.url("/docs/a"), run.url("/docs/b")}


def test_access_logs_jsonl(run_audit_scenario, tmp_path):
    ranges = tmp_path / "r.txt"
    ranges.write_text("20.171.0.0/16\n")
    log = tmp_path / "logpush.jsonl"
    record = {"ClientIP": "20.171.9.9", "EdgeStartTimestamp": "2026-09-12T10:00:00Z", "ClientRequestURI": "/",
              "EdgeResponseStatus": 200, "ClientRequestUserAgent": "OAI-SearchBot/1.0"}
    log.write_text(json.dumps(record) + "\n")
    run = run_audit_scenario("acc_ai_friendly", access_logs=(str(log),), access_log_format="cloudflare_logpush",
                             ip_range_files=(("OAI-SearchBot", str(ranges)),))
    assert run.checks["ACC-5"].evidence["entries_parsed"] == 1
    assert run.result.access.logs["bots"]["OAI-SearchBot"]["verified"] == 1


def test_int4_rederives_ownership_instead_of_trusting_the_flag(run_audit_scenario):
    """A probe on a site whose homepage lacks the verification tag is a violation, whatever the stored flag says."""
    from dataclasses import replace

    from maya_audit.checks.integrity import int4_crawler_identity

    run = run_audit_scenario("acc_waf_verified", max_probe_requests=5)
    assert run.gates["INT-4"].state == "compliant"
    wrong_token = replace(run.config, site_verification_token="not-the-real-token")
    gate = int4_crawler_identity(run.result, wrong_token)
    assert gate.state == "violation" and "ownership is not verified" in gate.summary
