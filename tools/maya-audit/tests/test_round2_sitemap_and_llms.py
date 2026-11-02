"""Round 2, run 3: every sitemap URL is checked, failed sitemap files and wrongly written addresses are reported, and
the links of llms.txt are followed (DECISIONS 206, 208; LG-78, LG-79, LG-80).

- IDX-5 judges every sitemap URL: the crawl's for free, the rest with one light request each (at most 64 KB, no
  redirect followed), at most 100 (Quick) or 300 (Standard) since DECISIONS 294, a sample spread over the sitemap files
  (one file: over the site's sections) above that, the same every run. A 429 backs off (DECISIONS 294); the third stops
  the light requests and the rest is said as not checked.
- A sitemap file named in robots.txt or a sitemap index that cannot be loaded is S3; the /sitemap.xml guess is not.
- An address with a "?" where a letter was lost, or a space, is S3, with the word it probably is; an address with
  letters that are not percent-encoded is Info.
- ACC-8 reads llms.txt whole (up to 1 MB), follows its links to this site and says which lead nowhere, and says when
  the file does not open with a "# " title line.

Every site is made up and held in memory; nothing is fetched from the internet.
"""
from types import SimpleNamespace

import httpx

from maya_audit import cli
from maya_audit.checks.index import _failed_sitemap_files
from maya_audit.config import estimated_duration_s
from maya_audit.index_data import malformed, section_sample
from maya_audit.models import SitemapDoc
from maya_audit_web import runner, wording
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import HTML_TYPE, KAFE, answer, audited

EMPTY = httpx.Response(200, headers=HTML_TYPE, content=b"")
OK = answer(title="Ürün | Demo Kafe")


def light(outcome, purpose="sitemap_check"):
    return [r.url.removeprefix(KAFE) for r in outcome.result.requests if r.purpose == purpose]


def idx5(outcome, words):
    return [f for f in outcome.by_id["IDX-5"].findings if words in f.title]


# -- the whole sitemap --------------------------------------------------------------------------------------------------
def thirty():
    """A made-up sitemap of 30 URLs over three sections: redirects, missing pages, empty pages, noindex and fine ones."""
    paths = ["/"] + [f"/urun/{n}" for n in range(1, 13)] + [f"/blog/{n}" for n in range(1, 10)] + [f"/kat/{n}" for n in range(1, 9)]
    noindex = httpx.Response(200, headers=HTML_TYPE, text='<!doctype html><html><head><title>Gizli</title>'
                             '<meta name="robots" content="noindex"></head><body><p>Gizli sayfa metni.</p></body></html>')
    routes = {"/": answer(title="Demo Kafe")}
    for path in paths[1:]:
        n = int(path.rsplit("/", 1)[1])
        routes[path] = (httpx.Response(301, headers={"location": "/"}) if path.startswith("/kat/") and n % 2
                        else EMPTY if path.startswith("/urun/") and n % 4 == 0
                        else noindex if path.startswith("/blog/") and n % 3 == 0
                        else OK if not path.startswith("/blog/") or n % 2 else None)
    return {p: r for p, r in routes.items() if r is not None}, paths


