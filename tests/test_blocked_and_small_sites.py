"""Blocked audits (who blocked, ACC-9), the http start address (IDX-2), and STR-18 to STR-23 for small sites.

Offline: the fake server, or an in-memory transport with name lookups stubbed so nothing leaves the machine.
"""
import json
import socket

import httpx
import pytest

from maya_audit.audit import run_audit
from maya_audit.classify import describe_blockers, identify_blocker
from maya_audit.config import CrawlConfig
from maya_audit.report import build_report, run_outcome
from test_review_fixes import QUIET, TR, audit, links, page, short

LONG = f"<p>{TR}</p><p>{TR}</p><p>{TR}</p><p>{TR}</p>"
ROBOTS = httpx.Response(200, text="User-agent: *\nAllow: /\n", headers={"content-type": "text/plain"})
HTML = {"content-type": "text/html; charset=utf-8"}


@pytest.fixture
def no_lookups(monkeypatch):
    """Names ending in .test never reach a resolver: the TLS probe then records 'not checked' and moves on."""
    real = socket.getaddrinfo

    def lookup(host, *args, **kwargs):
        if str(host).endswith(".test"):
            raise socket.gaierror(socket.EAI_NONAME, "not known")
        return real(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", lookup)


def run(respond, url="https://shop.test/", **options):
    outcome = run_audit(url, CrawlConfig(**{**QUIET, "max_pages": 10, **options}), httpx.MockTransport(respond))
    outcome.by_id = {check.check_id: check for check in outcome.checks}
    return outcome


def doc(body, title="Shop", head=""):
    return httpx.Response(200, headers=HTML, text=f'<!doctype html><html lang="en"><head><title>{title}</title>{head}</head>'
                                                 f'<body><header><nav><a href="/">Home</a></nav></header><main>{body}</main></body></html>')


# -- who blocked -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("status,headers,evidence,fetch_class,expected", [
    (403, {"server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "x"}, ["header cf-mitigated: challenge", "status 403"], "blocked",
     {"name": "Cloudflare", "kind": "bot challenge", "status": 403}),
    (403, {"server": "cloudflare"}, ["status 403 (access denied; bot protection vs. restricted page not determined)"], "blocked",
     {"name": "Cloudflare", "kind": "access denied", "status": 403}),
    (403, {"server": "AkamaiGHost"}, ["status 403 (access denied; ...)", "body signature akamai_access_denied: 'errors.edgesuite.net'"], "blocked",
     {"name": "Akamai", "kind": "bot challenge", "status": 403}),
    (403, {"server": "nginx", "x-datadome": "protected"}, ["status 403"], "blocked", {"name": "DataDome", "kind": "access denied", "status": 403}),
    (403, {"x-cdn": "Imperva"}, ["status 403"], "blocked", {"name": "Imperva", "kind": "access denied", "status": 403}),
    (403, {"server": "nginx"}, ["status 403 (access denied; ...)"], "blocked", {"name": None, "kind": "access denied", "status": 403}),
    (429, {"server": "nginx", "retry-after": "30"}, ["status 429"], "rate_limited", {"name": None, "kind": "rate limit", "status": 429}),
    (429, {"server": "cloudflare"}, ["status 429"], "rate_limited", {"name": "Cloudflare", "kind": "rate limit", "status": 429}),
])
def test_the_blocker_is_named_from_what_the_response_itself_says(status, headers, evidence, fetch_class, expected):
    assert identify_blocker(status, headers, evidence, fetch_class) == expected


def test_a_page_the_site_served_itself_has_no_blocker():
    assert identify_blocker(200, {"server": "cloudflare", "cf-ray": "x"}, ["status 200"], "ok") is None  # Cloudflare in front is not a block
    assert identify_blocker(None, {}, ["transport error: timeout"], "error") is None
    assert describe_blockers([]) == []


def challenged(request):
    return httpx.Response(403, headers={**HTML, "server": "cloudflare", "cf-mitigated": "challenge", "cf-ray": "a1-FRA"},
                          text="<html><title>Just a moment...</title><body>Checking your browser</body></html>")


