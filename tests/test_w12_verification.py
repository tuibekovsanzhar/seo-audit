"""DECISIONS 272: the audit asks its most serious findings again before the report is written, records what the second
look saw, and never changes a severity. Offline fake site; `verification.run` directly, then once through the audit."""
from dataclasses import replace
from types import SimpleNamespace as NS

from fakeserver import FakeServer, Response, Site
from maya_audit import verification
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from maya_audit.findings import Confidence, Finding, Severity
from maya_audit.robots import policy_from_response
from test_deadline_hosted_hardening import QUIET

ROBOTS = "User-agent: *\nAllow: /\nDisallow: /private\n"
BROKEN_ORG = ('<script type="application/ld+json">{"@type":"Organization","name":"Ev",'
              '"address":"Sokak\r\nNo 4"}</script>')
PAGE = "<html><head><title>Ev</title>{head}</head><body><h1>Ev</h1><p>{text}</p></body></html>"


def flips(first: Response, then: Response):
    def route(site, request):
        site.state[request.path] = site.state.get(request.path, 0) + 1
        return first if site.state[request.path] == 1 else then
    return route


def site():
    return Site({"/robots.txt": Response(body=ROBOTS, content_type="text/plain"),
                 "/gone": Response(404, "<html><title>Yok</title></html>"),
                 "/back": Response(200, PAGE.format(head="", text="Geri geldi.")),
                 "/moved-error": Response(500, "<html><title>Hata</title></html>"),
                 "/private/gone": Response(404, "<html><title>Yok</title></html>"),
                 "/empty": Response(200, ""),
                 "/": Response(200, PAGE.format(head=BROKEN_ORG, text="Ana sayfa."))})


def finding(rule, urls, severity=Severity.S2, launch_gated=(), pages=None):
    return Finding("IDX-1", f"test {rule}", severity, Confidence.VERIFIED, "r", [], {"kind": "page", "urls": urls},
                   {"pages": pages or [{"url": u, "status": 404} for u in urls]}, "e", "h",
                   launch_gated=list(launch_gated), rule_id=rule)


def run(findings, **cfg):
    with FakeServer(site()) as fake:
        base = fake.base_url
        for f in findings:
            f.scope["urls"] = [u.replace("{base}", base) for u in f.scope["urls"]]
            for p in f.evidence["pages"]:
                p["url"] = p["url"].replace("{base}", base)
        policy = policy_from_response(base + "/robots.txt", 200, None, ROBOTS.encode(), 100_000, [])
        result = NS(origin=base, robots_policy_by_origin={base: policy}, stop_reason=None, stopped=False)
        config = replace(CrawlConfig(), **{**QUIET, **cfg})
        summary = verification.run([NS(findings=findings)], result, config)
        return summary, fake


def test_a_client_error_that_still_answers_404_is_confirmed_and_one_that_now_opens_is_not_reproduced():
    still, back = finding("idx1.4xx.referenced", ["{base}/gone"]), finding("idx1.4xx.referenced", ["{base}/back"])
    summary, _ = run([still, back])
    assert still.verification["state"] == "confirmed" and still.verification["checked"][0]["status"] == 404
    assert back.verification["state"] == "not_reproduced"
    # Never a different severity, whatever the second look saw.
    assert still.severity == back.severity == Severity.S2
    assert summary["requests"] == 2 and summary["states"] == {"confirmed": 1, "not_reproduced": 1}


def test_some_addresses_reproducing_and_others_not_is_changed():
    mixed = finding("idx1.4xx.referenced.linked", ["{base}/gone", "{base}/back"])
    other = finding("idx1.4xx.referenced", ["{base}/moved-error"])
    run([mixed, other])
    assert mixed.verification["state"] == "changed"
    assert other.verification["state"] == "changed"  # a 404 that now answers 500 is another problem


