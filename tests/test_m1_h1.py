"""M1 slice B: the main heading (<h1>), each state its own finding, raw HTML and rendered page kept apart (DECISIONS 281).

Hand-written pages; the expected rule for each is written from the page itself:

  /            per case below (homepage: missing, empty, hidden)
  /yok         no <h1>                         -> str2.no_h1
  /bos         <h1></h1>                       -> str2.empty_h1
  /gizli       <h1 hidden>                     -> str2.hidden_h1
  /iki         two <h1>                        -> str2.many_h1
  /tamam       one visible <h1>                -> no heading finding (counter-example)
  JS           raw HTML without <h1>, a script adds one -> str2.js_only_h1, only when the page was rendered

Offline: loopback fake server; the rendering case uses the local headless browser and skips without one.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fakeserver import FakeServer, Response, Site
from maya_audit import final
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, page

ACTIONS = json.loads((Path(__file__).resolve().parents[1] / "maya_audit" / "rule_actions.json").read_text(encoding="utf-8"))["actions"]
PAGES = ["/yok", "/bos", "/gizli", "/iki", "/tamam"]
H1_RULES = {"str2.home_no_h1", "judgment.heading.home", "judgment.heading.pages", "str2.home_hidden_h1", "str2.no_h1", "str2.empty_h1",
            "str2.hidden_h1", "str2.many_h1", "str2.js_only_h1"}


def site(home_h1: str) -> dict:
    nav = " ".join(f'<a href="{p}">{p.strip("/")}</a>' for p in PAGES)
    return {
        "/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
        "/sitemap.xml": Response(404, "", content_type="text/plain"),
        "/": page(f"{home_h1}<p>{TR}</p>{nav}", nav=""),
        "/yok": page(f"<h2>Bölüm</h2><p>{TR}</p>", nav=""),
        "/bos": page(f"<h1></h1><p>{TR}</p>", nav=""),
        "/gizli": page(f"<h1 hidden>Gizli başlık</h1><p>{TR}</p>", nav=""),
        "/iki": page(f"<h1>Birinci</h1><h1>İkinci</h1><p>{TR}</p>", nav=""),
        "/tamam": page(f"<h1>Tamam</h1><p>{TR}</p>", nav=""),
    }


def h1_findings(routes: dict, **cfg) -> tuple[dict, str]:
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "max_pages": 10, **cfg}))
    report = final.seal(outcome).report
    found = {f["rule_id"]: f for c in report["checks"] for f in c["findings"] if f.get("rule_id") in H1_RULES}
    stray = [f["title"] for c in report["checks"] if c["check_id"] == "STR-2" for f in c["findings"]
             if "<h1>" in f["title"] and f.get("rule_id") not in H1_RULES]
    assert stray == [], stray  # every heading finding has a rule id
    return found, fake.base_url


@pytest.mark.parametrize("home_h1, home_rule", [("", "str2.home_no_h1"), ("<h1></h1>", "judgment.heading.home"),
                                                ("<h1 hidden>Ana sayfa</h1>", "str2.home_hidden_h1")])
def test_each_h1_state_is_its_own_finding_at_the_right_pages(home_h1, home_rule):
    found, base = h1_findings(site(home_h1))
    expected = {home_rule: [base + "/"], "str2.no_h1": [base + "/yok"], "str2.empty_h1": [base + "/bos"],
                "str2.hidden_h1": [base + "/gizli"], "str2.many_h1": [base + "/iki"]}
    assert {rule: f["scope"]["urls"] for rule, f in found.items()} == expected
    assert base + "/tamam" not in json.dumps([f["scope"] for f in found.values()])  # the counter-example


def test_every_h1_rule_has_an_action_and_the_finding_carries_it():
    found, _ = h1_findings(site("<h1></h1>"))
    for rule, f in found.items():
        assert rule in ACTIONS, rule
        assert (f.get("remediation") or {}).get("task_id") == rule


def test_raw_and_rendered_are_kept_apart_when_nothing_was_rendered():
    found, base = h1_findings(site(""))
    rows = {r["url"]: r for f in found.values() for r in f["evidence"]["h1_sources"]}
    assert rows[base + "/yok"] == {"url": base + "/yok", "raw_h1": [], "rendered_h1": None}  # None: not rendered, unknown
    assert rows[base + "/iki"]["raw_h1"] == ["Birinci", "İkinci"]
    assert "str2.js_only_h1" not in found  # never claimed without a rendered page


def test_idx6_broken_has_an_action():
    assert ACTIONS["idx6.broken"]["en"] and ACTIONS["idx6.broken"]["tr"]


# ------------------------------------------------------------------ raw HTML vs the rendered page

RENDER = {"render_enabled": True, "render_budget": 2, "render_timeout_s": 6, "render_settle_ms": 200,
          "render_control_wait_ms": 0, "render_interactions": False}
SCRIPTED = "<script>document.querySelector('main').insertAdjacentHTML('afterbegin', '<h1>Betikle gelen başlık</h1>')</script>"


def browser_or_skip():
    from test_rnd_scenarios import _browser_available
    reason = _browser_available()
    if reason:
        pytest.skip(f"needs the local headless browser: {reason}")


def test_an_h1_only_a_script_adds_is_its_own_finding_with_both_sources():
    browser_or_skip()
    routes = site("")
    routes["/"] = page(f"<p>{TR}</p>" + " ".join(f'<a href="{p}">{p}</a>' for p in PAGES) + SCRIPTED, nav="")
    found, base = h1_findings(routes, **RENDER)
    js = found["str2.js_only_h1"]
    assert js["scope"]["urls"] == [base + "/"] and js["severity"] == "S4"
    [row] = [r for r in js["evidence"]["h1_sources"] if r["url"] == base + "/"]
    assert row["raw_h1"] == [] and row["rendered_h1"] == ["Betikle gelen başlık"]
    assert "str2.home_no_h1" not in found  # the browser saw one: "no <h1>" would be wrong


def test_a_page_whose_raw_html_has_the_h1_is_not_js_only_when_rendered():
    browser_or_skip()
    found, base = h1_findings(site("<h1>Ana sayfa</h1>"), **RENDER)
    assert "str2.js_only_h1" not in found
    rows = {r["url"]: r for f in found.values() for r in f["evidence"]["h1_sources"]}
    assert base + "/" not in rows  # a healthy homepage is in no heading finding