def test_a_site_behind_a_challenge_gets_one_access_finding_that_names_the_blocker(no_lookups):
    outcome = run(challenged)
    assert run_outcome(outcome.result, outcome.gates)[1] == "DEGRADED"
    int1 = next(g for g in outcome.gates if g.check_id == "INT-1")
    assert int1.evidence["blocked_by"] == [{"name": "Cloudflare", "kind": "bot challenge", "status": 403, "responses": 1}]
    check = outcome.by_id["ACC-9"]
    [finding] = check.findings
    assert finding.title == ("The site blocks or challenges automated visitors: Cloudflare (bot challenge) answered 1 of 1 page "
                             "request(s). AI crawlers may be affected too")
    assert (finding.severity.value, finding.confidence.value, finding.scope["kind"]) == ("S3", "inferred", "sitewide")
    assert finding.evidence["pages_read"] == 0 and finding.evidence["start_url_blocked"] is True
    assert {"https://shop.test/robots.txt", "https://shop.test/sitemap.xml"} <= set(finding.evidence["robots_or_sitemap_also_refused"])
    assert "Maya-Audit" in finding.how_to_fix and "verify ownership" in finding.how_to_fix and "try again later" in finding.how_to_fix
    assert any("not tested here" in note for note in finding.notes) and any("does not try to get past" in note for note in finding.notes)
    assert "not_measured" in finding.evidence
    # Nothing was retried under another identity: every request carried Maya's own user agent, once per address.
    agents = {r.user_agent for r in outcome.result.requests}
    assert len(agents) == 1 and next(iter(agents)).startswith("Maya-Audit")
    pages = [r.url for r in outcome.result.requests if r.purpose == "page"]
    assert pages == ["https://shop.test/"]
    assert "blocked_by" in json.dumps(build_report(outcome.result, outcome.gates, outcome.checks)["gates"][0])


def test_a_plain_403_or_a_rate_limit_is_described_without_inventing_a_vendor(no_lookups):
    def denied(request):
        return ROBOTS if request.url.path == "/robots.txt" else httpx.Response(403, headers={**HTML, "server": "nginx"}, text="Forbidden")
    [finding] = run(denied).by_id["ACC-9"].findings
    assert "the site or its firewall (HTTP 403, access denied) answered 1 of 1" in finding.title
    assert finding.evidence["blocked_by"][0]["name"] is None and "https://shop.test/robots.txt" not in finding.evidence["robots_or_sitemap_also_refused"]

    def limited(request):
        return ROBOTS if request.url.path == "/robots.txt" else httpx.Response(429, headers={**HTML, "retry-after": "3600"}, text="slow down")
    [finding] = run(limited, rate_limit_stop_after=1).by_id["ACC-9"].findings
    # robots.txt served while every page got 429: a block on Maya's crawler (DECISIONS 288), still with no vendor made up.
    assert finding.title.startswith("Maya's crawler blocked (429 on pages): the site's firewall answered 1 of 1 page request(s)")
    assert finding.evidence["blocked_by"][0]["name"] is None


def test_a_site_that_lets_the_audit_in_passes_and_a_few_blocked_pages_are_a_low_finding(no_lookups):
    def open_site(request):
        if request.url.path == "/robots.txt":
            return ROBOTS
        if request.url.path == "/":
            return doc("<h1>Shop</h1>" + LONG + "".join(f'<a href="/p{n}">p{n}</a>' for n in range(1, 9)))
        if request.url.path == "/p3":
            return httpx.Response(403, headers={**HTML, "server": "nginx"}, text="members only")
        return doc(f"<h1>{request.url.path}</h1>" + LONG) if request.url.path.startswith("/p") else httpx.Response(404, headers=HTML, text="x")
    outcome = run(open_site)
    [finding] = outcome.by_id["ACC-9"].findings
    assert finding.severity.value == "S4" and finding.scope["count"] == 1 and finding.evidence["pages_read"] == 8
    assert run_outcome(outcome.result, outcome.gates)[1] != "DEGRADED"

    def all_open(request):
        return ROBOTS if request.url.path == "/robots.txt" else doc("<h1>Shop</h1>" + LONG) if request.url.path == "/" else httpx.Response(404, headers=HTML, text="x")
    clean = run(all_open).by_id["ACC-9"]
    assert clean.status == "pass" and clean.findings == []


