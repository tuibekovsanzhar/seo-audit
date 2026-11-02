"""STR-16 (shared meta descriptions) and STR-17 (pages with no link onward): broken, healthy and near-miss sites.

Offline: fake server only.
"""
from test_review_fixes import TR, audit, page, short, unique

LONG = f"<p>{TR}</p><p>{TR}</p><p>{TR}</p><p>{TR}</p>"


def described(text, body="<h1>Sayfa</h1>" + LONG, **kw):
    return page(body, head=f'<meta name="description" content="{text}">' if text else "", **kw)


# STR-16 ---------------------------------------------------------------------------------------------------
def test_str16_groups_pages_that_share_a_description():
    shared, other = "Kliniğimiz hakkında bilgi alın.", "Online randevu için tıklayın."
    # Each page its own text: pages that are copies say their shared description under IDX-8 (decision 225).
    own = lambda name: "<h1>Sayfa</h1>" + f"<p>{unique(name, 200)}</p>"  # noqa: E731
    routes = {
        "/hizmet-a/": described(shared, own("a")), "/hizmet-b/": described("  KLİNİĞİMİZ   hakkında bilgi alın. ".replace("KLİNİĞİMİZ", "Kliniğimiz"), own("b")),
        "/hizmet-c/": described(shared, own("c")), "/x/": described(other, own("x")), "/y/": described(other, own("y")),
        "/tek/": described("Yalnızca bu sayfaya ait açıklama.", own("tek")), "/yok/": described("", own("yok")),
    }
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-16"]
    [finding] = check.findings
    assert finding.title == "2 meta description(s) are shared by 5 different indexable pages"
    assert (finding.severity.value, finding.confidence.value, finding.rationale) == ("S4", "verified", "Hypothesis")
    groups = finding.evidence["groups"]
    assert [g["count"] for g in groups] == [3, 2] and groups[0]["description"] == shared
    assert short(outcome, groups[0]["urls"]) == ["/hizmet-a/", "/hizmet-b/", "/hizmet-c/"]  # case and spacing do not hide a copy
    assert finding.scope["count"] == 5 and "/tek/" not in " ".join(finding.scope["urls"])
    assert check.evidence["pages_without_description"] == 2  # /yok/ and the homepage: STR-10's finding, not this one's
    assert any("hypothesis" in note for note in finding.notes)


def test_str16_passes_when_every_description_is_its_own():
    outcome = audit({f"/sayfa-{n}/": described(f"Sayfa {n} için ayrı bir açıklama.") for n in range(1, 5)}, image_checks_max=0)
    check = outcome.by_id["STR-16"]
    assert check.findings == [] and check.status in ("pass", "partial") and check.evidence["pages_compared"] == 4


def test_str16_does_not_count_declared_variants_or_pages_it_cannot_judge():
    same = "Aynı açıklama her yerde."
    alt = lambda other: f'<link rel="alternate" hreflang="en" href="{other}">'
    routes = {
        # Language versions that name each other: one page in two languages, not a duplicate.
        "/tr/urun/": page("<h1>Ürün</h1>" + LONG, head=f'<meta name="description" content="{same}">' + alt("/en/product/")),
        "/en/product/": page("<h1>Product</h1>" + LONG, lang="en", head=f'<meta name="description" content="{same}">'),
        # Declared variants: noindex, and a canonical pointing at another page.
        "/kopya-noindex/": page("<h1>Kopya</h1>" + LONG, head=f'<meta name="description" content="{same}"><meta name="robots" content="noindex">'),
        "/kopya-canonical/": page("<h1>Kopya</h1>" + LONG, head=f'<meta name="description" content="{same}"><link rel="canonical" href="/tr/urun/">'),
        # Page 2 of a list repeats page 1's head by design.
        "/liste/?sayfa=2": described(same),
    }
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-16"]
    assert check.findings == []
    assert check.evidence["pages_left_out"] == {"page 2, 3, ... of a list": 1, "language version of a page already counted": 1}
    [gap] = [part for part in check.coverage["not_assessed"] if part["part"] == "pages left out of this comparison"]
    assert gap["count"] == 2 and check.status == "partial"  # nothing found, but not everything was compared


