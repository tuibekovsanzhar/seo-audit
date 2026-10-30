from maya_audit.classify import classify_fetch
from maya_audit.models import Confidence, FetchClass

CHALLENGE = b"<html><head><title>Just a moment...</title></head><script src='/cdn-cgi/challenge-platform/h/b/x'></script></html>"


def test_cf_mitigated_header_is_verified_block():
    c = classify_fetch(403, {"cf-mitigated": "challenge"}, CHALLENGE, None)
    assert (c.fetch_class, c.confidence) == (FetchClass.BLOCKED, Confidence.VERIFIED)
    assert "header cf-mitigated: challenge" in c.evidence


def test_plain_403_is_verified_block():
    c = classify_fetch(403, {}, b"Forbidden", None)
    assert (c.fetch_class, c.confidence) == (FetchClass.BLOCKED, Confidence.VERIFIED)


def test_429_is_verified_rate_limit_with_retry_after_evidence():
    c = classify_fetch(429, {"retry-after": "120"}, b"", None)
    assert (c.fetch_class, c.confidence) == (FetchClass.RATE_LIMITED, Confidence.VERIFIED)
    assert "header retry-after: 120" in c.evidence


def test_challenge_body_on_200_is_estimated_block():
    c = classify_fetch(200, {}, CHALLENGE, None)
    assert (c.fetch_class, c.confidence) == (FetchClass.BLOCKED, Confidence.ESTIMATED)


def test_challenge_body_on_503_is_estimated_block():
    c = classify_fetch(503, {}, CHALLENGE, None)
    assert (c.fetch_class, c.confidence) == (FetchClass.BLOCKED, Confidence.ESTIMATED)


def test_plain_503_is_the_servers_own_response():
    c = classify_fetch(503, {}, b"Service Unavailable", None)
    assert c.fetch_class == FetchClass.OK


def test_injected_challenge_script_on_normal_page_is_not_a_block():
    body = b"<html><title>Docs</title><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"
    c = classify_fetch(200, {}, body, None)
    assert c.fetch_class == FetchClass.OK


def test_transport_error():
    c = classify_fetch(None, {}, b"", "timeout (ReadTimeout)")
    assert (c.fetch_class, c.confidence) == (FetchClass.ERROR, Confidence.VERIFIED)
