"""Single-page audit mode: only the address entered is read and checked (DECISIONS 191).

Every site here is made up (the fake server, mock transports, an in-memory Firecrawl). Each rule has its healthy
case beside it: an ordinary audit of the same site still follows links and compares pages.
"""
import json

import httpx

from maya_audit import cli, schema, single_page
from maya_audit.config import CrawlConfig
from maya_audit.firecrawl import Options, reader
from maya_audit.firecrawl.panel import section as firecrawl_section
from maya_audit.report import build_report, headline, page_checks, render_markdown, render_text, run_outcome
from maya_audit_web.strings import t
from test_firecrawl import HTML, ROBOTS_TEXT, SITE, Firecrawl, client_for, no_lookups  # noqa: F401
from test_review_fixes import QUIET, TR, audit, page
from test_web_app import API, SHOP, audit_of, get, plan, web  # noqa: F401
from test_web_firecrawl import PAGES, services

PRODUCT = page(f"<h2>Lokum</h2><p>{TR}</p>" + '<a href="/urun/baklava/">Baklava</a> <a href="/hakkimizda">Hakkımızda</a>', title="Lokum 500 g")
ROUTES = {"/urun/lokum/": PRODUCT,
          "/urun/baklava/": page(f"<h1>Baklava</h1><p>{TR}</p>", title="Lokum 500 g"),
          "/hakkimizda": page(f"<h1>Hakkımızda</h1><p>{TR}</p>", title="Hakkımızda"),
          "/eski-urun": __import__("fakeserver").Response(status=301, headers={"location": "/urun/lokum/"})}


def paths(outcome, purpose=None):
    return [request.url.removeprefix(outcome.base) for request in outcome.result.requests if purpose in (None, request.purpose)]


def test_only_the_address_entered_is_read_and_no_link_or_sitemap_is_followed():
    one = audit(ROUTES, start="/urun/lokum/", single_page=True, max_pages=1)
    assert [p.url.removeprefix(one.base) for p in one.result.pages] == ["/urun/lokum/"]
    assert paths(one, "page") == ["/urun/lokum/"] and not paths(one, "sitemap") and "/robots.txt" in paths(one)
    assert not any(path in ("/urun/baklava/", "/hakkimizda", "/") for path in paths(one))
    assert one.result.config["single_page"] is True and one.result.stop_reason.value == "exhausted"

    # The same site in an ordinary audit: links and the sitemap are followed, as before.
    whole = audit(ROUTES, start="/urun/lokum/")
    assert len(whole.result.pages) >= 3 and paths(whole, "sitemap") and not single_page.is_single(whole.result)


def test_a_redirect_of_the_address_itself_is_followed_and_still_one_page_is_read():
    one = audit(ROUTES, start="/eski-urun", single_page=True, max_pages=1)
    assert [p.url.removeprefix(one.base) for p in one.result.pages if p.status == 200] == ["/urun/lokum/"]
    assert set(paths(one, "page")) == {"/eski-urun", "/urun/lokum/"}


def test_checks_that_compare_pages_are_set_aside_and_site_level_facts_are_still_checked():
    one = audit(ROUTES, start="/urun/lokum/", single_page=True, max_pages=1)
    for check_id in single_page.COMPARES_PAGES:
        check = one.by_id[check_id]
        assert (check.status, check.summary, check.findings) == ("not_assessed", single_page.NOT_APPLICABLE, []), check_id
        assert check.evidence["single_page"] == "compares_pages"
    # The page is not the homepage: the homepage's own checks say so instead of judging this page as one.
    assert one.by_id["STR-18"].status == "not_assessed" and one.by_id["STR-18"].summary == single_page.NOT_THE_HOMEPAGE
    assert not [f for f in one.by_id["STR-3"].findings if "homepage" in f.title.lower()]
    [no_h1] = [f for f in one.by_id["STR-2"].findings if "<h1>" in f.title]
    assert no_h1.title == "1 page(s) have no <h1>" and no_h1.severity.value == "S4"
    # Site-level facts the page depends on: robots.txt was read, and the host's missing HTTPS is still a finding.
    assert one.by_id["ACC-1"].status != "not_assessed" and one.by_id["IDX-2"].findings and one.by_id["IDX-2"].findings[0].scope["kind"] == "sitewide"
    counted = page_checks(one.checks)
    # The checks set aside are not counted as checks that could not run.
    assert not counted["limited"] and counted["total"] == page_checks(audit(ROUTES, start="/urun/lokum/").checks)["total"] - len(single_page.COMPARES_PAGES) - 1

    # Healthy cases: the root address keeps the homepage rules, and an ordinary audit keeps the comparisons.
    root = audit({"/": page(f"<h2>Mağaza</h2><p>{TR}</p>", title="Mağaza")}, single_page=True, max_pages=1)
    assert single_page.is_homepage(root.result) and root.by_id["STR-18"].status != "not_assessed"
    assert [f.title for f in root.by_id["STR-2"].findings if "<h1>" in f.title] == ["The homepage has no <h1>"]
    whole = audit(ROUTES, start="/urun/lokum/")
    assert whole.by_id["IDX-8"].status != "not_assessed" and all("single_page" not in (c.evidence or {}) for c in whole.checks)