def test_str16_leaves_out_a_page_cut_at_the_size_limit():
    same = "Aynı açıklama."
    big = described(same, body="<h1>Büyük</h1>" + LONG * 400)
    outcome = audit({"/a/": described(same), "/b/": big}, image_checks_max=0, max_body_bytes=40_000)
    check = outcome.by_id["STR-16"]
    assert check.findings == [] and check.evidence["pages_left_out"] == {"page cut at the size limit": 1}


# STR-17 ---------------------------------------------------------------------------------------------------
def alone(body, **kw):
    return page(body, nav="", **kw)


def test_str17_reports_a_page_that_links_nowhere_else_on_the_site():
    routes = {
        "/brosur/": alone("<h1>Broşür</h1>" + LONG + '<p><a href="https://baska-site.example/">Ortağımız</a> <a href="#ust">Yukarı</a> '
                          '<a href="/brosur/">Bu sayfa</a></p>'),
        "/normal/": page("<h1>Normal</h1>" + LONG),
    }
    outcome = audit(routes, image_checks_max=0)
    check = outcome.by_id["STR-17"]
    [finding] = check.findings
    assert finding.title == "1 page(s) have no link to any other page of this site"
    assert (finding.severity.value, finding.rationale) == ("Info", "Hypothesis")
    [row] = finding.evidence["pages"]
    assert row["url"].removeprefix(outcome.base) == "/brosur/" and row["links_to_other_sites"] == 1
    assert "nothing needs doing" in finding.how_to_fix  # an observation, never a mandatory fix


def test_str17_passes_when_every_page_leads_somewhere():
    outcome = audit({"/a/": page("<h1>A</h1>" + LONG), "/b/": alone("<h1>B</h1>" + LONG + '<a href="/a/">A sayfası</a>')}, image_checks_max=0)
    check = outcome.by_id["STR-17"]
    assert check.findings == [] and check.status in ("pass", "partial") and check.evidence["pages_left_out"] == {}


def test_str17_leaves_out_forms_endings_and_pages_whose_links_a_script_may_add():
    routes = {
        "/basvuru/": alone('<h1>Başvuru</h1>' + LONG + '<form action="/gonder"><input name="ad"><button type="submit">Gönder</button></form>'),
        "/tesekkurler/": alone("<h1>Teşekkürler</h1>" + LONG),
        "/belge/": alone("<h1>Belge</h1>" + LONG, title="Sipariş onay"),
        "/uygulama/": alone('<h1>Uygulama</h1>' + LONG + '<div id="menu"></div><script src="/menu.js"></script>'),
    }
    outcome = audit(routes, image_checks_max=0)  # rendering is off here, so the scripted page was never opened in a browser
    check = outcome.by_id["STR-17"]
    assert check.findings == []
    assert check.evidence["pages_left_out"] == {
        "page with a form": 1, "thank-you, confirmation, login, legal or cart page": 2,
        "runs scripts and was not opened in a browser, so its links may be added there": 1}
    [gap] = [part for part in check.coverage["not_assessed"] if part["part"] == "pages left out of this comparison"]
    assert gap["count"] == 4 and check.status == "partial"


def test_str17_has_nothing_to_say_about_a_one_page_site():
    outcome = audit({}, image_checks_max=0)
    assert outcome.by_id["STR-17"].status == "not_assessed" and "Only one indexable page" in outcome.by_id["STR-17"].summary


def test_the_new_checks_are_in_the_report_and_named_when_structure_data_is_unavailable():
    from maya_audit.report import build_report, render_markdown
    outcome = audit({"/a/": described("x"), "/b/": described("x")}, image_checks_max=0)
    report = build_report(outcome.result, outcome.gates, outcome.checks)
    ids = [c["check_id"] for c in report["checks"]]
    assert "STR-16" in ids and "STR-17" in ids and report["schema_version"] == "1.23"
    assert "STR-16" in render_markdown(outcome.result, outcome.gates, outcome.checks)
