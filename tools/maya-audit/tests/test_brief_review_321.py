"""DECISIONS 321: fixes from reviewing the client briefs. A certificate's expiry date and days left everywhere and its
severity by the days left; host-level cards name hosts; the brief's coverage line; the owner of merged cards; XLSX
sheets that are never silently empty. Hand-made reports only; nothing is requested."""
from __future__ import annotations

import json

import pytest

from maya_audit import client_appendix, client_selection as cs, xlsx
from maya_audit.checks.index import expiry_finding, expiry_severity
from maya_audit.config import CrawlConfig
from maya_audit.findings import Severity
from maya_audit.reassess_rules import saved_data
from maya_audit_web.team_report import brief, texts
from test_client_brief_319 import _card, _data
from test_team_report import SITE, built, synthetic

HOST = SITE.split("//")[1]


# ---------------------------------------------------------------- 1: the certificate

# DECISIONS 322 made the bands inclusive: 7 days or fewer Blocker, 14 or fewer High, 30 or fewer Medium.
@pytest.mark.parametrize("days,want", [(0.5, "S1"), (6.9, "S1"), (7, "S1"), (7.1, "S2"), (9.1, "S2"), (13.9, "S2"), (14, "S2"),
                                       (14.1, "S3"), (29.9, "S3"), (30, "S3")])
def test_certificate_severity_by_days_left(days, want):
    assert expiry_severity(days).value == want


def test_the_warning_window_is_thirty_days():
    assert CrawlConfig.tls_expiry_warning_days == 30.0


def _tls(host, days, not_after="2026-11-10T23:42:31+00:00"):
    return {"host": host, "port": 443, "valid": True, "not_after": not_after, "days_left": days,
            "issuer": {"organizationName": "GlobalSign nv-sa"}}


def _cert_report(days=9.1, *, finding=True, severity="S3", not_after="2026-11-10T23:42:31+00:00"):
    """A saved report: crawl on 1 Nov 2026, a certificate on both hosts expiring on 10 Nov (9 days)."""
    report = synthetic([("STR-2", "str2.no_h1")], "S4")
    hosts = [{"host": HOST, "role": "start", "tls": _tls(HOST, days, not_after)},
             {"host": "www." + HOST, "role": "variant", "tls": _tls("www." + HOST, days, not_after)}]
    check = {"check_id": "IDX-2", "status": "findings" if finding else "pass", "evidence": {"hosts": hosts}, "findings": []}
    if finding:
        f = {k: (v.value if isinstance(v, Severity) else v) for k, v in vars(expiry_finding(not_after, hosts, 14)).items()}
        f["severity"], f["confidence"] = severity, "verified"
        f["expected"] = "more than 14 days of validity left"
        f["evidence"] = {"hosts": [h["tls"] for h in hosts]}
        check["findings"] = [json.loads(json.dumps(f, default=str))]
    report["checks"].append(check)
    report["findings_in_priority_order"] = [f["id"] for c in report["checks"] for f in c["findings"]]
    report["crawl"]["config"] = {"max_pages": 1}
    return report


def test_a_saved_certificate_under_14_days_becomes_high_with_a_retest_state():
    new, changes = saved_data(_cert_report(), {})
    [f] = next(c for c in new["checks"] if c["check_id"] == "IDX-2")["findings"]
    assert f["severity"] == "S2" and f["verification"]["state"] == "not_retested"
    assert f["expected"] == "more than 30 days of validity left"
    assert any("S3 -> S2 (DECISIONS 321)" in c for c in changes)
    assert "RG-5" not in json.dumps(new["release_gate"])


def test_a_current_schema_report_gets_the_rule_too():
    copy_, changes = saved_data(_cert_report(days=5.0), {})
    [f] = next(c for c in copy_["checks"] if c["check_id"] == "IDX-2")["findings"]
    assert f["severity"] == "S1" and changes
    assert copy_["findings_in_priority_order"][0] == f["id"]


