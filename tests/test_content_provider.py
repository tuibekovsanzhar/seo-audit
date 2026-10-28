"""Provider routing, consent and diagnostics; all transports are in-memory."""
import json

import httpx
import pytest

from maya_audit.config import CrawlConfig
from maya_audit.content_provider import ContentProviderError, ProviderConsent, ProviderIdentity
from maya_audit.firecrawl import ApprovalRequired, Options, reader, panel
from maya_audit.firecrawl.client import WebsiteLoadError
from test_firecrawl import KEY, SITE, Firecrawl, blocked_audit, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET

ENGINE_ERROR = ("All scraping engines failed to retrieve content from this URL. "
                "Engines tried: [pdf, document, image]. " + "Provider diagnostic detail. " * 30 + "END-OF-ERROR")


def engine_failure(body):
    return httpx.Response(500, json={"success": False, "error": ENGINE_ERROR})


@pytest.mark.parametrize("proxy,approved", [("basic", False), ("enhanced", True), ("auto", True)])
@pytest.mark.parametrize("waived", [False, True])
def test_html_request_keeps_browser_eligible_and_privacy_controls(tmp_path, proxy, approved, waived):
    api = Firecrawl(SITE)
    client = client_for(tmp_path, api, proxy=proxy, owner_approved_bypass=approved,
                        allow_without_zero_data_retention=waived)
    client.scrape("https://bank.test/")
    body = api.bodies[0]
    assert body["formats"] == ["rawHtml"] and body["onlyMainContent"] is False
    assert body["blockAds"] is True and body["parsers"] == [] and body["mobile"] is False
    assert body["proxy"] == proxy and body["skipTlsVerification"] is False
    assert body["maxAge"] == 0 and body["storeInCache"] is False
    assert body.get("zeroDataRetention", False) is (not waived)
    assert body["timeout"] == 85000 and "waitFor" not in body
    assert not {"fastMode", "engine", "forceEngine", "actions", "lockdown", "minAge", "headers"} & body.keys()
    assert client.body_for("https://bank.test/", wait_ms=1500)["waitFor"] == 1500


@pytest.mark.parametrize("proxy", ["enhanced", "auto"])
def test_unblocking_consent_is_enforced_at_adapter_even_with_money_and_cache(tmp_path, proxy):
    api = Firecrawl(SITE)
    allowed = client_for(tmp_path, api, proxy=proxy, owner_approved_bypass=True)
    allowed.scrape("https://bank.test/")
    denied = client_for(tmp_path, api, proxy=proxy)
    with pytest.raises(ApprovalRequired, match="owner has not approved"):
        denied.scrape("https://bank.test/")
    assert len(api.bodies) == 1 and denied.calls == []


def test_provider_consent_defaults_off():
    with pytest.raises(ContentProviderError, match="off"):
        ProviderConsent().require(unblocking=False)
    with pytest.raises(ContentProviderError, match="owner"):
        ProviderConsent(enabled=True).require(unblocking=True)
    ProviderConsent(enabled=True, owner_approved=True).require(unblocking=True)


def test_complete_error_and_engines_are_preserved_but_credentials_redacted(tmp_path):
    api = Firecrawl(responder=lambda body: httpx.Response(500, json={"error": ENGINE_ERROR + KEY.value}))
    client = client_for(tmp_path, api)
    with pytest.raises(WebsiteLoadError) as raised:
        client.scrape("https://bank.test/")
    error = raised.value
    assert "END-OF-ERROR" in str(error) and KEY.value not in str(error)
    assert error.engines == ["pdf", "document", "image"] and error.engine_selection
    assert error.diagnostic("https://bank.test/")["message"].endswith("[redacted]")
    assert client.ledger.spent_today() == 0 and client.calls[0]["credits"] == 0
    assert client.requests_sent == 1


def test_engine_failure_continues_to_known_urls_without_retry_or_escalation(tmp_path, no_lookups):
    outcome = blocked_audit()
    outcome.result.discovered_urls += ["https://bank.test/products", "https://bank.test/contact"]
    before = [(c.check_id, c.summary) for c in outcome.checks if c.check_id.startswith("ACC-")]
    api = Firecrawl(SITE, responder=lambda body: engine_failure(body) if body["url"] == "https://bank.test/" else None)
    client = client_for(tmp_path, api)
    info = reader.apply(outcome, CrawlConfig(**QUIET), client, Options())
    assert info["used"] and info["pages_read"] == 2
    assert api.urls == ["https://bank.test/", "https://bank.test/products", "https://bank.test/contact"]
    assert {b["proxy"] for b in api.bodies} == {"basic"}
    assert info["errors"][0]["message"] == ENGINE_ERROR
    assert info["errors"][0]["kind"] == "engine_selection" and not reader.also_blocked(info)
    assert ENGINE_ERROR in panel.render_markdown(info) and ENGINE_ERROR in panel.render_text(info)
    assert before == [(c.check_id, c.summary) for c in outcome.checks if c.check_id.startswith("ACC-")]
    assert client.ledger.spent_today() == 4  # failed URL is free; two documents


def test_repeated_engine_failures_use_request_cap_even_when_they_cost_zero(tmp_path, no_lookups):
    outcome = blocked_audit()
    outcome.result.discovered_urls += [f"https://bank.test/p{n}" for n in range(10)]
    api = Firecrawl(responder=engine_failure)
    client = client_for(tmp_path, api, max_pages=3)
    info = reader.apply(outcome, CrawlConfig(**QUIET), client, Options(max_pages=3))
    assert len(api.urls) == 4  # adapter's hard request bound: pages plus one robots allowance
    assert len(set(api.urls)) == len(api.urls) and not info["used"]
    assert len(info["errors"]) == 4 and client.ledger.spent_today() == 0
    assert "request allowance" in info["stopped_because"] and not reader.also_blocked(info)


def test_provider_identity_labels_shared_content_checks(tmp_path, no_lookups):
    # Test-only adapter uses the guarded mock client; no second commercial provider is implemented.
    client = client_for(tmp_path, Firecrawl(SITE))
    client.identity = ProviderIdentity("fixture-provider", "Fixture Provider")
    outcome = blocked_audit()
    info = {}
    checks = reader.read_blocked_site(outcome.result, CrawlConfig(**QUIET), client, Options(), info)
    assert checks
    assert all(c.summary.startswith("Source: Fixture Provider") for c in checks)
    assert all(f.evidence["source"]["reader"] == "fixture-provider" for c in checks for f in c.findings)
    assert all(f.notes[0].startswith("Source: Fixture Provider") for c in checks for f in c.findings)
    from maya_audit_web.summary import _source
    from maya_audit.models import to_jsonable
    assert all(_source(to_jsonable(f))["label"].startswith("Source: Fixture Provider")
               for c in checks for f in c.findings)


def test_partial_content_survives_request_cap_after_errors(tmp_path, no_lookups):
    outcome = blocked_audit()
    outcome.result.discovered_urls += ["https://bank.test/products", "https://bank.test/contact"]
    api = Firecrawl(SITE, responder=lambda body: None if body["url"].endswith("/products") else engine_failure(body))
    info = reader.apply(outcome, CrawlConfig(**QUIET), client_for(tmp_path, api, max_pages=1), Options(max_pages=2))
    assert info["used"] and info["pages_read"] == 1 and len(api.urls) == 2
    assert "request allowance" in info["stopped_because"] and info["errors"]
    assert outcome.by_id()["STR-1"].coverage["not_assessed"]
