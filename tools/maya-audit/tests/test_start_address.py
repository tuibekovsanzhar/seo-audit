"""The start address that answers with an error, and the brand's other domains (Round 1, run 3: DECISIONS 196 and 202).

- A start address that answers 4xx or 5xx while the audit still read the site from its root is said first, in every
  output: the Markdown and text reports, the web summary and the printed report, in English and Turkish.
- `--brand-family-domain` and the plan card's field take host names and nothing else.

Every site is made up and held in memory (an in-memory transport, the web app's test sites). Each rule has its healthy
case beside it.
"""
import json

import pytest

pytest.importorskip("fastapi")

from maya_audit import cli, schema, single_page  # noqa: E402
from maya_audit.report import START_FAILED, build_report, headline, render_markdown, render_text, run_outcome, start_address  # noqa: E402
from maya_audit_web import pdf, strings, summary  # noqa: E402
from test_blocked_and_small_sites import no_lookups  # noqa: E402,F401
from test_false_alarms import KAFE, answer, audited  # noqa: E402
from test_web_app import API, SHOP, audit_of, error, get, plan, web  # noqa: E402,F401

ENTERED = KAFE + "/urun-detayi"
SENTENCE = f"The start address you entered returned 404 (/urun-detayi). The audit was run from {KAFE}/ instead."
TURKISH = f"Girdiğiniz başlangıç adresi 404 döndürdü (/urun-detayi). Denetim bunun yerine {KAFE}/ adresinden yürütüldü."
ROUTES = {"/": answer('<a href="/menu">Menü</a>', title="Demo Kafe | Ana Sayfa"), "/menu": answer(title="Menü | Demo Kafe")}


def shown(outcome, language="en"):
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    strings.set_language(language)
    try:
        view = summary.build(report, outcome="INCOMPLETE", reason="as saved")
        printed = pdf.render_html(view, rows=summary.search(report, limit=10)["items"], plan=summary.action_plan(report), generated_at="2026-10-14T00:00:00+00:00")
    finally:
        strings.set_language("en")
    return report, view, printed


def test_a_start_address_that_answers_404_is_said_first_in_every_output_in_english_and_turkish(no_lookups):
    outcome = audited(ROUTES, start=ENTERED, sitemap=("/", "/menu"))
    assert [(p.url.removeprefix(KAFE), p.status) for p in outcome.result.pages][:2] == [("/urun-detayi", 404), ("/", 200)]
    found = {"entered": ENTERED, "status": 404, "audited_from": KAFE + "/"}
    assert start_address(outcome.result) == found
    report, view, printed = shown(outcome)
    assert report["schema_version"] == "1.30" and report["problem_summary"]["start_address"] == found
    assert set(report["problem_summary"]) <= set(schema.PROBLEM_SUMMARY_KEYS) and tuple(found) == schema.PROBLEM_START_ADDRESS_KEYS
    assert START_FAILED.format(status=404, path="/urun-detayi", audited_from=KAFE + "/") == SENTENCE
    # The engine's own outputs: the first sentence of the Markdown headline, and a line of the text header.
    assert headline(report["problem_summary"]).startswith(SENTENCE + " ")
    markdown, text = render_markdown(outcome.result, outcome.gates, outcome.checks), render_text(outcome.result, outcome.gates, outcome.checks)
    assert f"**{SENTENCE} " in markdown and markdown.index(SENTENCE) < markdown.index("## What this audit covers")
    assert f"Start       {SENTENCE}\n" in text and text.index(SENTENCE) < text.index("INT-1")
    # The web summary and the printed report: the same sentence, in the headline and on the cover.
    assert view["start_address"] == {**found, "message": SENTENCE} and view["headline"] == headline(report["problem_summary"])
    cover = printed.split('<section class="exec">')[0]
    assert f"<b>{SENTENCE}</b>" in cover and printed.count(SENTENCE) == 2
    _, turkish, turkish_printed = shown(outcome, "tr")
    assert turkish["start_address"]["message"] == TURKISH and turkish["headline"].startswith(TURKISH + " ")
    assert f"<b>{TURKISH}</b>" in turkish_printed and "The start address" not in turkish_printed


def test_a_start_address_that_answers_200_adds_nothing_and_a_saved_1_13_report_is_read_as_before(no_lookups):
    outcome = audited(ROUTES, sitemap=("/", "/menu"))
    assert start_address(outcome.result) is None
    report, view, printed = shown(outcome)
    assert "start_address" not in report["problem_summary"] and view["start_address"] is None
    assert "start address" not in headline(report["problem_summary"]).lower() and "The start address you entered" not in printed
    assert "The start address" not in render_markdown(outcome.result, outcome.gates, outcome.checks)
    assert "\nStart       " not in render_text(outcome.result, outcome.gates, outcome.checks)
    # A deep start address that answers 200 is the page the audit began on, not a failed one.
    deep = audited(ROUTES, start=KAFE + "/menu", sitemap=("/", "/menu"))
    assert start_address(deep.result) is None
    # A report saved by team-preview-13 has no such key, and is shown as it always was.
    older = {**report, "schema_version": "1.13"}
    assert schema.unsupported_reason(older) is None
    assert summary.build(older, outcome="COMPLETED", reason="as saved")["start_address"] is None