def test_robots_disallow_sends_nothing_and_says_why():
    hidden = finding("idx1.4xx.referenced", ["{base}/private/gone"])
    summary, fake = run([hidden])
    assert hidden.verification == {"state": "not_retested", "checked": [], "subjects": hidden.scope["urls"],
                                   "reason": "robots.txt disallows Maya's user agent"}
    assert summary["requests"] == 0
    assert not any(r.path.startswith("/private") for r in fake.requests)


def test_the_request_cap_and_the_url_sample_hold():
    many = [finding("idx1.4xx.referenced", ["{base}/gone", "{base}/back", "{base}/moved-error"]) for _ in range(3)]
    summary, fake = run(many, verification_max_requests=4, verification_urls_per_finding=2)
    assert summary["requests"] == 4
    assert [len(f.verification["checked"]) for f in many] == [2, 2, 0]
    assert many[2].verification["reason"] == "the re-test's request cap (4) was reached"


def test_switched_off_sends_no_request_and_writes_nothing():
    f = finding("idx1.4xx.referenced", ["{base}/gone"])
    summary, fake = run([f], verification_enabled=False)
    # DECISIONS 278: a High finding still says it was not re-tested, and why; nothing is sent.
    assert f.verification["state"] == "not_retested" and f.verification["reason"].startswith("switched off")
    assert summary["requests"] == 0 and summary["reason"].startswith("switched off")
    assert not fake.requests


def test_only_severe_or_gated_medium_findings_with_a_retest_are_in_scope():
    low = finding("idx1.4xx.referenced", ["{base}/gone"], severity=Severity.S3)
    gated = finding("idx1.4xx.referenced", ["{base}/gone"], severity=Severity.S3, launch_gated=["LG-1"])
    unknown = finding("str1.no_title", ["{base}/gone"])
    run([low, gated, unknown])
    assert low.verification is None  # Medium, no unverified check: no state needed
    # High with no re-test for its rule: says so (DECISIONS 278)
    assert unknown.verification == {"state": "not_retested", "checked": [], "reason": "no re-test for this rule",
                                    "subjects": unknown.scope["urls"]}
    assert gated.verification["state"] == "confirmed"


def test_empty_page_and_broken_organization_are_asked_again():
    empty = finding("judgment.empty.repeated", ["{base}/empty"], pages=[{"url": "{base}/empty", "status": 200}])
    org = finding("str3.organization_broken", ["{base}/"], pages=[{"url": "{base}/"}])
    run([empty, org], probes_enabled=True)
    assert empty.verification["state"] == "confirmed"
    # A browser's answer is recorded beside an empty page, never deciding it.
    assert empty.verification["second_client"]["client"] == "browser"
    assert org.verification["state"] == "confirmed" and "second_client" not in org.verification


def test_the_audit_records_the_second_look_on_its_findings():
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": Response(200, PAGE.format(head=BROKEN_ORG, text="Ana sayfa " * 80))}
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **QUIET))
    [org] = [f for c in outcome.checks for f in c.findings if f.rule_id == "str3.organization_broken"]
    assert org.verification["state"] == "confirmed" and org.severity == Severity.S2
    assert outcome.result.verification["requests"] >= 1


def test_an_empty_page_is_asked_again_under_the_name_it_has_while_the_audit_runs():
    # Seen live (Adile, 27 Oct): the empty-page finding is `idx1.empty` until the report's judgments rename it, so a
    # table keyed only by the later name never re-tested it.
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": Response(200, PAGE.format(head="", text="Ana sayfa " * 80 + '<a href="/bos">b</a>')),
              "/bos": Response(200, "")}
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **{**QUIET, "probes_enabled": True}))
    empty = [f for c in outcome.checks for f in c.findings if f.rule_id == "idx1.empty"]
    assert empty and all(f.verification and f.verification["state"] == "confirmed" for f in empty
                         if f.severity.value in ("S1", "S2"))
    assert any(f.verification for f in empty)