@pytest.mark.parametrize("days,made", [(20.0, True), (30.0, True), (30.1, False), (45.0, False)])  # 30 inclusive (322)
def test_a_saved_certificate_inside_the_new_window_gets_its_finding(days, made):
    new, _changes = saved_data(_cert_report(days=days, finding=False), {})
    found = next(c for c in new["checks"] if c["check_id"] == "IDX-2")["findings"]
    assert bool(found) is made
    if made:
        assert found[0]["severity"] == "S3" and found[0]["rule_id"] == "idx2.expires"


CERT = {"en": ("Expires 10 November 2026; 9 days left at the audit (1 November 2026).", f"Hosts: {HOST}, www.{HOST}"),
        "tr": ("Bitiş tarihi: 10 Kasım 2026; denetim tarihinde (1 Kasım 2026) 9 gün kalmıştı.", f"Alan adları: {HOST}, www.{HOST}")}


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_certificate_card_and_evidence_table_show_the_date_and_days(tmp_path, lang):
    data = built(tmp_path, _cert_report(), lang)
    card = next(t for t in data["todos"] if any(i.startswith("IDX-2") for i in t["finding_ids"]))
    assert card["severity"] == "S2"
    assert card["sub"][0] == CERT[lang][0] and card["certificate_line"] == CERT[lang][0]
    assert card["hosts_line"] == CERT[lang][1] and CERT[lang][1] in card["sub"]
    assert not any("öncelik puanına" in s or "priority score" in s for s in card["sub"])  # no "not read" line
    row = next(f for f in data["findings"] if f["id"].startswith("IDX-2"))
    assert row["scope"] == ("2 hosts" if lang == "en" else "2 alan adı")
    sample = data["evidence_sample"]
    if sample["finding_id"].startswith("IDX-2"):
        assert sample["rows"] and sample["rows"][0][:3] == [HOST, "10 " + ("November" if lang == "en" else "Kasım") + " 2026",
                                                            "9 days" if lang == "en" else "9 gün"]


