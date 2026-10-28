"""Owner cooperation: the allowlist steps for a site nothing could read, ownership by meta tag or DNS TXT, docs/BOT.md.

The DNS lookup is a mock transport; no test asks a real resolver.
"""
import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from maya_audit import allowlist, ownership  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, Site, cloudflare, get, plan, start, web  # noqa: E402,F401
from test_web_blocked import walled  # noqa: E402
from test_web_firecrawl import PAGES, services  # noqa: E402

ROOT = Path(__file__).parents[1]


def test_the_token_is_stable_per_site_and_cannot_be_guessed_for_another():
    one = ownership.token_for("Shop.example", "secret-a")
    assert one == ownership.token_for("shop.example", "secret-a") and one.startswith("maya-") and len(one) == 37
    assert one != ownership.token_for("other.example", "secret-a") and one != ownership.token_for("shop.example", "secret-b")
    assert ownership.meta_tag(one) == f'<meta name="maya-site-verification" content="{one}">'
    assert ownership.txt_record(one) == f"maya-site-verification={one}" and len(ownership.instructions("shop.example", one)) == 4


def dns(records, status=200):
    seen = []

    def answer(request):
        seen.append(request)
        assert request.url.host == "dns.google" and request.url.params["type"] == "TXT"
        return httpx.Response(status, json={"Status": 0, "Answer": [{"name": "shop.example.", "type": 16, "data": f'"{r}"'} for r in records]})
    return httpx.MockTransport(answer), seen


def test_a_dns_txt_record_is_matched_exactly_and_a_failed_lookup_is_not_a_verification():
    token = ownership.token_for("shop.example", "s")
    found, seen = dns(["v=spf1 -all", ownership.txt_record(token)])
    assert ownership.dns_txt_verified("shop.example", token, transport=found)["verified"] is True and seen[0].url.params["name"] == "shop.example"
    other, _ = dns(["maya-site-verification=maya-somebody-else", ownership.txt_record(token) + "x"])
    missing = ownership.dns_txt_verified("shop.example", token, transport=other)
    assert missing["verified"] is False and missing["txt_records_found"] == 2 and "no DNS TXT record matching" in missing["reason"]
    down, _ = dns([], status=503)
    assert ownership.dns_txt_verified("shop.example", token, transport=down)["verified"] is False

    def broken(request):
        raise httpx.ConnectError("no route")
    assert "could not be checked" in ownership.dns_txt_verified("shop.example", token, transport=httpx.MockTransport(broken))["reason"]


def test_allowlist_steps_name_the_user_agent_put_the_recognised_firewall_first_and_never_promise_a_bypass():
    blocks = allowlist.instructions("Maya-Audit", "Maya-Audit/0.2", "Cloudflare")
    assert [b["id"] for b in blocks] == ["cloudflare", "akamai", "generic"] and blocks[0]["copy"] == '(http.user_agent contains "Maya-Audit")'
    assert [b["id"] for b in allowlist.instructions("Maya-Audit", "Maya-Audit/0.2", "Akamai")][0] == "akamai"
    text = "\n".join(allowlist.lines("Maya-Audit", "Maya-Audit/0.2")) + allowlist.markdown("Maya-Audit", "Maya-Audit/0.2")
    assert "Maya-Audit/0.2" in text and "auditor's IP address" in text and "Delete the rule after the audit" in text and "docs/BOT.md" in text
    assert "does not try to get past" in text


def test_the_bot_page_marks_what_is_still_to_be_confirmed():
    page = (ROOT / "docs" / "BOT.md").read_text(encoding="utf-8")
    assert page.count("to be confirmed") >= 5 and "Maya-Audit" in page and "User-agent: Maya-Audit\nDisallow: /" in page
    assert "maya-site-verification" in page and "@" not in page.replace("(name @)", "")  # no invented contact address


def test_the_allowlist_steps_appear_only_when_nothing_could_read_the_site(web, tmp_path):
    # Firecrawl was turned away too: the block card, the Markdown and the printable report carry the owner's steps.
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES, walled(("basic",)))))
    audit = start(client, plan(client))
    view = get(client, audit, "/summary")
    steps = view["blocked"]["allowlist"]
    assert [b["id"] for b in steps["blocks"]][0] == "cloudflare" and "Maya-Audit" in steps["note"]
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    printed = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert "## How to let the audit in" in markdown and "How to let the audit in" in printed and "http.user_agent contains" in printed
    # Read through Firecrawl: no block card, so no steps anywhere.
    read = web(folder=tmp_path / "read", site=Site(respond=cloudflare), firecrawl=services(tmp_path / "2", Firecrawl(PAGES)))
    fine = start(read, plan(read))
    assert get(read, fine, "/summary")["blocked"] is None
    assert "How to let the audit in" not in read.get(f"{API}/audits/{fine['id']}/downloads/markdown").text + read.get(f"{API}/audits/{fine['id']}/print?full=true").text
    # A site that let the audit in has none either.
    open_site = web(folder=tmp_path / "open")
    plain = start(open_site, plan(open_site))
    assert "How to let the audit in" not in open_site.get(f"{API}/audits/{plain['id']}/downloads/markdown").text


def test_ownership_is_checked_only_when_asked_and_a_dns_record_lets_acc4_run(web, monkeypatch):
    client = web()
    made = plan(client)
    proof = made["ownership"]
    assert proof["requested"] is False and proof["token"].startswith("maya-") and proof["token"] in proof["meta_tag"] and proof["token"] in proof["txt_record"]
    assert plan(client)["ownership"]["token"] == proof["token"]  # the same token for the same site, every time
    transport, seen = dns([ownership.txt_record(proof["token"])])
    monkeypatch.setattr(ownership, "TRANSPORT", transport)
    audit = start(client, made)
    assert seen == [] and "ownership" not in get(client, audit, "/result")  # not asked for: no lookup, no section

    asked = plan(client, verify_ownership=True)
    assert asked["ownership"]["requested"] and asked["fingerprint"] != made["fingerprint"]
    audit = start(client, asked)
    report = get(client, audit, "/result")
    owned = report["ownership"]
    assert len(seen) == 1 and owned["verified"] is True and owned["method"] == "dns_txt" and "DNS TXT record" in owned["summary"]
    acc4 = next(c for c in report["checks"] if c["check_id"] == "ACC-4")
    assert acc4["status"] != "not_assessed" or "ownership not verified" not in acc4["summary"]
    assert next(g for g in report["gates"] if g["check_id"] == "INT-2")["state"] != "violation"
    view = get(client, audit, "/summary")
    assert view["ownership"]["verified"] and view["verification"]["token"] == proof["token"]
    assert "## Site ownership" in client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    from maya_audit import schema
    assert set(owned) == set(schema.OWNERSHIP_KEYS)

    # No record and no tag: said plainly, with the two ways to verify, and ACC-4 stays unrun.
    nothing, _ = dns([])
    monkeypatch.setattr(ownership, "TRANSPORT", nothing)
    audit = start(client, plan(client, verify_ownership=True, key_pages=["/about"]))
    owned = get(client, audit, "/result")["ownership"]
    assert owned["verified"] is False and "is not verified" in owned["summary"] and len(owned["instructions"]) == 4
    assert json.dumps(get(client, audit, "/summary")["ownership"]["instructions"]).count(proof["token"]) == 2