# -- IDX-2: an address typed with http:// --------------------------------------------------------------------------
def test_idx2_does_not_report_a_missing_redirect_when_the_http_start_address_redirects_to_https(no_lookups):
    def respond(request):
        if request.url.scheme == "http":
            return httpx.Response(301, headers={"location": str(request.url.copy_with(scheme="https"))})
        return ROBOTS if request.url.path == "/robots.txt" else doc("<h1>Shop</h1>" + LONG) if request.url.path == "/" else httpx.Response(404, headers=HTML, text="x")
    outcome = run(respond, url="http://shop.test/")
    idx2 = outcome.by_id["IDX-2"]
    assert not [f for f in idx2.findings if "No HTTP to HTTPS redirect" in f.title]  # was reported, wrongly, on a real site
    [host] = outcome.result.index.hosts
    assert host["http_redirect"] == {**host["http_redirect"], "redirects_to_https": True, "status": 301, "location": "https://shop.test/",
                                     "seen_in": "the crawl's own request for the start URL"}


def test_idx2_still_reports_a_site_that_serves_http_without_redirecting(no_lookups):
    def respond(request):
        return ROBOTS if request.url.path == "/robots.txt" else doc("<h1>Shop</h1>" + LONG) if request.url.path == "/" else httpx.Response(404, headers=HTML, text="x")
    outcome = run(respond, url="http://shop.test/")
    [finding] = [f for f in outcome.by_id["IDX-2"].findings if "No HTTP to HTTPS redirect" in f.title]
    # One finding by the fact (decision 188): the probe's own reason stays in the evidence, and the line says what answered.
    [host] = finding.evidence["hosts"]
    assert finding.title == "No HTTP to HTTPS redirect on shop.test" and finding.severity.value == "S2"
    assert host["reason"] == "the audited start URL is served over plain http" and host["outcome"] == "served_on_http"
    assert host["line"] == "http://shop.test/ answers 200 without redirecting: the site is also served without encryption"
    assert outcome.result.index.hosts[0]["http_redirect"]["redirects_to_https"] is False


# -- STR-18: the homepage title and the brand ----------------------------------------------------------------------
def og(name):
    return f'<meta property="og:site_name" content="{name}">'


