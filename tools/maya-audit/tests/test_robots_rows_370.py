"""DECISIONS 370: a robots.txt / crawler finding is attached only to the addresses its rule blocks, each with the rule
and the bots blocked there, plus one site-wide line (the rule, how many sampled addresses it blocks, the rest open);
a bot is never said to be blocked on an address it can fetch. Fake servers and reports only."""
from __future__ import annotations

from maya_audit import page_rows, reassess_rules
from maya_audit.example_rows import attach, robots_pages, robots_site_row, tr_count

SITE = "https://shop.test"
RULE = "disallowed by line 5: Disallow: /profile/"


def test_the_live_check_attaches_a_vendor_only_where_its_bots_are_blocked(run_audit_scenario):
    run = run_audit_scenario("acc_robots_rules")
    for f in run.findings("ACC-6"):
        pages = f.evidence["pages"]
        assert pages and {p["url"] for p in pages} == set(f.scope["urls"])
        assert all(p["blocked"] and set(p["blocked"]) <= set(f.evidence["blocked_tokens"]) for p in pages)
        assert "örnek adresten" in f.evidence["site_row"]["tr"]


def test_the_site_line_says_the_rule_the_share_and_that_the_rest_is_open():
    line = robots_site_row([RULE], 1, 30, ["GPTBot", "Googlebot"])
    assert line["tr"] == "robots.txt 5. satır Disallow: /profile/ → 30 örnek adresten 1'i engelli (GPTBot, Googlebot); diğer sayfalar açık"
    assert line["en"] == "robots.txt line 5 Disallow: /profile/ → 1 of 30 sampled addresses blocked (GPTBot, Googlebot); the other pages are open"
    assert robots_site_row([RULE], 30, 30, ["CCBot"])["tr"].endswith("; örnek adreslerin hepsi engelli")
    assert [tr_count(n) for n in (1, 2, 3, 6, 10, 30, 40, 100)] == ["1'i", "2'si", "3'ü", "6'sı", "10'u", "30'u", "40'ı", "100'ü"]


def _saved(title="OpenAI: Training (GPTBot): partly blocked (1/30 sampled URLs) · Search (OAI-SearchBot): partly "
                 "blocked (1/30 sampled URLs) · Live fetch (ChatGPT-User): allowed", acc2=True):
    sample = [{"url": SITE + "/"}, {"url": SITE + "/a"}, {"url": SITE + "/profile/card"}]
    acc6 = {"id": "ACC-6-o", "check_id": "ACC-6", "rule_id": "acc6.scope", "title": title, "severity": "Info",
            "scope": {"kind": "sitewide", "count": 3, "urls": [s["url"] for s in sample]},
            "evidence": {"sample_size": 30, "blocked_tokens": ["GPTBot", "OAI-SearchBot"]}}
    decisions = [{"url": SITE + "/profile/card", "token": t, "reason": RULE} for t in ("GPTBot", "OAI-SearchBot", "PerplexityBot")]
    blocks = {"id": "ACC-2-b", "check_id": "ACC-2", "rule_id": "acc2.blocks.sample", "title": "x", "severity": "Info",
              "scope": {"urls": [SITE + "/profile/card"]}, "evidence": {"decisions": decisions}}
    checks = [{"check_id": "ACC-6", "findings": [acc6]}] + ([{"check_id": "ACC-2", "findings": [blocks]}] if acc2 else [])
    return {"checks": checks, "crawl": {"access": {"url_sample": sample}, "robots": [{"url": SITE + "/robots.txt"}]}}


def test_a_saved_audit_is_rewritten_to_the_blocked_addresses_only():
    r = _saved()
    affected = {"ACC-6-o": [SITE + "/", SITE + "/a", SITE + "/profile/card"]}
    changes: list[str] = []
    reassess_rules._decisions_370(r, affected, changes)
    f = r["checks"][0]["findings"][0]
    assert affected["ACC-6-o"] == [SITE + "/profile/card"] and f["scope"]["urls"] == [SITE + "/profile/card"]
    assert page_rows.measured(f, SITE + "/profile/card", "tr") == \
        "robots.txt 5. satır Disallow: /profile/ → bu adreste engelli: GPTBot, OAI-SearchBot"
    assert "PerplexityBot" not in f["evidence"]["pages"][0]["blocked"]  # another vendor's bot
    assert f["evidence"]["site_row"]["tr"].startswith("robots.txt 5. satır Disallow: /profile/ → 30 örnek adresten 1'i engelli")
    assert changes == ["ACC-6-o: 3 -> 1 address(es), only where robots.txt blocks GPTBot, OAI-SearchBot (DECISIONS 370)"]
    # the homepage is never said to block these bots
    assert "engel" not in page_rows.measured(f, SITE + "/", "tr", page={"status": 200}, read=True)


def test_without_the_saved_decisions_the_finding_is_said_once_on_robots_txt():
    r = _saved(acc2=False)
    affected = {"ACC-6-o": []}
    reassess_rules._decisions_370(r, affected, [])
    f = r["checks"][0]["findings"][0]
    assert affected["ACC-6-o"] == [SITE + "/robots.txt"]
    assert f["evidence"]["site_row"]["tr"] == "robots.txt → 30 örnek adresten 1'i engelli (GPTBot, OAI-SearchBot); diğer sayfalar açık"


def test_acc2_blocked_addresses_carry_their_rule_line():
    r = _saved()
    attach(r)
    acc2 = r["checks"][1]["findings"][0]
    assert page_rows.measured(acc2, SITE + "/profile/card", "tr") == \
        "robots.txt 5. satır Disallow: /profile/ → bu adreste engelli: GPTBot, OAI-SearchBot, PerplexityBot"
    assert robots_pages([{"url": SITE + "/a", "token": "GPTBot", "reason": "allowed by line 7: Allow: /a"}]) == []
