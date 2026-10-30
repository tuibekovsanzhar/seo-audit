"""The release gate (DECISIONS 278): one place that checks a report, its cards and its validation note agree.

Every report here is made up (example.test); the gate must decide the same way for any site.
"""
from maya_audit import release_gate as gate

SITE = "https://shop.example.test"


def finding(fid, rule, severity="S2", urls=("/a",), evidence=None, **extra):
    f = {"id": fid, "check_id": rule.split(".")[0].upper().replace("IDX1", "IDX-1"), "rule_id": rule,
         "severity": severity, "title": f"{rule} title", "scope": {"kind": "page", "count": len(urls),
                                                                   "urls": [SITE + u for u in urls]},
         "evidence": {"pages": [{"url": SITE + u} for u in urls]} if evidence is None else evidence,
         "verification": {"state": "not_retested", "reason": "no re-test for this rule"}}
    f.update(extra)
    return f


def report(*findings, coverage=None):
    return {"checks": [{"check_id": "X-1", "findings": list(findings), "coverage": coverage or {}}],
            "answer_engine_panel": []}


def card(n_ids, urls=(), **extra):
    c = {"finding_ids": n_ids, "all_urls": [SITE + u for u in urls], "links": [{"href": SITE + u} for u in urls[:4]],
         "title": "Fix it", "steps": "Do one thing\nDo another", "verify": "It is fixed.", "fact": "",
         "known_paths": [], "verification_state": "not_retested"}
    c.update(extra)
    return c


def rules(violations):
    return sorted({v["rule"] for v in violations})


def test_high_finding_without_evidence_is_not_ready():
    r = report(finding("F1", "idx4.redirect_loop", evidence={"severity_assessment": {}, "judgment": {}}))
    record = gate.run(r)
    assert "RG-2" in rules(record["violations"]) and record["decision"] == gate.BLOCKED
    assert "F1 is S2 but has no evidence" in record["violations"][0]["message"]


def test_a_medium_finding_without_evidence_is_not_this_rule():
    r = report(finding("F1", "x.medium", severity="S3", evidence={}))
    assert "RG-2" not in rules(gate.check_report(r))


def test_high_finding_without_verification_state_blocks():
    f = finding("F1", "idx4.redirect_loop")
    f["verification"] = None
    assert "RG-5" in rules(gate.check_report(report(f)))


def test_card_urls_are_the_findings_urls():
    r = report(finding("F1", "x.rule", urls=("/a", "/b")))
    ok = gate.check_cards({"todos": [card(["F1"], ("/a", "/b"))]}, r)
    assert ok == []
    bad = gate.check_cards({"todos": [card(["F1"], ("/a", "/x"))]}, r)
    assert rules(bad) == ["RG-3"] and "/x" in bad[0]["message"]


def test_card_text_cannot_name_an_address_the_card_does_not_hold():
    r = report(finding("F1", "x.rule", urls=("/a",)))
    bad = gate.check_cards({"todos": [card(["F1"], ("/a",), steps="Open /a\nThen fix /elsewhere")]}, r)
    assert rules(bad) == ["RG-3"] and "/elsewhere" in bad[0]["message"]


def test_a_card_must_name_its_findings():
    r = report(finding("F1", "x.rule"))
    assert rules(gate.check_cards({"todos": [card([], ("/a",))]}, r)) == ["RG-1"]
    assert rules(gate.check_cards({"todos": [card(["NOPE"], ())]}, r)) == ["RG-1"]


def test_confirmed_only_for_the_addresses_the_finding_is_about():
    f = finding("F1", "idx1.4xx.referenced", urls=("/source",),
                verification={"state": "confirmed", "checked": [{"url": SITE + "/404?from=x", "outcome": "confirmed"}]})
    assert "RG-4" in rules(gate.check_report(report(f)))
    f["verification"]["checked"] = [{"url": SITE + "/source", "outcome": "confirmed"}]
    assert "RG-4" not in rules(gate.check_report(report(f)))


def test_a_card_cannot_say_confirmed_for_an_unconfirmed_finding():
    r = report(finding("F1", "x.rule"))
    bad = gate.check_cards({"todos": [card(["F1"], ("/a",), verification_state="confirmed")]}, r)
    assert "RG-4" in rules(bad)


def test_a_high_card_must_show_its_retest_state():
    r = report(finding("F1", "x.rule"))
    bad = gate.check_cards({"todos": [card(["F1"], ("/a",), verification_state=None)]}, r)
    assert "RG-5" in rules(bad)