def test_a_single_page_audit_of_an_address_that_answers_404_has_no_other_page_to_name(no_lookups):
    outcome = audited(ROUTES, start=ENTERED, sitemap=("/", "/menu"), single_page=True, max_pages=1)
    assert [(p.url, p.status) for p in outcome.result.pages] == [(ENTERED, 404)] and single_page.is_single(outcome.result)
    assert start_address(outcome.result) is None
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    assert "start_address" not in report["problem_summary"] and report["problem_summary"]["single_page"] == {"url": ENTERED}
    assert "The start address" not in headline(report["problem_summary"])
    assert run_outcome(outcome.result, outcome.gates)[1] != "COMPLETED" or "404" in json.dumps(report["checks"])
    # Healthy: a deep address that answers 200 is still "the page audited" (decision 191).
    one = audited(ROUTES, start=KAFE + "/menu", single_page=True, max_pages=1)
    assert single_page.page_url(one.result) == KAFE + "/menu" and run_outcome(one.result, one.gates)[1:] == ("COMPLETED", single_page.OUTCOME)


# -- the brand's other domains --------------------------------------------------------------------------------------
def test_the_command_line_takes_host_names_only_and_passes_them_to_the_audit(capsys):
    args = cli._parser().parse_args(["crawl", "https://demo-kafe.test/", "--brand-family-domain", "Other-Shop.test",
                                     "--brand-family-domain", "grup.example", "--brand-family-domain", "other-shop.test"])
    cfg = cli._crawl_config(args)
    assert cfg.brand_family_domains == ("other-shop.test", "grup.example") and cfg.idx6_other_site_checks_max == 10
    assert list(cfg.snapshot()["brand_family_domains"]) == ["other-shop.test", "grup.example"]
    assert cli._crawl_config(cli._parser().parse_args(["crawl", "https://demo-kafe.test/"])).brand_family_domains == ()
    for bad in ("https://other-shop.test/", "other-shop.test/yol", "<script>alert(1)</script>", "10.0.0.1"):
        with pytest.raises(SystemExit):
            cli._parser().parse_args(["crawl", "https://demo-kafe.test/", "--brand-family-domain", bad])
        assert "not a domain name" in capsys.readouterr().err


def test_the_plan_card_field_is_validated_saved_in_the_profile_and_part_of_the_fingerprint(web):
    client = web()
    plain = plan(client)
    assert plain["brand_family_domains"] == [] and plain["max_brand_family_domains"] == 20
    made = plan(client, brand_family_domains=[" Other-Shop.example ", "grup.example", "other-shop.example", ""])
    assert made["brand_family_domains"] == ["other-shop.example", "grup.example"]
    assert made["fingerprint"] != plain["fingerprint"]  # a changed list is a changed plan
    assert plan(client, brand_family_domains=["grup.example", "other-shop.example"])["fingerprint"] == made["fingerprint"]
    assert plan(client, brand_family_domains=[])["fingerprint"] == plain["fingerprint"]
    # Anything that is not a host name is refused in the app's usual error shape, and never stored or echoed as markup.
    for bad in (["https://other-shop.example/"], ["other-shop.example/path"], ["<img src=x onerror=alert(1)>"], ["two words.example"], ["10.0.0.1"]):
        problem = error(client.post(f"{API}/plans", json={"url": SHOP, "brand_family_domains": bad}), 422, "invalid_brand_family_domains")
        assert problem["message"].startswith("This is not a domain name: ")
        error(client.put(f"{API}/projects/{SHOP}/profile", json={"brand_family_domains": bad}), 422, "invalid_brand_family_domains")
    error(client.post(f"{API}/plans", json={"url": SHOP, "brand_family_domains": [f"d{n}.example" for n in range(21)]}), 422, "invalid_request")
    error(client.post(f"{API}/plans", json={"url": SHOP, "brand_family_domains": "other-shop.example"}), 422, "invalid_request")
    assert client.get(f"{API}/projects/{SHOP}/profile").json()["brand_family_domains"] == []

    # Saved in the profile: a later plan that names none begins from the saved ones; a save that leaves the field out keeps them.
    saved = client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Demo Shop", "brand_family_domains": ["Other-Shop.example"]}).json()
    assert saved["brand_family_domains"] == ["other-shop.example"]
    assert client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Demo Shop"}).json()["brand_family_domains"] == ["other-shop.example"]
    later = plan(client)
    assert later["brand_family_domains"] == ["other-shop.example"] and later["fingerprint"] != plain["fingerprint"]
    assert client.put(f"{API}/projects/{SHOP}/profile", json={"brand_name": "Demo Shop", "brand_family_domains": []}).json()["brand_family_domains"] == []

    # The audit runs with the plan's list.
    report = get(client, audit_of(client, brand_family_domains=["other-shop.example"]), "/result")
    assert report["crawl"]["config"]["brand_family_domains"] == ["other-shop.example"]
    idx6 = next(check for check in report["checks"] if check["check_id"] == "IDX-6")
    assert idx6["evidence"]["brand_family_domains"] == ["other-shop.example"]
    # Turkish: the label and the refusal.
    client.put(f"{API}/session/language", json={"language": "tr"})
    problem = error(client.post(f"{API}/plans", json={"url": SHOP, "brand_family_domains": ["a b"]}), 422, "invalid_brand_family_domains")
    assert problem["message"].startswith("Bu bir alan adı değil: ") and strings.t("plan.brand_family", "tr") == "Aynı markanın diğer alan adları (virgülle ayırın)"
    client.put(f"{API}/session/language", json={"language": "en"})
    assert strings.t("plan.brand_family") == "Other domains of the same brand (comma-separated)"


def test_the_plan_card_builds_the_field_from_dom_nodes_and_sends_a_list():
    from pathlib import Path

    script = (Path(summary.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert 'T("plan.brand_family")' in script and "brand_family_domains: familyList()" in script
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert unsafe not in script
