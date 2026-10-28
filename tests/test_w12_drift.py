"""DECISIONS 273: two audits of one site are compared by rule id when a title was reworded, and a problem still
reported says whether it got worse or better. Small saved-report shapes, as in test_web_app."""
from maya_audit_web import comparison

A, B, C = "https://x.example/a", "https://x.example/b", "https://x.example/c"


def report(findings, pages=(A, B, C)):
    checks = {}
    for n, (check_id, title, urls, severity, rule) in enumerate(findings):
        checks.setdefault(check_id, []).append({"id": f"{check_id}-{n}", "check_id": check_id, "title": title,
                                                "severity": severity, "rule_id": rule,
                                                "scope": {"kind": "page", "count": len(urls), "urls": urls}})
    return {"schema_version": "1.20", "findings_in_priority_order": [],
            "page_counts": {"pages_checked": len(pages), "redirects": 0}, "gates": [], "answer_engine_panel": [],
            "checks": [{"check_id": c, "title": c, "status": "findings", "summary": "", "findings": f, "coverage": {}}
                       for c, f in checks.items()],
            "crawl": {"start_url": "https://x.example/", "started_at": "t", "pages": [{"url": u, "status": 200} for u in pages],
                      "config": {"max_pages": 50}, "requests": [], "stop_reason": "exhausted"}}


def test_a_reworded_title_is_still_the_same_problem_by_its_rule_id():
    old = report([("STR-2", "The homepage's only <h1> is hidden", [A], "S2", "str2.home_hidden_h1")])
    new = report([("STR-2", "The homepage's main heading cannot be seen", [A], "S2", "str2.home_hidden_h1")])
    result = comparison.compare(new, old)
    assert [(r["matched_by"], r["trend"]) for r in result["still_reported"]] == [("rule_id", "same")]
    assert result["counts"]["new"] == result["counts"]["no_longer_reported"] == 0


def test_a_rule_held_twice_on_one_side_is_not_guessed_at():
    old = report([("STR-14", "Link to /a has no text", [A], "S4", "str14.shared"),
                  ("STR-14", "Link to /b has no text", [B], "S4", "str14.shared")])
    new = report([("STR-14", "Link to /c is empty", [C], "S4", "str14.shared")])
    result = comparison.compare(new, old)
    assert result["still_reported"] == [] and result["counts"]["no_longer_reported"] == 2 and result["counts"]["new"] == 1


def test_worse_and_better_by_severity_and_by_pages_under_the_same_conditions():
    old = report([("IDX-1", "2 URL(s) return 404", [A, B], "S3", "idx1.4xx.referenced"),
                  ("STR-1", "3 page(s) have no <title>", [A, B, C], "S3", "str1.no_title"),
                  ("STR-9", "1 page(s) declare the wrong language", [A], "S4", "str9.lang")])
    new = report([("IDX-1", "3 URL(s) return 404", [A, B, C], "S3", "idx1.4xx.referenced"),
                  ("STR-1", "1 page(s) have no <title>", [A], "S2", "str1.no_title"),
                  ("STR-9", "1 page(s) declare the wrong language", [A], "S4", "str9.lang")])
    result = comparison.compare(new, old)
    trend = {r["check_id"]: (r["trend"], r["severity_before"]) for r in result["still_reported"]}
    assert trend == {"IDX-1": ("worse", "S3"), "STR-1": ("worse", "S3"), "STR-9": ("same", "S4")}
    assert result["counts"]["worse"] == 2 and result["counts"]["better"] == 0
    back = comparison.compare(old, new)
    assert back["counts"]["better"] == 2


def test_page_counts_decide_nothing_when_the_audits_read_different_pages():
    old = report([("IDX-1", "2 URL(s) return 404", [A, B], "S3", "idx1.4xx.referenced")])
    new = report([("IDX-1", "1 URL(s) return 404", [A], "S3", "idx1.4xx.referenced")], pages=(A,))
    result = comparison.compare(new, old)
    assert not result["same_conditions"] and result["still_reported"][0]["trend"] == "same"
