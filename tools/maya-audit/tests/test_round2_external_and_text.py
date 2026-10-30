"""Round 2, run 4: the share image's icon and size, invisible characters in the main text, links to other sites on by
default, and IDX-5 without the crawl's page-cap gap when the sitemap check asked every sitemap URL (DECISIONS 209,
210, 211; LG-81, LG-82, LG-83).

- STR-10: an og:image that is the site icon (a .ico address or an icon content type) is S4 with no request needed; an
  og:image under 200 × 200 pixels, read from the first 64 KB Maya already receives, is S4; an unknown size is nothing.
  Same-site redirects of an og:image are followed, at most 3 hops.
- STR-13: 10 or more zero-width or soft-hyphen characters in a page's main text is S4; the footer is not counted.
- IDX-6: every link to another site is asked once with a HEAD (a 405 is asked again as a GET), that site's robots.txt
  first and counted toward the cap; only 404 and 410 are broken. sameAs links are asked even with the check off. The web
  app's demo mode asks nothing of other sites.

Every site is made up and held in memory or on a loopback fake server; a made-up host on the real network path ends as
"could not be checked", never on the internet.
"""
import struct
from types import SimpleNamespace

import httpx

from fakeserver import FakeServer, Response, Site
from maya_audit import cli
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig, estimated_duration_s, external_link_cap
from maya_audit.structure_data import image_size
from maya_audit_web import demo, runner, wording
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import HTML_TYPE, KAFE, TR, answer, audited
from test_round2_sitemap_and_llms import thirty

EXT = "ext.test"


def page(body="", *, title="Sayfa | Demo Kafe", head="", footer=""):
    return httpx.Response(200, headers=HTML_TYPE, text=(
        f'<!doctype html><html lang="tr"><head><title>{title}</title>{head}</head><body><header><nav><a href="/">Ana Sayfa</a>'
        f"</nav></header><main><h1>{title}</h1><p>{TR}</p>{body}</main><footer>{footer}</footer></body></html>"))


def og(url):
    return f'<meta property="og:image" content="{url}">'


def png(width, height, extra=b""):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
            + b"\x08\x02\x00\x00\x00" + extra)


def image(body, kind="image/png"):
    return httpx.Response(200, headers={"content-type": kind}, content=body)


def str10(outcome, words):
    return [f for f in outcome.by_id["STR-10"].findings if words in f.title]


# -- Item 6: the share image ---------------------------------------------------------------------------------------------
def test_the_image_header_reader_knows_five_formats_and_says_nothing_it_cannot_read():
    assert image_size(png(1200, 630)) == {"format": "png", "width": 1200, "height": 630}
    assert image_size(b"GIF89a" + struct.pack("<HH", 64, 32) + b"\x00" * 4) == {"format": "gif", "width": 64, "height": 32}
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (1199).to_bytes(3, "little") + (629).to_bytes(3, "little")
    assert image_size(webp) == {"format": "webp", "width": 1200, "height": 630}
    ico = b"\x00\x00\x01\x00" + struct.pack("<H", 2) + bytes([16, 16]) + b"\x00" * 14 + bytes([32, 32]) + b"\x00" * 14
    assert image_size(ico) == {"format": "ico", "width": 32, "height": 32}
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"\x00" * 14 + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 630, 1200)
    assert image_size(jpeg + b"\x00" * 10) == {"format": "jpeg", "width": 1200, "height": 630}
    assert image_size(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None and image_size(b"") is None


def test_the_site_icon_as_share_image_is_reported_without_a_request_even_when_it_redirects(no_lookups):
    routes = {"/": page(title="Demo Kafe", head=og("/favicon.ico")),
              "/favicon.ico": httpx.Response(301, headers={"location": "/assets/favicon.ico"})}
    outcome = audited(routes)
    [icon] = str10(outcome, "site icon")
    assert icon.title == "1 page(s) use the site icon as share image (og:image is a .ico file)"
    assert (icon.severity.value, icon.confidence.value) == ("S4", "verified") and "LG-81" in icon.launch_gated
    assert icon.how_to_fix == "The share image is the site icon; use an image of at least 1200 × 630."
    assert wording.title("STR-10", icon.title, "tr") == ("1 sayfa paylaşım görseli olarak site simgesini kullanıyor "
                                                        "(og:image bir .ico dosyası)", True)
    assert wording.fix(icon.how_to_fix, "tr")[1] and wording.expected(icon.expected, "tr")[1]


def test_a_16_pixel_share_image_is_too_small(no_lookups):
    outcome = audited({"/": page(title="Demo Kafe", head=og("/og.png")), "/og.png": image(png(16, 16))})
    [small] = str10(outcome, "smaller than")
    assert small.title == "1 page(s) have a share image smaller than 200 × 200 pixels" and small.severity.value == "S4"
    assert small.evidence["images"][0]["image"] == {"format": "png", "width": 16, "height": 16}
    assert outcome.result.structure.links[KAFE + "/og.png"]["image"]["width"] == 16
    assert "LG-81" in small.launch_gated and wording.title("STR-10", small.title, "tr") == (
        "1 sayfanın paylaşım görseli 200 × 200 pikselden küçük", True)


def test_a_jpeg_whose_size_lies_past_64_kb_gives_no_finding(no_lookups):
    # Two 64 KB application segments before the size marker: the first 64 KB Maya reads do not hold it.
    segment = b"\xff\xe1" + struct.pack(">H", 65535) + b"\x00" * 65533
    jpeg = b"\xff\xd8" + segment * 2 + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 16, 16) + b"\x00" * 20
    outcome = audited({"/": page(title="Demo Kafe", head=og("/og.jpg")), "/og.jpg": image(jpeg, "image/jpeg")})
    assert str10(outcome, "smaller than") == [] and str10(outcome, "site icon") == []
    assert "image" not in outcome.result.structure.links[KAFE + "/og.jpg"]