def test_a_sitemap_larger_than_the_cap_is_sampled_over_its_sections_the_same_way_every_run(no_lookups):
    routes, paths = thirty()
    first = audited(routes, sitemap=paths, sitemap_check_max=10)
    asked = light(first)
    assert len(asked) == 10 and len(set(asked)) == 10
    # One from each section in turn, each in sitemap order.
    sections = [p.split("/")[1] for p in asked]
    assert sections[:3] == sorted(set(sections[:3]), key=sections[:3].index) and len(set(sections[:3])) == 3
    [share] = idx5(first, "are not live, indexable pages")
    checked = share.evidence["sitemap_check"]["checked"]
    # Two empty responses plus two recorded HTTP404s are already IDX-1's (nine-corrections #5).
    assert share.title.endswith("with them); the sitemap lists 30") and f"of {checked} sitemap URL(s) checked" in share.title
    assert "are not live, indexable pages besides the 4 empty or failing page(s) reported under IDX-1 (" in share.title
    assert share.confidence.value == "estimated" and "LG-78" in share.launch_gated
    crawled = share.evidence["sitemap_check"]["checked_by_crawl"]
    assert share.notes == [f"The sitemap lists 30 URLs; {checked} were checked ({crawled} read by the crawl, 10 with one light request "
                           "each, a sample spread over the site's sections). The share is of the URLs checked and is an estimate "
                           "for the whole sitemap."]
    assert set(share.evidence["breakdown"]["not_live"]) == {"redirect", "not_found", "server_error", "empty", "noindex"}
    # The unassessed sitemap population is explicit; it is not the content-read cap.
    # Sampling fairness, measured share, raw counts and confidence above remain unchanged.
    gaps = [p for p in first.by_id["IDX-5"].coverage["not_assessed"] if p["part"] == "sitemap-listed URLs"]
    assert len(gaps) == 1 and gaps[0]["count"] == share.evidence["sitemap_check"]["not_checked"]
    assert "sitemap request cap" in gaps[0]["reason"]
    assert not any(p["part"] == "pages found but not read" for p in first.by_id["IDX-5"].coverage["not_assessed"])
    second = audited(routes, sitemap=paths, sitemap_check_max=10)
    assert light(second) == asked
    # Shown in Turkish, note and title.
    assert wording.title("IDX-5", share.title, "tr")[1] and wording.note(share.notes[0], "tr")[1]
    assert first.int4.state == "compliant"


def test_a_cap_above_the_sitemap_checks_every_url_and_says_of_n(no_lookups):
    routes, paths = thirty()
    outcome = audited(routes, sitemap=paths)  # cap 200: every URL the crawl did not read is asked once
    crawled = {p.url.removeprefix(KAFE) for p in outcome.result.pages}
    assert sorted(light(outcome)) == sorted(set(paths) - crawled)
    [share] = idx5(outcome, "are not live, indexable pages")
    same = share.evidence["reported_under_idx1"]["count"]
    # The first number is the URLs left in the finding (review CR-28); the share in brackets still counts IDX-1's.
    assert share.title.startswith(f"{len(share.evidence['bad_urls'])} of 30 sitemap URL(s) are not live") and share.confidence.value == "verified"
    assert same == 5 and " besides the 5 empty or failing page(s) reported under IDX-1 (" in share.title
    # Keep a distinct, unrepresented failure in the sitemap review; do not exclude all error observations.
    assert KAFE+'/blog/8' in share.scope['_all_urls']
    assert "LG-78" not in share.launch_gated and not share.notes
    assert wording.title("IDX-5", share.title, "tr")[0].startswith("30 site haritası URL'sinin")
    # An empty page found by a light request is IDX-1's empty page too.
    empty = [f for f in outcome.by_id["IDX-1"].findings if "empty page" in f.title]
    assert {KAFE + f"/urun/{n}" for n in (4, 8, 12)} <= {u for f in empty for u in f.scope["_all_urls"]}
    # Probes are off in these audits, so the crawled empty pages are not asked again as a browser (first review C1/C2).
    assert {f.evidence["observation_strength"] for f in empty} == {"repeated_empty_same_client_only",
                                                                   "single_probe_or_missing_corroboration"}


def test_one_429_backs_off_and_the_light_requests_go_on(no_lookups):
    # DECISIONS 294 (Owner, 2026-11-02; replaces "a 429 stops them" for the sitemap check): the gap widens, the shared
    # site limit steps down, and the other URLs are still asked.
    paths = ["/"] + [f"/sayfa/{n}" for n in range(1, 21)]
    routes = {p: OK for p in paths} | {"/sayfa/12": httpx.Response(429, text="slow down")}
    outcome = audited(routes, sitemap=paths, max_pages=3)
    asked = light(outcome)
    assert "/sayfa/12" in asked and len(asked) == len(set(asked)) == 18
    data = outcome.result.index.sitemap_check
    assert data.stopped_because is None and data.rate_limited == 1 and "rate_limit" not in data.not_checked
    limit = outcome.result.backoff["site_limit"]
    assert limit["final"] < limit["configured"] and limit["backed_off"][0]["reason"] == "429"