def test_cross_card_reference_needs_shared_evidence():
    r = report(finding("F1", "x.one", urls=("/a",)), finding("F2", "x.two", urls=("/b",)))
    cards = [card(["F1"], ("/a",), steps="Fix the links\nThe rest is fixed with the 2. iş"),
             card(["F2"], ("/b",))]
    bad = gate.check_cards({"todos": cards}, r)
    assert rules(bad) == ["RG-6"] and bad[0]["card"] == 1
    cards[1]["all_urls"].append(SITE + "/a")
    cards[1]["links"].append({"href": SITE + "/a"})
    r["checks"][0]["findings"][1]["scope"]["urls"].append(SITE + "/a")
    assert gate.check_cards({"todos": cards}, r) == []


def test_sitemap_step_only_when_listed_in_sitemap():
    ev = {"pages": [{"url": SITE + "/a", "in_sitemap": False}]}
    r = report(finding("F1", "idx1.4xx.referenced", evidence=ev))
    step = {"text": "Take the addresses out of the sitemap", "when": {"evidence_any": "pages[].in_sitemap"}, "shown": True}
    bad = gate.check_cards({"todos": [card(["F1"], ("/a",), step_rules=[step])]}, r)
    assert rules(bad) == ["RG-11"]
    ev["pages"][0]["in_sitemap"] = True
    assert gate.check_cards({"todos": [card(["F1"], ("/a",), step_rules=[step])]}, r) == []


def test_note_title_topic_needs_a_finding():
    r = report(finding("F1", "x.rule", severity="Info"))
    good = card(["F1"], ("/a",), topics=[{"topic": "question headings", "ids": ["F1"]}], verification_state=None)
    bad = card(["F1"], ("/a",), topics=[{"topic": "menu language", "ids": []}], verification_state=None)
    assert gate.check_cards({"todos": [good]}, r) == []
    out = gate.check_cards({"todos": [bad]}, r)
    assert rules(out) == ["RG-11"] and "menu language" in out[0]["message"]


def test_content_advice_only_for_allowed_page_types():
    advice = {"task_id": "str3.expected_type", "content": True, "page_types": ["article", "blog"]}
    f = finding("F1", "str3.expected_type", severity="Info", urls=("/blog/2", "/blog/post"), remediation=advice,
                page_types={SITE + "/blog/2": "pagination", SITE + "/blog/post": "article"})
    out = gate.check_report(report(f))
    assert rules(out) == ["RG-7"] and "pagination" in out[0]["message"]


def test_unknown_page_type_gets_no_content_advice():
    advice = {"task_id": "str3.expected_type", "content": True, "page_types": ["article"]}
    f = finding("F1", "str3.expected_type", severity="Info", urls=("/x",), remediation=advice, page_types={})
    out = gate.check_report(report(f))
    assert rules(out) == ["RG-7"] and "page type unknown; no content advice" in out[0]["message"]


def test_one_finding_does_not_mix_absent_and_empty():
    f = finding("F1", "str2.h1", severity="S4", measurement={"claims": [
        {"element": "<h1>", "state": "absent", "urls": [SITE + "/a"]},
        {"element": "<h1>", "state": "empty", "urls": [SITE + "/b"]}]})
    assert rules(gate.check_report(report(f))) == ["RG-8"]


def test_one_element_on_one_page_is_one_finding():
    a = finding("F1", "str10.no_tag", severity="Info",
                measurement={"claims": [{"element": "og:title", "state": "absent", "urls": [SITE + "/a"]}]})
    b = finding("F2", "tseo1.head_closed_later", severity="S3",
                measurement={"claims": [{"element": "og:title", "state": "after_head", "urls": [SITE + "/a"]}]})
    out = gate.check_report(report(a, b))
    assert rules(out) == ["RG-9"] and "F1 and F2" in out[0]["message"]


def test_same_dedup_key_and_same_pages_is_a_double_count():
    a = finding("F1", "x.one", severity="S3", urls=("/a", "/b"), dedup_key="lang:html")
    b = finding("F2", "x.two", severity="S4", urls=("/a", "/b", "/c"), dedup_key="lang:html")
    assert rules(gate.check_report(report(a, b))) == ["RG-9"]


def test_absent_where_not_measured_is_a_silent_gap():
    f = finding("F1", "str10.no_tag", severity="Info",
                measurement={"claims": [{"element": "canonical", "state": "absent", "urls": [SITE + "/a"]}]})
    cov = {"not_assessed": [{"part": "canonical after an early-closed head", "element": "canonical", "count": 1,
                             "urls": [SITE + "/a"], "reason": "the head ended before the canonical"}]}
    assert rules(gate.check_report(report(f, coverage=cov))) == ["RG-10"]