def test_a_healthy_share_image_behind_a_same_site_redirect_gives_no_finding(no_lookups):
    routes = {"/": page(title="Demo Kafe", head=og("/eski-og.png")),
              "/eski-og.png": httpx.Response(301, headers={"location": "/og.png"}), "/og.png": image(png(1200, 630))}
    outcome = audited(routes)
    check = outcome.by_id["STR-10"]
    assert not [f for f in check.findings if "share image" in f.title or "og:image" in f.title]
    entry = outcome.result.structure.links[KAFE + "/eski-og.png"]
    assert entry["status"] == 200 and entry["hops"] == [{"url": KAFE + "/eski-og.png", "status": 301, "location": KAFE + "/og.png"}]
    assert entry["image"] == {"format": "png", "width": 1200, "height": 630}
    assert check.evidence["og_image_not_assessed_count"] == 0


# -- Item 7: invisible characters ------------------------------------------------------------------------------------------
WORDS = " ".join(f"kah​ve{n}" for n in range(12))  # 12 zero-width spaces, each inside a word


def test_twelve_zero_width_spaces_inside_words_in_the_main_text_are_reported(no_lookups):
    outcome = audited({"/": page(f"<p>{WORDS}</p>", title="Demo Kafe")})
    [found] = [f for f in outcome.by_id["STR-13"].findings if "invisible" in f.title]
    assert found.title == "1 page(s) have invisible characters in the main text (12 in all)"
    assert (found.severity.value, found.confidence.value) == ("S4", "verified") and "LG-82" in found.launch_gated
    row = found.evidence["pages"][0]
    assert row["inside_words"] == 12 and row["by_character"] == {"U+200B": 12} and row["examples"][0] == "kah[U+200B]ve0"
    assert wording.title("STR-13", found.title, "tr") == ("1 sayfanın ana metninde görünmez karakterler var (toplam 12)", True)
    assert wording.fix(found.how_to_fix, "tr")[1] and wording.expected(found.expected, "tr")[1]
    assert outcome.by_id["STR-13"].summary == "1 finding(s)."


def test_the_same_characters_in_the_footer_or_three_in_the_text_are_not_reported(no_lookups):
    footer = audited({"/": page(title="Demo Kafe", footer=f"<p>{WORDS}</p>")})
    assert not [f for f in footer.by_id["STR-13"].findings if "invisible" in f.title]
    few = audited({"/": page("<p>kah​ve sü­t ça⁠y</p>", title="Demo Kafe")})
    assert not [f for f in few.by_id["STR-13"].findings if "invisible" in f.title]
    home = next(p for p in few.result.pages if p.url == KAFE + "/")
    assert home.analysis["invisible_chars"]["count"] == 3
    emoji = audited({"/": page("<p>" + "\U0001F469‍\U0001F373 " * 12 + "</p>", title="Demo Kafe")})  # U+200D: not counted
    assert "invisible_chars" not in next(p for p in emoji.result.pages if p.url == KAFE + "/").analysis