def test_every_output_is_titled_single_page_audit_and_says_other_pages_were_not_checked():
    one = audit(ROUTES, start="/urun/lokum/", single_page=True, max_pages=1)
    url = one.base + "/urun/lokum/"
    report = json.loads(json.dumps(build_report(one.result, one.gates, one.checks)))
    summary = report["problem_summary"]
    assert summary["single_page"] == {"url": url} and summary["pages_checked"] == 1 and set(summary) <= set(schema.PROBLEM_SUMMARY_KEYS)
    assert headline(summary).endswith(". " + single_page.ONLY_THIS_PAGE) and "1 page read for content" in headline(summary)
    assert run_outcome(one.result, one.gates)[1:] == ("COMPLETED", single_page.OUTCOME)
    assert report["audit_status"]["content_coverage"]["note"] == single_page.COVERAGE
    markdown, text = render_markdown(one.result, one.gates, one.checks), render_text(one.result, one.gates, one.checks)
    assert markdown.startswith(f"# Single-page audit: {url}\n") and single_page.ONLY_THIS_PAGE in markdown and text.startswith(f"Single-page audit: {url}\n{single_page.ONLY_THIS_PAGE}\n")
    assert single_page.SITE_LEVEL in markdown and "| Whole site" not in markdown

    whole = audit(ROUTES, start="/urun/lokum/")
    report = build_report(whole.result, whole.gates, whole.checks)
    assert "single_page" not in report["problem_summary"] and "Only this page" not in headline(report["problem_summary"])
    assert render_markdown(whole.result, whole.gates, whole.checks).startswith("# Maya Audit: ")


def test_firecrawl_is_sent_only_the_address_entered(tmp_path, no_lookups):
    def site(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_TEXT, headers={"content-type": "text/plain"})
        url = str(request.url)
        return httpx.Response(200, headers=HTML, text=SITE[url]) if url in SITE else httpx.Response(404, headers=HTML, text="<html><title>x</title></html>")

    deep = "https://bank.test/about"
    assert deep in SITE
    cfg = CrawlConfig(**{**QUIET, "max_pages": 1, "single_page": True})
    outcome = __import__("maya_audit.audit", fromlist=["x"]).run_audit(deep, cfg, httpx.MockTransport(site))
    api = Firecrawl(SITE)
    options = Options(read_always=True, max_pages=1)
    assert options.estimate(1)["max_requests"] == 2  # the page and robots.txt: "about 2 credits" on the plan card
    info = reader.apply(outcome, cfg, client_for(tmp_path, api), options)
    assert api.urls == [deep] and info["used"] and info["pages_read"] == 1
    by_id = {c.check_id: c for c in outcome.checks}
    assert by_id["IDX-8"].summary == single_page.NOT_APPLICABLE and by_id["STR-21"].status == "not_assessed"
    part = firecrawl_section(info)
    assert run_outcome(outcome.result, outcome.gates, info)[1:] == ("COMPLETED", single_page.OUTCOME)
    assert not part["coverage"].get("known_urls_not_requested") and not part.get("stopped_because")


def test_the_command_line_flag_caps_the_run_at_one_page():
    args = cli._parser().parse_args(["crawl", "https://shop.test/urun/lokum/", "--single-page", "--max-pages", "50"])
    cfg = cli._crawl_config(args)
    assert cfg.single_page is True and cfg.max_pages == 1
    assert cli._crawl_config(cli._parser().parse_args(["crawl", "https://shop.test/"])).single_page is False