def test_the_web_results_carry_the_certificate_and_hosts_lines():
    from pathlib import Path
    import maya_audit_web
    root = Path(maya_audit_web.__file__).parent
    assert '"certificate_line": todo.get("certificate_line")' in (root / "app.py").read_text(encoding="utf-8")
    assert "f.certificate_line" in (root / "static" / "app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_brief_says_the_expiry_date_and_days_and_never_nothing_urgent(tmp_path, lang):
    report = _cert_report()
    new, _changes = saved_data(report, {})
    f = next(c for c in new["checks"] if c["check_id"] == "IDX-2")["findings"][0]
    data = _data([{**_card(1, "idx2.expires", severity="S2"), "finding_ids": [f["id"]]}])
    [p] = brief.problems(data, new, lang)
    assert ("10 November 2026" in p["what"] and "9 days" in p["what"]) if lang == "en" else \
        ("10 Kasım 2026" in p["what"] and "9 gün" in p["what"])
    b = brief.compose(data, new, lang)
    urgent = {"en": "Nothing is urgent", "tr": "Acil bir sorun yok"}[lang]
    assert not any(urgent.lower() in h.lower() or "acil ya da" in h.lower() for h in b["health"]), b["health"]
    assert brief.check(b) == []


@pytest.mark.parametrize("lang", texts.LANGS)
def test_a_high_card_outside_the_brief_or_a_near_certificate_stops_the_calm_sentence(lang):
    calm = {"en": "Nothing is urgent", "tr": "Acil"}[lang]
    cards = [_card(1, "str2.no_h1"), _card(2, "str7.placeholder", severity="S2", issue_type="warning")]
    report = {"checks": [], "audit_status": {"content_coverage": {"pages_read": 40}}, "crawl": {}}
    b = brief.compose(_data(cards), report, lang)
    assert not b["health"][1].startswith(calm) and b["verdict"] == brief.fmt(brief.library(lang)["verdict"]["S2"], brand="Shop")
    # A certificate with 10 days left, even if its card said Medium.
    cert = _cert_report(days=10.0)
    only = brief.compose(_data([_card(1, "str2.no_h1")]), {**cert, "audit_status": report["audit_status"]}, lang)
    assert not only["health"][1].startswith(calm)
    # Nothing High anywhere: the calm sentence is allowed.
    plain = brief.compose(_data([_card(1, "str2.no_h1")]), report, lang)
    assert plain["health"][1] == brief.library(lang)["health"]["S3"]


# ---------------------------------------------------------------- 2: host-level findings

@pytest.mark.parametrize("finding,hosts", [
    ({"check_id": "IDX-2", "scope": {"urls": ["https://a.com/", "https://www.a.com/"]}}, ["a.com", "www.a.com"]),
    ({"check_id": "ACC-1", "scope": {"urls": ["https://a.com/robots.txt"]}}, ["a.com"]),
    ({"check_id": "IDX-5", "scope": {"urls": ["https://a.com/sitemap_products_1.xml?from=1"]}}, ["a.com"]),
    ({"check_id": "IDX-5", "scope": {"urls": ["https://a.com/products/x"]}}, None),
    ({"check_id": "RND-6", "scope": {"urls": ["https://a.com/"]}}, None),
])
def test_host_level_findings_are_told_apart_from_page_findings(finding, hosts):
    assert cs.host_level(finding) == hosts


# ---------------------------------------------------------------- 3: the brief's coverage line

def _cov(stop="page_cap", read=13, planned=50, acc9=False, reasons=()):
    checks = [{"check_id": "ACC-9", "findings": [{"id": "ACC-9-1", "rule_id": "acc9.bot_protection"}]}] if acc9 else []
    return {"checks": checks, "crawl": {"stop_reason": stop, "config": {"max_pages": planned}},
            "audit_status": {"content_coverage": {"pages_read": read, "reasons": list(reasons)}}}


@pytest.mark.parametrize("lang", texts.LANGS)
@pytest.mark.parametrize("kind,report", [("protection", _cov(acc9=True)), ("protection", _cov(stop="rate_limit")),
                                         ("time", _cov(stop="time_limit")), ("small", _cov(stop="exhausted")),
                                         ("other", _cov())])
def test_fewer_pages_than_planned_get_one_plain_line_with_why(lang, kind, report):
    line = brief.coverage_line(report, 13, lang)
    assert line == brief.fmt(brief.library(lang)["labels"]["coverage"][kind], read="13", planned="50")
    assert "13" in line and "50" in line


def test_no_coverage_line_when_the_plan_was_read():
    assert brief.coverage_line(_cov(read=50), 50, "en") is None
    assert brief.coverage_line({"crawl": {}}, 3, "en") is None


@pytest.mark.parametrize("lang", texts.LANGS)
def test_the_coverage_line_is_on_page_one_and_passes_the_gate(lang):
    report = _cov(acc9=True)
    b = brief.compose(_data([_card(1, "str2.no_h1")]), report, lang)
    assert b["health"][0] == brief.coverage_line(report, 13, lang)
    assert brief.check(b) == []


# ---------------------------------------------------------------- 4: the owner of merged cards

@pytest.mark.parametrize("lang", texts.LANGS)
def test_canonical_and_redirect_chain_card_is_developer_plus_seo(tmp_path, lang):
    report = synthetic([("IDX-4", "idx4.chain"), ("IDX-3", "idx3.chain")], "S2")
    a, b_ = report["checks"][0]["findings"][0], report["checks"][1]["findings"][0]
    a["title"] = "Canonical points at an address that redirects: /tr/ -> /tr/tr/"
    b_["title"] = "Redirect chain: /tr/tr/ -> / -> /tr/"
    b_["scope"]["urls"] = a["scope"]["urls"]
    data = built(tmp_path, report, lang)
    owners = [t["owner"] for t in data["todos"]]
    L = json.loads((__import__("pathlib").Path(texts.__file__).parent / "refs" / "etiketler.json").read_text(encoding="utf-8"))[lang]
    dev = L["owners"]["developer"]
    assert all(o.startswith(dev) for o in owners), owners


@pytest.mark.parametrize("lang,want", [("en", "Developer + SEO / marketing team"), ("tr", "Geliştirici + SEO / pazarlama ekibi")])
def test_the_brief_says_both_owners_of_a_merged_card(lang, want):
    data = _data([_card(1, "str2.no_h1")])
    data["todos"][0]["owner"] = "Developer + SEO" if lang == "en" else "Geliştirici + SEO"
    [p] = brief.problems(data, {"checks": [], "audit_status": {"content_coverage": {"pages_read": 40}}}, lang)
    assert p["who"] == want and p["owner"] == "developer"


def test_every_merge_group_gets_its_most_technical_owner():
    from maya_audit_web.team_report import build_data
    builder_cls = next(v for v in vars(build_data).values() if isinstance(v, type) and hasattr(v, "card_owner"))
    rank = builder_cls.OWNER_RANK
    labels = {"developer": "D", "seo": "S", "content": "C"}

    class Fake:
        OWNER_RANK = rank
        L = {"owners": labels}

        def owner_effort(self, f):
            return f["owner"], "S"
    card_owner = builder_cls.card_owner
    for group in (*cs.MERGE_GROUPS, cs.CHAIN_GROUP):
        for owners in (["content", "developer"], ["seo", "developer"], ["content", "seo"], ["seo"], ["content", "content"]):
            members = [{"owner": o, "rule_id": r} for o, r in zip(owners, group["rules"] * 2)]
            got = card_owner(Fake(), members)
            first = min(owners, key=rank.index)
            assert got.split(" + ")[0] == labels[first], (group["id"], owners, got)
            assert len(got.split(" + ")) == min(2, len(set(owners)))


# ---------------------------------------------------------------- 5: the XLSX never has a silently empty sheet

def _selection(**over):
    sel = {"key_pages": [], "key_pages_reason": "no_pages", "templates": [], "templates_reason": "no_template",
           "coverage": {"lines": []}}
    sel.update(over)
    return sel


@pytest.mark.parametrize("lang", ("tr", "en"))
@pytest.mark.parametrize("reason", ["reader_only", "no_pages", "not_read", "no_template"])
def test_an_empty_sheet_says_why_in_one_line(monkeypatch, lang, reason):
    monkeypatch.setattr(client_appendix, "appendix_rows", lambda selection, lists: [])
    out = {s["name"]: s for s in client_appendix.sheets(_selection(templates_reason=reason), lang)}
    W = client_appendix.WORDS[lang]
    assert out[W["coverage"]]["rows"][0][0] in ("Sürüm", "Version")  # DECISIONS 373: the engine, commit and build time
    assert out[W["coverage"]]["rows"][1][0] == "Platform"  # DECISIONS 365: Kapsam always names the platform
    for name in (W["findings"], W["urls"], W["templates"], W["key_pages"]):
        assert out[name]["rows"] and len(out[name]["rows"]) == 1 and out[name]["header"] == [W["note"]], name
    assert out[W["templates"]]["rows"][0][0] == W["empty"]["templates"][reason]
    # RG-17 reads the first sheet's ids: a note line is not an id.
    assert client_appendix.finding_ids(xlsx.workbook(list(out.values())), lang) == set()


def test_templates_reason_says_why_the_table_is_empty():
    assert cs.templates_reason({}, {"crawl": {"pages": []}}) == "no_pages"
    blocked = {"https://a/x/1": {"template_key": "/x/*", "read": False}, "https://a/x/2": {"template_key": "/x/*", "read": False}}
    assert cs.templates_reason(blocked, {}) == "not_read"
    assert cs.templates_reason({"https://a/": {"template_key": None}}, {}) == "no_template"
    assert cs.templates_reason({"https://a/x/1": {"template_key": "/x/*", "read": True}}, {}) is None


@pytest.mark.parametrize("lang", ("tr", "en"))
def test_importance_not_computed_says_why_in_plain_words(lang):
    W = client_appendix.WORDS[lang]
    assert "page reader" not in W["importance_reader"] and "sayfa okuyucu" not in W["importance_reader"]
    assert ("blocked" in W["importance_reader"]) if lang == "en" else ("engellendi" in W["importance_reader"])