# -- Item 8: links to other sites --------------------------------------------------------------------------------------------
LINKS = ''.join(f'<a href="https://{EXT}{path}">{path}</a>' for path in ("/gone", "/moved", "/head-405", "/private/x", "/fine"))


def ext_routes():
    head_405 = lambda n: httpx.Response(405) if n == 1 else answer(title="Dış")  # noqa: E731
    return {(EXT, "/gone"): answer(title="Yok", status=404), (EXT, "/moved"): httpx.Response(301, headers={"location": "/fine"}),
            (EXT, "/head-405"): head_405, (EXT, "/private/x"): answer(title="Gizli"), (EXT, "/fine"): answer(title="Dış")}


def ext_requests(outcome):
    return [(r.url.removeprefix(f"https://{EXT}"), r.purpose) for r in outcome.result.requests if r.url.startswith(f"https://{EXT}")]


def test_links_to_other_sites_are_asked_by_default_politely_and_only_404_or_410_is_broken(no_lookups):
    routes = {"/": page(LINKS, title="Demo Kafe"), "/menu": page(LINKS, title="Menü | Demo Kafe")} | ext_routes()
    outcome = audited(routes, sitemap=("/", "/menu"), robots={EXT: "User-agent: *\nDisallow: /private\n"})
    asked = ext_requests(outcome)
    assert asked[0] == ("/robots.txt", "robots")  # that site's robots.txt first
    assert "/private/x" not in [path for path, _ in asked]  # disallowed there
    assert asked[1:] == [("/gone", "external_link_head"), ("/moved", "external_link_head"), ("/head-405", "external_link_head"),
                         ("/head-405", "external_link_status"), ("/fine", "external_link_head"),
                         ("/gone", "external_link_status"), ("/fine", "external_link_status")]
    [gone] = [f for f in outcome.by_id["IDX-6"].findings if "other sites" in f.title]
    assert gone.title == "2 link(s) to other sites on 2 page(s) return 404 or 410"  # one address, linked from two pages
    assert (gone.severity.value, gone.confidence.value) == ("S4", "verified") and "LG-83" in gone.launch_gated
    assert [row["target"] for row in gone.evidence["links"]] == [f"https://{EXT}/gone"]
    assert gone.how_to_fix == "Update or remove these links; the pages they point to are gone."
    assert wording.title("IDX-6", gone.title, "tr") == ("2 sayfadaki diğer sitelere giden 2 bağlantı 404 ya da 410 döndürüyor", True)
    assert wording.fix(gone.how_to_fix, "tr")[1] and wording.expected(gone.expected, "tr")[1]
    evidence = outcome.by_id["IDX-6"].evidence["other_site_links"]
    assert evidence["working"] == 3 and evidence["gone"] == 1 and evidence["not_checked"] == {"robots": 1}
    summary = outcome.by_id["IDX-6"].summary
    assert " Links to other sites: 4 checked, 1 gone (404 or 410), 1 not checked. " in summary and wording.line(summary, "tr")[1]
    budget = outcome.result.structure.external
    assert budget["requests"] == 8 and budget["robots_requests"] == 1 and budget["cap"] == external_link_cap(100, 20, 2)
    assert outcome.int4.state == "compliant" and outcome.result.config["check_external_links"] is True


def test_the_cap_counts_robots_txt_and_the_most_linked_addresses_go_first(no_lookups):
    many = "".join(f'<a href="https://{EXT}/p/{n}">{n}</a>' for n in range(40))
    routes = {"/": page(many + f'<a href="https://{EXT}/popular">p</a>', title="Demo Kafe"),
              "/menu": page(f'<a href="https://{EXT}/popular">p</a>', title="Menü | Demo Kafe")}
    routes |= {(EXT, f"/p/{n}"): answer(title="Dış") for n in range(40)} | {(EXT, "/popular"): answer(title="Dış")}
    outcome = audited(routes, sitemap=("/", "/menu"))
    asked = ext_requests(outcome)
    cap = 20 + 2  # 20 + the two pages read
    assert len(asked) == cap and asked[0] == ("/robots.txt", "robots") and asked[1] == ("/popular", "external_link_head")
    assert outcome.by_id["IDX-6"].evidence["other_site_links"]["not_checked"] == {"cap": 41 - (cap - 1)}
    assert outcome.int4.state == "compliant"