def test_str18_notes_a_homepage_title_without_the_brand_name():
    outcome = audit({"/": page(f"<h1>Hoş geldiniz</h1>{LONG}", title="Ana Sayfa | Hoş Geldiniz", head=og("Maksimum Enerji")),
                     "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0)
    [finding] = outcome.by_id["STR-18"].findings
    assert finding.title == "The homepage title does not name the brand ('Ana Sayfa | Hoş Geldiniz')" and finding.severity.value == "Info"
    assert finding.evidence["names_looked_for"][0] == "Maksimum Enerji" and "Maksimum Enerji" in finding.how_to_fix


def test_str18_passes_when_the_title_names_the_brand_in_any_spelling():
    for title in ("Maksimum Enerji: güneş panelleri", "MAKSİMUM ENERJİ", "Güneş panelleri | maksimum-enerji", "Enerji Maksimum"):
        outcome = audit({"/": page(f"<h1>X</h1>{LONG}", title=title, head=og("Maksimum Enerji")), "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0)
        assert outcome.by_id["STR-18"].findings == [], title


# -- STR-19: links that lead nowhere ------------------------------------------------------------------------------
def test_str19_reports_links_without_an_address_and_footer_entries_that_are_not_links():
    body = (f'<h1>Site</h1>{LONG}<a href="#">Daha fazla</a> <a href="javascript:void(0)">Aç</a> <a href="/gercek/">Gerçek</a>')
    footer = '<a>Kariyer</a> <a>Basın</a> <a href="/gizlilik/">Gizlilik</a>'
    routes = {"/a/": page(body, footer=footer), "/b/": page(body, footer=footer), "/gercek/": page(f"<h1>G</h1>{LONG}"),
              "/gizlilik/": page(f"<h1>Gizlilik</h1>{LONG}")}
    check = audit(routes, image_checks_max=0).by_id["STR-19"]
    by = {f.severity.value: f for f in check.findings}
    assert by["S4"].title == "4 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"
    assert by["S4"].evidence["pages_count"] == 2
    # How many of them each page has, so "Problems by page" can say a page's own number (schema 1.10).
    assert sorted((row["url"].rsplit("/", 2)[-2], row["links"]) for row in by["S4"].evidence["by_page"]) == [("a", 2), ("b", 2)]
    assert {(row["text"], row["why"], row["pages"]) for row in by["S4"].evidence["links"]} == {("Daha fazla", 'href="#"', 2), ("Aç", "javascript: address", 2)}
    assert by["Info"].title == "4 link(s) on 2 page(s) in the footer look like links but have no address"
    assert {row["text"] for row in by["Info"].evidence["links"]} == {"Kariyer", "Basın"}


def test_str19_does_not_count_script_driven_controls_anchors_with_a_target_or_named_anchors():
    body = (f'<h1>Site</h1>{LONG}<a href="#" aria-expanded="false" aria-controls="menu">Menü</a> <a href="#" role="button">Kapat</a>'
            '<a href="#bolum-2">Bölüm 2</a> <a href="#" data-bs-toggle="modal">Aç</a> <a name="ust"></a> <a id="capa"></a> <a href="/b/">B</a>')
    check = audit({"/a/": page(body), "/b/": page(f"<h1>B</h1>{LONG}<a>metin içinde adres yok</a>")}, image_checks_max=0).by_id["STR-19"]
    # None is a link a crawler should follow: no Low finding. The three controls are one accessibility note, never a problem.
    assert check.evidence["links_without_address"] == 0 and [f.severity.value for f in check.findings] == ["Info"]
    note = check.findings[0]
    assert note.title == '3 control group(s) use anchors; interaction and accessibility require review'
    assert {(row["text"], row["control_because"]) for row in note.evidence["controls"]} == {
        ("Menü", "aria-controls"), ("Kapat", 'role="button"'), ("Aç", "data-bs-toggle")}  # an <a> without href outside the footer is not reported


def test_str19_a_sign_in_control_is_an_accessibility_note_and_a_link_to_content_stays_low():
    """The maximum.com false alarm: "Log in" and "Forgot password?" open a sign-in window. Not an SEO problem."""
    body = (f'<h1>Site</h1>{LONG}<a href="#">Log in</a> <a href="#">Forgot password?</a> <a href="javascript:void(0)">Our services</a> '
            '<a href="#">Read more</a> <a href="/b/">B</a>')
    outcome = audit({"/a/": page(body), "/b/": page(f"<h1>B</h1>{LONG}")}, image_checks_max=0)
    check = outcome.by_id["STR-19"]
    low, note = check.findings
    assert low.severity.value == "S4" and low.title == "2 link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)"
    assert {row["text"] for row in low.evidence["links"]} == {"Our services", "Read more"}
    assert note.severity.value == "Info" and note.title == '2 control group(s) use anchors; interaction and accessibility require review'
    assert {row["text"] for row in note.evidence["controls"]} == {"Log in", "Forgot password?"} and note.evidence["seo_problem"] is False
    assert "accessibility note, not an SEO finding" in note.notes[0] and "Log in" not in json.dumps(low.evidence)
    assert check.summary == ("2 finding(s): 2 distinct element group(s) to content without an address a crawler can follow; 2 control(s) coded as links "
                             "(an accessibility note, not an SEO problem).")
    # Only the controls: nothing Low, and nothing for the action plan (a note never requires a fix).
    only = audit({"/a/": page(f'<h1>Site</h1>{LONG}<a href="#">Log in</a> <a href="#">Forgot password?</a>')}, image_checks_max=0).by_id["STR-19"]
    assert [f.severity.value for f in only.findings] == ["Info"] and only.evidence["links_without_address"] == 0


def test_str19_recognises_controls_by_label_in_english_and_turkish_by_markup_and_by_having_no_text():
    from maya_audit.analysis import control_by_text, control_marker, fold_text
    for label in ("Log in", "LOGIN", "Sign in", "Sign up", "Register", "Forgot password?", "Menu", "Search", "Close", "Cart", "Language",
                  "Giriş Yap", "GİRİŞ YAP", "giris yap", "Üye Ol", "ÜYE OL", "Şifremi unuttum", "ŞİFREMİ UNUTTUM", "Menü", "MENÜ", "Ara", "Kapat", "Sepet", ""):
        assert control_by_text(label), label
    for label in ("Our services", "Read more", "Daha fazla", "Hizmetlerimiz", "Search our catalogue of products", "Arama sonuçları hakkında",
                  "Cart abandonment guide", "Aramıza katılın", "Menu engineering for restaurants", "Kapatılan şubeler"):
        assert control_by_text(label) is None, label
    assert fold_text("  ŞİFREMİ  Unuttum? ") == "sifremi unuttum"
    marked = [{"role": "button"}, {"aria-haspopup": "dialog"}, {"aria-controls": "x"}, {"aria-expanded": "false"}, {"data-toggle": "modal"},
              {"data-bs-toggle": "offcanvas"}, {"data-modal": "login"}, {"data-micromodal-trigger": "m1"}, {"popovertarget": "p"}, {"onclick": "open()"}]
    assert all(control_marker({"href": "#", **attrs}) for attrs in marked) and control_marker({"href": "#", "class": "nav"}) is None
    body = (f'<h1>Site</h1>{LONG}<a href="#" aria-haspopup="dialog">Hesabınıza girin</a> <a href="#" data-modal="signup">Ücretsiz deneyin</a> '
            '<a href="#"><svg></svg></a> <a href="#">ŞİFREMİ UNUTTUM</a> <a href="#">Hizmetlerimiz</a>')
    check = audit({"/a/": page(body)}, image_checks_max=0).by_id["STR-19"]
    low, note = check.findings
    assert [row["text"] for row in low.evidence["links"]] == ["Hizmetlerimiz"]
    assert {(row["text"], row["control_because"]) for row in note.evidence["controls"]} == {
        ("Hesabınıza girin", "aria-haspopup"), ("Ücretsiz deneyin", "data-modal"), ("(no text)", "no text (an icon)"),
        ("ŞİFREMİ UNUTTUM", "label “ŞİFREMİ UNUTTUM”")}


# -- STR-20: the message in a video ---------------------------------------------------------------------------------
def test_str20_notes_a_page_whose_message_is_a_video_with_little_text():
    routes = {"/": page('<h1>Biz kimiz</h1><video autoplay muted loop src="/tanitim.mp4"></video><p>İzleyin.</p>', title="Firma"),
              "/kanal/": page('<h1>Tanıtım</h1><iframe src="https://www.youtube.com/embed/abc"></iframe>'),
              "/anlatim/": page(f'<h1>Ürün</h1><video controls src="/urun.mp4"></video>{LONG}')}
    check = audit(routes, image_checks_max=0).by_id["STR-20"]
    [finding] = check.findings
    assert finding.severity.value == "S4" and finding.title.startswith("2 page(s) carry their message in video or animation, with fewer than 80 words")
    rows = {row["url"].rsplit("0", 1)[-1][row["url"].rsplit("0", 1)[-1].find("/"):]: row for row in finding.evidence["pages"]}
    assert set(rows) == {"/", "/kanal/"} and rows["/"]["players"] == ["video"] and rows["/kanal/"]["video_embeds"]
    assert "transcript" in finding.how_to_fix  # the page with a video and enough text beside it is not listed


def test_str20_passes_without_players_and_for_short_pages_that_have_no_video():
    check = audit({"/a/": page("<h1>Kısa</h1><p>Yalnızca birkaç kelime.</p>"), "/b/": page(f"<h1>B</h1>{LONG}")}, image_checks_max=0).by_id["STR-20"]
    assert check.findings == [] and check.status in ("pass", "partial")  # a short page is STR-15's subject, not this one's


# -- STR-21: basic pages ------------------------------------------------------------------------------------------------
def test_str21_names_the_basic_pages_a_fully_read_site_does_not_have():
    routes = {"/hakkimizda/": page(f"<h1>Hakkımızda</h1>{LONG}"), "/blog/": page(f"<h1>Blog</h1>{LONG}")}
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-21"]
    [finding] = check.findings
    assert finding.title == "No Product or service / Contact / FAQ page was found among the 3 page(s) of the site"
    assert finding.severity.value == "Info" and finding.evidence["not_found"] == ["Product or service", "Contact", "FAQ"]
    assert short(outcome, check.evidence["found"]["About"]) == ["/hakkimizda/"]


def test_str21_recognises_basic_pages_by_address_title_or_heading_in_english_and_turkish():
    routes = {"/kurumsal/": page(f"<h1>Kurumsal</h1>{LONG}"), "/s/1/": page(f"<h1>Hizmetlerimiz</h1>{LONG}"),
              "/s/2/": page(f"<h1>Bize yazın</h1>{LONG}", title="İletişim"), "/sss/": page(f"<h1>Sorular</h1>{LONG}")}
    check = audit(routes, image_checks_max=0).by_id["STR-21"]
    assert check.findings == [] and check.status in ("pass", "partial") and all(check.evidence["found"].values())


def test_str21_does_not_call_a_page_missing_when_the_crawl_did_not_read_everything():
    routes = {f"/sayfa-{n}/": page(f"<h1>Sayfa {n}</h1>{LONG}") for n in range(1, 9)}
    check = audit(routes, image_checks_max=0, max_pages=3).by_id["STR-21"]
    assert check.status == "not_assessed" and check.findings == [] and "may exist" in check.summary


# -- STR-22: a newsroom of outside links -----------------------------------------------------------------------------
def news(count_outside, text=""):
    items = "".join(f'<li><a href="https://gazete-{n}.example/haber">Haber {n}</a></li>' for n in range(count_outside))
    return page(f"<h1>Basında Biz</h1>{text}<ul>{items}</ul>")


def test_str22_notes_a_press_page_that_is_only_links_to_other_sites():
    check = audit({"/basinda-biz/": news(6), "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0).by_id["STR-22"]
    [finding] = check.findings
    assert finding.title == "1 news or press page(s) consist of links to other sites, with little text of their own"
    [row] = finding.evidence["pages"]
    assert row["links_to_other_sites"] == 6 and row["words_of_its_own"] < 150 and finding.severity.value == "Info"


def test_str22_leaves_news_pages_with_their_own_text_and_sites_without_a_news_page():
    written = audit({"/haberler/": news(6, text=LONG), "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0).by_id["STR-22"]
    assert written.findings == [] and written.evidence["news_pages"] == 1
    few = audit({"/press/": news(2), "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0).by_id["STR-22"]
    assert few.findings == []  # two outside links are not a link list
    none = audit({"/a/": news(6)}, image_checks_max=0).by_id["STR-22"]
    assert none.findings == [] and none.evidence["news_pages"] == 0  # not a news page by its address


# -- STR-23: job pages -------------------------------------------------------------------------------------------------
JOB_LD = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Engineer",'
          '"description":"Build things","datePosted":"2026-09-01","hiringOrganization":{"@type":"Organization","name":"X"}}</script>')


def test_str23_notes_job_pages_without_jobposting_markup_and_not_the_careers_page_itself():
    routes = {"/kariyer/": page(f"<h1>Kariyer</h1>{LONG}" + links(["/kariyer/muhendis/", "/kariyer/satis/"])),
              "/kariyer/muhendis/": page(f"<h1>Mühendis</h1>{LONG}"), "/kariyer/satis/": page(f"<h1>Satış</h1>{LONG}", head=JOB_LD)}
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-23"]
    [finding] = check.findings
    assert finding.title == "1 job page(s) have no JobPosting structured data" and short(outcome, finding.scope["urls"]) == ["/kariyer/muhendis/"]
    assert check.evidence["job_pages"] == 2 and finding.severity.value == "Info"


def test_str23_passes_when_every_job_page_has_the_markup_or_there_are_none():
    marked = audit({"/jobs/engineer/": page(f"<h1>Engineer</h1>{LONG}", head=JOB_LD)}, image_checks_max=0).by_id["STR-23"]
    assert marked.findings == [] and marked.evidence["job_pages"] == 1
    none = audit({"/careers/": page(f"<h1>Careers</h1>{LONG}"), "/a/": page(f"<h1>A</h1>{LONG}")}, image_checks_max=0).by_id["STR-23"]
    assert none.findings == [] and none.evidence["job_pages"] == 0


def test_the_new_checks_are_reported_in_order_and_say_not_assessed_when_nothing_was_read(no_lookups):
    outcome = run(challenged)
    ids = [check.check_id for check in outcome.checks]
    assert ids[ids.index("ACC-8") + 1] == "ACC-9" and [f"STR-{n}" for n in range(18, 24)] == ids[ids.index("STR-18"):ids.index("STR-23") + 1]
    assert {outcome.by_id[f"STR-{n}"].status for n in range(18, 24)} == {"not_assessed"}  # nothing read: nothing claimed