def test_the_web_mode_plans_one_page_and_ignores_important_pages(web):
    client = web()
    modes = get_json(client, "/settings")["modes"]
    assert [mode["id"] for mode in modes] == ["single", "quick", "smart", "standard", "custom"]  # custom: DECISIONS 331  # smart: DECISIONS 327 and modes[0]["label"] == "Single page" and modes[0]["page_cap"] == 1
    made = plan(client, url=f"http://{SHOP}/item/13", mode="single", key_pages=[f"http://{SHOP}/item/2"])
    assert made["page_cap"] == 1 and made["single_page"] is True and made["target"]["url"] == f"http://{SHOP}/item/13"
    assert made["scope_label"] == t("plan.scope.single") and "no links are followed" in made["scope_label"]
    quick = plan(client)
    assert quick["page_cap"] == 50 and not quick["single_page"] and quick["scope_label"] is None
    assert client.post(f"{API}/plans", json={"url": SHOP, "mode": "one"}).status_code == 422


def get_json(client, path):
    response = client.get(f"{API}{path}")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_single_page_audit_in_the_app_reads_one_page_and_labels_site_level_findings(web):
    client = web()
    audit_ = audit_of(client, url=f"http://{SHOP}/item/13", mode="single")
    assert audit_["state"] == "finished" and audit_["outcome"]["code"] == "COMPLETED" and audit_["outcome"]["reason"] == single_page.OUTCOME
    report, view = get(client, audit_, "/result"), get(client, audit_, "/summary")
    assert [p["url"] for p in report["crawl"]["pages"]] == [f"http://{SHOP}/item/13"] and report["page_counts"]["pages_checked"] == 1
    assert [r["url"] for r in report["crawl"]["requests"] if r["purpose"] == "page"] == [f"http://{SHOP}/item/13"]
    title = f"Single-page audit: http://{SHOP}/item/13"
    assert view["single_page"] == {"url": f"http://{SHOP}/item/13", "title": title, "note": single_page.ONLY_THIS_PAGE}
    assert view["headline"].endswith(single_page.ONLY_THIS_PAGE)
    site_wide = [row for row in view["top"] if row.get("site_level")]
    assert site_wide and all(row["affects"] == "Site-level: also affects this page" for row in site_wide)
    coverage = next(row for row in view["status"]["rows"] if row["id"] == "content_coverage")
    assert coverage["note"] == single_page.COVERAGE
    printed = client.get(f"{API}/audits/{audit_['id']}/print?full=true").text
    assert f"<title>{title}</title>" in printed and single_page.ONLY_THIS_PAGE in printed
    if report["problem_summary"]["whole_site"]["problems"]:
        assert single_page.SITE_LEVEL in printed
    assert client.get(f"{API}/audits/{audit_['id']}/downloads/markdown").text.startswith(f"# {title}\n")

    # In Turkish, with no English left in the sentences this mode adds.
    assert client.put(f"{API}/session/language", json={"language": "tr"}).status_code == 200
    turkish, printed = get(client, audit_, "/summary"), client.get(f"{API}/audits/{audit_['id']}/print?full=true&lang=tr").text
    assert turkish["single_page"]["title"] == f"Tek sayfa denetimi: http://{SHOP}/item/13"
    assert turkish["headline"].endswith("Yalnızca bu sayfa okundu; sitenin diğer sayfaları kontrol edilmedi.")
    assert "(İngilizce)" not in printed and "Only this page" not in printed and "Single-page audit" not in printed
    client.put(f"{API}/session/language", json={"language": "en"})

    # Healthy case: a quick audit of the same site reads many pages and carries none of this.
    quick = get(client, audit_of(client), "/summary")
    assert quick["single_page"] is None and "Only this page" not in quick["headline"] and quick["problem_summary"]["pages_checked"] > 1


def test_the_plan_card_says_one_page_and_about_two_firecrawl_credits(web, tmp_path, monkeypatch):
    api = Firecrawl({url: body for url, body in PAGES.items() if not url.endswith("robots.txt")})
    client = web(firecrawl=services(tmp_path, api))
    # With zero data retention (the default) a request costs 2 credits, and the card says the real figure.
    made = plan(client, mode="single")
    assert made["firecrawl"]["max_pages"] == 1 and made["firecrawl"]["max_requests"] == 2 and made["firecrawl"]["max_credits"] == 4
    assert made["scope_label"] == "Single page: 1 page, ~4 Firecrawl credits. Only this address is read; no links are followed"
    monkeypatch.setenv("MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION", "off")  # an account without zero data retention: 1 credit a request
    made = plan(client, mode="single")
    assert made["firecrawl"]["max_credits"] == 2
    assert made["scope_label"] == "Single page: 1 page, ~2 Firecrawl credits. Only this address is read; no links are followed"
    monkeypatch.delenv("MAYA_AUDIT_FIRECRAWL_ZERO_DATA_RETENTION")
    assert api.bodies == []  # a plan sends nothing
    assert plan(client)["firecrawl"]["max_pages"] == 50