def test_at_most_25_other_sites_are_asked():
    from maya_audit import external_links

    held = external_links.ExternalBudget(enabled=True, cap=100, sites_max=25, same_as_max=10)
    result = SimpleNamespace(_external=held, robots_policy_by_origin={}, pages=[])
    fetcher = SimpleNamespace(poll_stop=lambda: None, deadline_mono=None, log=[])
    held.sites = [f"https://site{n}.test" for n in range(25)]
    assert external_links.room(fetcher, result, CrawlConfig(), "https://another.test/x") == "sites_cap"
    assert external_links.verdict(404, None) == "broken" and external_links.verdict(301, None) == "works"
    assert [external_links.verdict(s, None) for s in (403, 429, 999, 503, 400)] == ["refused", "refused", "refused", "server_error", "other_status"]
    assert external_links.verdict(None, "host_not_found (x)") == "no_answer"


def test_same_as_links_are_asked_even_with_external_links_off_and_other_links_are_not(no_lookups):
    org = ('<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Organization", "name": "Demo Kafe", '
           f'"url": "{KAFE}/", "sameAs": ["https://{EXT}/gone", "https://{EXT}/fine"]}}</script>')
    routes = {"/": page(f'<a href="https://{EXT}/moved">x</a>', title="Demo Kafe", head=org)} | ext_routes()
    outcome = audited(routes, check_external_links=False)
    asked = ext_requests(outcome)
    assert asked == [("/robots.txt", "robots"), ("/gone", "external_link_head"), ("/fine", "external_link_head"), ("/gone", "external_link_status")]
    [dead] = [f for f in outcome.by_id["STR-5"].findings if "404/410" in f.title]
    assert [row["sameAs"] for row in dead.evidence["links"]] == [f"https://{EXT}/gone"]
    idx6 = outcome.by_id["IDX-6"]
    assert not [f for f in idx6.findings if "other sites" in f.title] and idx6.evidence["other_site_links"]["not_checked"] == {"off": 1}
    assert " Links to other sites were not checked (--no-external-links). " in idx6.summary and wording.line(idx6.summary, "tr")[1]
    assert outcome.int4.state == "compliant"


def test_healthy_links_to_other_sites_give_no_finding(no_lookups):
    links = "".join(f'<a href="https://{EXT}/ok/{n}">{n}</a>' for n in range(3))
    routes = {"/": page(links, title="Demo Kafe")} | {(EXT, f"/ok/{n}"): answer(title="Dış") for n in range(3)}
    outcome = audited(routes)
    idx6 = outcome.by_id["IDX-6"]
    assert idx6.findings == [] and idx6.status == "pass" and idx6.evidence["other_site_links"]["working"] == 3
    assert outcome.int4.state == "compliant"


def test_llms_txt_links_to_another_site_count_404_as_not_found_and_a_redirect_as_working(no_lookups):
    llms = f"# Demo\n\n- [Menü](/menu)\n- [Eski](https://{EXT}/gone)\n- [Taşındı](https://{EXT}/moved)\n"
    routes = {"/": page('<a href="/menu">Menü</a>', title="Demo Kafe"), "/menu": page(title="Menü | Demo Kafe"),
              "/llms.txt": httpx.Response(200, headers={"content-type": "text/plain"}, text=llms)} | ext_routes()
    outcome = audited(routes, sitemap=("/", "/menu"))
    [links] = [f for f in outcome.by_id["ACC-8"].findings if "do not work" in f.title]
    assert links.title == "1 of 3 link(s) in llms.txt lead to pages that do not work (not found)"
    rows = {row["url"]: row for row in outcome.result.access.llms[0]["links"]["rows"]}
    assert rows[f"https://{EXT}/moved"]["works"] and rows[f"https://{EXT}/gone"]["kind"] == "not_found"