def test_three_429s_stop_the_light_requests_and_the_rest_is_not_checked(no_lookups):
    paths = ["/"] + [f"/sayfa/{n}" for n in range(1, 21)]
    routes = {p: OK for p in paths} | {f"/sayfa/{n}": httpx.Response(429, text="slow down") for n in (6, 9, 12)}
    outcome = audited(routes, sitemap=paths, max_pages=3)
    data = outcome.result.index.sitemap_check
    assert data.stopped_because == "rate_limit" and data.rate_limited == 3 and data.not_checked["rate_limit"] >= 1
    parts = outcome.by_id["IDX-5"].coverage["not_assessed"]
    assert any("429" in p["reason"] and p["count"] == data.not_checked["rate_limit"] for p in parts)
    assert outcome.by_id["IDX-5"].status == "partial"


def test_a_healthy_sitemap_gives_no_finding_and_a_page_query_is_not_a_malformed_address(no_lookups):
    paths = ["/", "/menu", "/iletisim", "/blog?page=2", "/blog?amp"]
    outcome = audited({p.split("?")[0]: OK for p in paths}, sitemap=paths, max_pages=2)
    assert light(outcome) and outcome.by_id["IDX-5"].findings == []
    # The crawl stopped at its page cap, but the sitemap check asked every URL it did not read: IDX-5 has no gap (run 4).
    assert outcome.result.stop_reason.value == "page_cap" and outcome.by_id["IDX-5"].coverage["not_assessed"] == []
    assert outcome.by_id["IDX-5"].status == "pass"
    assert malformed(KAFE + "/blog?page=2") is None and malformed(KAFE + "/blog?amp") is None