def test_a_gap_without_count_or_reason_is_silent():
    cov = {"not_assessed": [{"part": "something"}]}
    assert rules(gate.check_report(report(coverage=cov))) == ["RG-10"]


def test_cut_off_card_text_is_flagged_soft():
    r = report(finding("F1", "x.rule", severity="S4"))
    out = gate.check_cards({"todos": [card(["F1"], ("/a",), fact="/a · 404 · +", verification_state=None)]}, r)
    assert rules(out) == ["RG-13"] and not out[0]["hard"]
    assert gate.decision(out) == gate.CONDITIONAL


def test_counts_only_matched_and_retested_items():
    kept = finding("F1", "idx1.4xx.referenced", urls=("/src",),
                   verification={"state": "confirmed", "subjects": [SITE + "/src"], "checked": []})
    other = finding("F2", "idx5.sitemap", severity="S3", urls=("/listed",))
    items = [{"label": "broken links", "rule_id": "idx1.4xx.referenced", "urls": ["/src"]},
             {"label": "sitemap to 404", "rule_id": "idx1.4xx.referenced", "urls": ["/listed"]},
             {"label": "sitemap review", "rule_id": "idx5.sitemap", "urls": ["/listed"], "manual_notes": "seen live"},
             {"label": "old false alarm", "rule_id": "str12.language", "urls": ["/x"], "expected": "closed"}]
    out = gate.checklist(items, report(kept, other))
    assert [r["result"] for r in out["rows"]] == ["kept_and_retested", "unmatched", "matched_not_retested", "closed"]
    assert out["counts"]["kept_and_retested"] == 1 and out["counts"]["items"] == 4
    assert out["rows"][1]["finding_id"] is None  # same rule, no shared address: never matched by name
    assert out["rows"][2]["manual_notes"] == "seen live" and out["rows"][2]["finding_id"] == "F2"


def test_gate_runs_on_an_unknown_brand_report_shape():
    """A report of a site the gate has never seen: no exception, every rule answers from the contract alone."""
    weird = {"checks": [{"check_id": "STR-2", "coverage": {}, "findings": [
                {"id": "Q", "severity": "S2", "scope": {}, "evidence": {"x": 1}},
                {"id": "R", "severity": "Info"}]},
             {"check_id": "ACC-1"}], "answer_engine_panel": None}
    record = gate.run(weird, affected={"Q": ["https://unknown-brand.test/"]}, data={"todos": [{"finding_ids": ["Q"]}]})
    assert record["decision"] == gate.BLOCKED
    assert rules(record["violations"]) == ["RG-5"] and record["high_not_retested"] == ["Q"]
    assert "Decision: BLOCKED" in gate.summary_table(record)


def test_the_gate_holds_no_brand_or_site_specific_text():
    import inspect
    source = inspect.getsource(gate).casefold()
    for word in ("enpara", "carpex", "arjava", "adile", "enparaliol", "bluelight", "menü dili", "menu language"):
        assert word not in source


def test_a_clean_report_passes():
    f = finding("F1", "x.rule", verification={"state": "confirmed", "checked": [{"url": SITE + "/a"}]})
    r = report(f)
    record = gate.run(r, data={"todos": [card(["F1"], ("/a",), verification_state="confirmed")]})
    assert record["decision"] == gate.PASS and record["violations"] == []


def test_card_urls_may_come_from_the_scope_and_the_companion_list():
    """Seen on a saved report: a card holds scope.urls and affected-urls.json together; both are the finding's own."""
    f = finding("F1", "x.rule", urls=("/a",))
    out = gate.check_cards({"todos": [card(["F1"], ("/a", "/b"))]}, report(f), affected={"F1": [SITE + "/b"]})
    assert out == []


def test_a_note_card_from_observations_may_show_the_checks_observed_addresses():
    r = report(finding("F1", "acc8.redirecting", severity="Info", urls=("/llms",)))
    r["checks"].append({"check_id": "IDX-3", "findings": [], "observations": [
        {"metric": "internal links pointing at redirecting URLs", "sample": [{"source": SITE + "/a", "target": SITE + "/old"}]}]})
    ok = card(["F1", "IDX-3"], ("/llms", "/a"), verification_state=None)
    assert gate.check_cards({"todos": [ok]}, r) == []
    bad = card(["F1", "IDX-3"], ("/llms", "/nowhere"), verification_state=None)
    assert rules(gate.check_cards({"todos": [bad]}, r)) == ["RG-3"]