def test_a_made_up_host_on_the_real_network_path_could_not_be_checked_and_changes_no_verdict():
    # A loopback fake server links to a host that does not exist. The fetcher's real path looks it up (the suite's
    # network guard refuses every public name): its robots.txt gets no answer, so the link is not asked and not broken.
    links = '<a href="https://made-up-elsewhere.example/page">x</a><a href="https://another-made-up.example/">y</a>'
    site = Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
                 "/": Response(body=f"<!doctype html><html lang='tr'><head><title>Demo Kafe</title></head><body><main>"
                                    f"<h1>Demo Kafe</h1><p>{TR}</p>{links}</main></body></html>")})
    with FakeServer(site) as server:
        outcome = run_audit(server.base_url + "/", CrawlConfig(request_delay_s=0, robots_samples=1, render_enabled=False,
                                                               prf_enabled=False, probes_enabled=False, refetch_delay_s=0))
    idx6 = {c.check_id: c for c in outcome.checks}["IDX-6"]
    assert idx6.findings == [] and idx6.evidence["other_site_links"]["not_checked"] == {"no_answer": 2}
    assert [r.purpose for r in outcome.result.requests if "made-up" in r.url] == ["robots", "robots"]
    assert outcome.result.stop_reason.value == "exhausted" and {g.check_id: g.state for g in outcome.gates}["INT-4"] == "compliant"
    assert {c.check_id: c for c in outcome.checks}["ACC-1"].status == "pass"


# -- the switch, the caps, the estimate, demo mode -------------------------------------------------------------------------
def config(*argv):
    return cli._crawl_config(cli._parser().parse_args(["crawl", KAFE + "/", *argv]))


def test_on_by_default_off_with_no_external_links_off_in_demo_mode_and_the_estimate_counts_them():
    assert config().check_external_links is True and config("--check-external-links").check_external_links is True
    assert config("--no-external-links").check_external_links is False
    assert external_link_cap(100, 20, 50) == 70 and external_link_cap(100, 20, 500) == 100 and external_link_cap(100, 20, 1, True) == 20
    assert estimated_duration_s(50, external_links=70) - estimated_duration_s(50) == 70 * 1.3
    assert config("--no-external-links").time_limit_s < config().time_limit_s
    assert demo.OVERRIDES["check_external_links"] is False
    real = runner.Engine()
    shown = runner.plan_shape(real, "quick", [])
    demo_engine = SimpleNamespace(overrides=demo.OVERRIDES, overrides_for=None, allow_loopback=True)
    demo_shape = runner.plan_shape(demo_engine, "quick", [])
    quick = runner.crawl_config(real, {"url": KAFE + "/", "mode": "quick", "key_pages": []}, None, resume=False)
    assert quick.check_external_links is True
    assert runner.crawl_config(demo_engine, {"url": KAFE + "/", "mode": "quick", "key_pages": []}, None, resume=False).check_external_links is False
    # The plan's "up to" minutes include the requests to other sites when they are on: 70 × 1.3 s, about 1.5 minutes.
    assert shown["up_to_minutes"] >= demo_shape["up_to_minutes"]


# -- IDX-5: the crawl's page cap is no gap when the sitemap check asked every URL ----------------------------------------
def test_idx5_keeps_the_page_cap_gap_only_when_the_sitemap_check_sampled(no_lookups):
    routes, paths = thirty()
    every = audited(routes, sitemap=paths, max_pages=5)  # the crawl stops at 5 pages; the sitemap check asks the rest
    assert every.result.stop_reason.value == "page_cap" and not every.result.index.sitemap_check.sampled
    assert not [p for p in every.by_id["IDX-5"].coverage["not_assessed"] if p["part"] == "pages found but not read"]
    # IDX-1 also uses its own response/probe population rather than a content-only cap.
    assert not [p for p in every.by_id["IDX-1"].coverage["not_assessed"] if p["part"] == "pages found but not read"]
    assert every.by_id["IDX-1"].evidence["assessment_scope"]["status_counts"]
    sampled = audited(routes, sitemap=paths, max_pages=5, sitemap_check_max=10)
    assert sampled.result.index.sitemap_check.sampled
    gaps = sampled.by_id["IDX-5"].coverage["not_assessed"]
    assert not [p for p in gaps if p["part"] == "pages found but not read"]
    assert any(p["part"] == "sitemap-listed URLs" and p["count"] == sampled.by_id["IDX-5"].evidence["listed_urls_not_fetched"] for p in gaps)
    assert sampled.by_id["IDX-5"].status in ("findings", "partial")