# -- sitemap files that could not be loaded ---------------------------------------------------------------------------
def test_a_file_named_in_the_sitemap_index_that_answers_404_is_reported_and_the_guess_never_is(no_lookups):
    index = httpx.Response(200, headers={"content-type": "application/xml"}, text=(
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>{KAFE}/a-sitemap.xml</loc></sitemap><sitemap><loc>{KAFE}/b-sitemap.xml</loc></sitemap></sitemapindex>"))
    urlset = httpx.Response(200, headers={"content-type": "application/xml"}, text=(
        f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{KAFE}/</loc></url></urlset>'))
    outcome = audited({"/": answer(title="Demo Kafe"), "/index.xml": index, "/a-sitemap.xml": urlset},
                      robots={"demo-kafe.test": f"User-agent: *\nAllow: /\nSitemap: {KAFE}/index.xml\n"})
    [failed] = idx5(outcome, "could not be loaded")
    assert failed.title == "1 sitemap file(s) named in the sitemap index or robots.txt could not be loaded"
    assert failed.severity.value == "S3" and failed.scope["kind"] == "sitewide"
    assert failed.evidence["files"][0]["url"] == KAFE + "/b-sitemap.xml" and failed.evidence["files"][0]["status"] == 404
    assert failed.evidence["files"][0]["named_in"] == f"sitemap index {KAFE}/index.xml"
    assert wording.title("IDX-5", failed.title, "tr") == ("Site haritası dizininde ya da robots.txt'de adı geçen 1 site haritası "
                                                         "dosyası yüklenemedi", True)
    # The /sitemap.xml Maya asks for on its own is never reported, whatever it answers.
    guessed = SimpleNamespace(sitemap_docs=[SitemapDoc(KAFE + "/sitemap.xml", 404, None, None, 0)],
                              _sitemap_named_in={KAFE + "/sitemap.xml": "guess"})
    assert _failed_sitemap_files(guessed) == []


# -- addresses written wrongly ----------------------------------------------------------------------------------------
def test_wordlike_query_is_uncertain_not_a_proven_lost_letter(no_lookups):
    home = answer("<p>Taksitli ödeme seçenekleri.</p>", title="Demo Kafe")
    paths = ["/", "/?deme-erteleme-ve-hesaplama", "/k/g?rgen?ler-y", "/blog?page=2", "/menü"]
    outcome = audited({"/": home, "/menü": OK}, sitemap=paths)
    [wrong] = idx5(outcome, "word-like queries")
    assert wrong.title == "2 sitemap URL(s) use word-like queries; intended paths are unassessed"
    assert wrong.severity.value == "Info" and wrong.confidence.value == 'inferred'
    assert sorted(wrong.scope["urls"]) == sorted([KAFE + "/?deme-erteleme-ve-hesaplama", KAFE + "/k/g?rgen?ler-y"])
    assert 'valid query' in wrong.notes[0] and wording.note(wrong.notes[0], 'tr')[1]
    assert not idx5(outcome, 'written wrongly')
    [raw] = idx5(outcome, "not percent-encoded")
    assert raw.severity.value == "Info" and raw.scope["urls"] == [KAFE + "/menü"]
    for finding in (wrong, raw):
        assert wording.title("IDX-5", finding.title, "tr")[1]


def test_with_no_word_found_the_general_sentence_is_said():
    assert section_sample([KAFE + "/a/1", KAFE + "/a/2", KAFE + "/b/1"], 2) == [KAFE + "/a/1", KAFE + "/b/1"]
    from maya_audit.checks.index import _malformed_sitemap_urls
    result = SimpleNamespace(sitemap_urls=[KAFE + "/?zzz-q"], pages=[])
    [finding] = _malformed_sitemap_urls(result)
    assert finding.severity.value == 'Info' and 'valid query' in finding.notes[0]
    assert wording.note(finding.notes[0], 'tr')[1]


# -- the caps, from the command line and the web modes ------------------------------------------------------------------
def caps(*argv):
    return cli._crawl_config(cli._parser().parse_args(["crawl", KAFE + "/", *argv]))


def test_the_cap_is_100_quick_300_standard_0_single_page_and_the_estimate_grows_with_it():
    # DECISIONS 294 (Owner, 2026-11-02): 300 in Standard and 100 in Quick (were 1,000 and 200).
    assert caps().sitemap_check_max == 100 and caps("--max-pages", "500").sitemap_check_max == 300
    assert caps("--single-page").sitemap_check_max == 0 and caps("--sitemap-check-max", "7").sitemap_check_max == 7
    assert estimated_duration_s(50, sitemap_check=200) - estimated_duration_s(50) == 200 * 1.3
    engine = SimpleNamespace(overrides={}, overrides_for=None, allow_loopback=True)
    for mode, cap in (("single", 0), ("quick", 100), ("standard", 300)):
        config = runner.crawl_config(engine, {"url": KAFE + "/", "mode": mode, "key_pages": []}, None, resume=False)
        assert config.sitemap_check_max == cap, mode
    import pytest
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["crawl", KAFE + "/", "--sitemap-check-max", "1001"])


# -- llms.txt -------------------------------------------------------------------------------------------------------------
LLMS = "Generated by a made-up plugin 1.0\n\n# Demo\n\n- [Boş](/bos)\n- [Eski](/eski): taşındı\n- [Menü](/menu)\n- [Dış](https://ext.test/x)\n"


def test_llms_txt_links_that_lead_nowhere_and_a_first_line_that_is_not_a_title(no_lookups):
    routes = {"/": answer(title="Demo Kafe"), "/llms.txt": httpx.Response(200, headers={"content-type": "text/plain"}, text=LLMS),
              "/bos": EMPTY, "/eski": httpx.Response(301, headers={"location": "/menu"}), "/menu": OK}
    routes[("ext.test", "/x")] = OK
    outcome = audited(routes)
    assert sorted(light(outcome, "llms_link_check")) == ["/bos", "/eski", "/menu"]
    # Another site's link goes through the other-site check (run 4, DECISIONS 211): its robots.txt first, one HEAD.
    assert [path for host, path in outcome.asked if host == "ext.test"] == ["/robots.txt", "/x"]
    check = outcome.by_id["ACC-8"]
    # Accuracy round: a redirect with an observed healthy destination is not broken.
    # The genuinely empty page is still detected by IDX-1; no duplicate warning under ACC-8.
    assert not [f for f in check.findings if "do not work" in f.title]
    assert any("empty page" in f.title for f in outcome.by_id["IDX-1"].findings)
    rows = outcome.result.access.llms[0]["links"]["rows"]
    moved = next(r for r in rows if r["url"] == KAFE + "/eski")
    assert moved["works"] is True and moved["final_url"] == KAFE + "/menu"
    assert next(r for r in rows if r["url"] == KAFE + "/bos")["works"] is False
    [first] = [f for f in check.findings if "title line" in f.title]
    assert first.severity.value == "Info" and first.notes == ["First line: “Generated by a made-up plugin 1.0”."]
    assert wording.note(first.notes[0], "tr")[1] and wording.title("ACC-8", first.title, "tr")[1]
    entry = outcome.result.access.llms[0]
    assert entry["links"]["found"] == 4 and entry["links"]["other_site"] == 1 and entry["links"]["checked"] == 4
    assert not [p for p in check.coverage["not_assessed"] if p["part"] == "links in llms.txt"]
    assert outcome.int4.state == "compliant"


def test_at_most_50_llms_links_are_asked_and_a_healthy_file_is_presence_only(no_lookups):
    many = "# Demo\n" + "".join(f"- [Sayfa {n}](/s/{n})\n" for n in range(1, 81))
    routes = {"/": answer(title="Demo Kafe"), "/llms.txt": httpx.Response(200, headers={"content-type": "text/plain"}, text=many)}
    routes |= {f"/s/{n}": OK for n in range(1, 81)}
    outcome = audited(routes)
    assert len(light(outcome, "llms_link_check")) == 50
    assert outcome.result.access.llms[0]["links"]["not_checked"] == {"cap": 30}

    healthy = "# Demo\n\n- [Menü](/menu)\n- [İletişim](/iletisim)\n"
    outcome = audited({"/": answer('<a href="/menu">Menü</a>', title="Demo Kafe"), "/menu": OK, "/iletisim": OK,
                       "/llms.txt": httpx.Response(200, headers={"content-type": "text/plain"}, text=healthy)})
    assert [f.title for f in outcome.by_id["ACC-8"].findings] == ["llms.txt is present"]
    assert outcome.by_id["ACC-8"].status == "findings" and outcome.result.access.llms[0]["links"]["checked"] == 2


def test_a_single_page_audit_reads_llms_txt_but_asks_for_no_link_and_no_sitemap_url(no_lookups):
    routes = {"/": answer(title="Demo Kafe"), "/llms.txt": httpx.Response(200, headers={"content-type": "text/plain"}, text=LLMS),
              "/bos": EMPTY, "/menu": OK}
    outcome = audited(routes, sitemap=("/", "/menu"), single_page=True, max_pages=1)
    assert light(outcome, "llms_link_check") == [] and light(outcome) == []
    titles = [f.title for f in outcome.by_id["ACC-8"].findings]
    assert titles == ["llms.txt is present", "llms.txt does not open with a “# ” title line"]
    assert outcome.by_id["ACC-8"].findings[1].scope["kind"] == "sitewide"  # said as site-level in every output
    assert outcome.by_id["IDX-5"].status == "not_assessed"
