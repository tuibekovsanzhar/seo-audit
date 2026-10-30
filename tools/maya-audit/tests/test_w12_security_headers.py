"""DECISIONS 262: baseline security headers on the homepage's answer, an Info note."""
from maya_audit.checks.perf import missing_security_headers


def test_a_bare_answer_lacks_all_four():
    assert missing_security_headers({"content-type": "text/html"}) == [
        "Content-Security-Policy", "X-Content-Type-Options: nosniff", "Referrer-Policy", "X-Frame-Options (or CSP frame-ancestors)"]


def test_report_only_csp_and_frame_ancestors_count():
    headers = {"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff",
               "Referrer-Policy": "strict-origin-when-cross-origin"}
    assert missing_security_headers(headers) == []
    assert "Content-Security-Policy" not in missing_security_headers({"content-security-policy-report-only": "x"})


def test_nosniff_must_be_the_value():
    assert "X-Content-Type-Options: nosniff" in missing_security_headers({"x-content-type-options": "yes"})
