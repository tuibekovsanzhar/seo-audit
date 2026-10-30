"""team-preview-16, run 2: one cause is said once, and a cover says what stopped the audit (DECISIONS 215, 218, 225, 226;
LG-85).

- Empty pages are IDX-1's: IDX-5 keeps its share but takes them out of its pages and says how many were IDX-1's, or
  is left out when the rest is within its threshold; ACC-8 leaves them out; IDX-1 says where else they are listed and
  in which sections (decision 215).
- A page-scope problem whose line under a page would only repeat its title, on many pages, is said once in the first
  row of "Problems by page" (decision 218).
- IDX-8's groups of copies and near-copies are one finding with a line a group; a shared title or description inside
  one group is said on its line; the same problem on other pages is one row of the top problems and the action plan
  (decision 225).
- An audit stopped only by its page limit is a partial audit, said with its figures (decision 226).

Every site is made up and held in memory; nothing is fetched from the internet.
"""
import httpx

from maya_audit.findings import Finding, Severity, scope_for
from maya_audit.models import Confidence, to_jsonable
from maya_audit.report import detail_lines, detail_sentence, problem_summary, problems_by_page_lines, run_outcome
from maya_audit_web import practical, strings, summary, wording
from test_brand_and_launch_gate import no_lookups  # noqa: F401
from test_false_alarms import HTML_TYPE, KAFE, answer, audited
from test_wording import OPEN, run

EMPTY = httpx.Response(200, headers=HTML_TYPE, content=b"")
TEXT = {"content-type": "text/plain"}
EMPTIES = [f"/semt/{n}" for n in range(1, 7)] + [f"/sube/{n}" for n in range(1, 7)]
OKS = [f"/menu/{n}" for n in range(1, 21)]


def kafe(redirects: int):
    """demo-kafe.test: 12 empty pages under /semt/ and /sube/, all in the sitemap and in llms.txt; `redirects` old
    addresses in the sitemap that redirect; 20 fine menu pages."""
    old = [f"/eski/{n}" for n in range(1, redirects + 1)]
    routes = {"/": answer(title="Demo Kafe"), **{path: EMPTY for path in EMPTIES}, **{path: answer(title=f"Menü {path}") for path in OKS},
              **{path: httpx.Response(301, headers={"location": "/"}) for path in old},
              "/llms.txt": httpx.Response(200, headers=TEXT, text="# Demo Kafe\n\n" + "".join(f"- [Sayfa]({p})\n" for p in EMPTIES + ["/menu/1"]))}
    return audited(routes, sitemap=["/", *EMPTIES, *old, *OKS], max_pages=3)


def by_title(check, words):
    return [f for f in check.findings if words in f.title]


def test_empty_pages_in_the_sitemap_and_llms_txt_are_said_once_under_idx1_with_their_sections(no_lookups):
    outcome = kafe(redirects=8)
    empties = by_title(outcome.by_id["IDX-1"], "empty page")
    # Strength groups remain distinct; their union is still exactly the twelve root-cause URLs.
    assert len(empties) == 2
    assert set().union(*(set(f.scope["_all_urls"]) for f in empties)) == {KAFE + p for p in EMPTIES}
    assert sum(f.scope["count"] for f in empties) == 12
    [share] = by_title(outcome.by_id["IDX-5"], "not live")
    # The title's first number is the URLs left in the finding, as its scope says (review CR-28); the share keeps IDX-1's.
    assert share.title.startswith("8 of ") and " besides the 12 empty or failing page(s) reported under IDX-1 (" in share.title
    assert set(share.scope["_all_urls"]) == {f"{KAFE}/eski/{n}" for n in range(1, 9)} and share.evidence["reported_under_idx1"]["count"] == 12
    assert "LG-78" not in share.launch_gated or share.confidence == Confidence.ESTIMATED
    assert not by_title(outcome.by_id["ACC-8"], "do not work")
    assert outcome.by_id["ACC-8"].evidence["_root_cause"]["llms.txt"]["finding_id"] is None
    section_counts = {}
    for empty in empties:
        n = empty.scope["count"]
        also = empty.evidence["also_listed_in"]
        assert [(a["where"], a["count"], a["finding_id"]) for a in also] == [("sitemap", n, share.id), ("llms.txt", n, None)]
        lines = [detail_sentence(line) for line in detail_lines(to_jsonable(empty))]
        assert lines[:2] == [f"Also listed in the sitemap: {n} of these pages (IDX-5 counts them in its share).",
                            f"Also linked from llms.txt: {n} of these pages."]
        for section in empty.evidence.get("by_section", []):
            section_counts[section["section"]] = section_counts.get(section["section"], 0) + section["count"]
        strings.set_language("tr")
        try:
            shown = practical.details(to_jsonable(empty))
            assert shown[0] == f"Site haritasında da listeleniyor: bu sayfalardan {n} tanesi (IDX-5 bunları oranına katıyor)."
            assert shown[1] == f"llms.txt dosyasından da bağlantı veriliyor: bu sayfalardan {n} tanesi."
            turkish, ok = wording.title("IDX-5", share.title, "tr")
            assert ok and "IDX-1'de bildirilen 12 boş veya hatalı sayfa bunlara dahil değil" in turkish
        finally:
            strings.set_language("en")
    assert section_counts == {"/semt/": 6, "/sube/": 6}
    findings = [f for c in outcome.checks if not c.check_id.startswith("ANS") for f in c.findings]
    rows = problem_summary(to_jsonable(findings), {f.id: f.scope["_all_urls"] for f in findings}, pages_checked=3)
    # Each strength group is represented, never duplicated by IDX-5 or ACC-8.
    represented = set(rows["whole_site"]["finding_ids"]) | {fid for r in rows["by_page"] for fid in r["finding_ids"]}
    assert {f.id for f in empties} <= represented


def test_idx5_is_left_out_when_without_idx1s_pages_its_share_is_within_the_threshold(no_lookups):
    outcome = kafe(redirects=1)
    assert not by_title(outcome.by_id["IDX-5"], "not live")
    assert "which is within the threshold" in outcome.by_id["IDX-5"].summary
    empties = by_title(outcome.by_id["IDX-1"], "empty page")
    assert sum(f.scope["count"] for f in empties) == 12
    for empty in empties:
        n = empty.scope["count"]
        [sitemap] = [a for a in empty.evidence["also_listed_in"] if a["where"] == "sitemap"]
        assert sitemap == {"where": "sitemap", "count": n, "finding_id": None, "left_out": True}
        assert detail_sentence(detail_lines(to_jsonable(empty))[0]).startswith(f"Also listed in the sitemap: {n} of these pages. Without them")
    assert wording.line(outcome.by_id["IDX-5"].summary, "tr", check_id="IDX-5")[1]


def test_a_healthy_sitemap_with_three_redirects_and_no_empty_page_gives_the_same_idx5_finding_as_before(no_lookups):
    old = ["/eski/1", "/eski/2", "/eski/3"]
    routes = {"/": answer(title="Demo Kafe"), **{p: httpx.Response(301, headers={"location": "/"}) for p in old},
              **{p: answer(title=f"Menü {p}") for p in OKS[:10]}}
    outcome = audited(routes, sitemap=["/", *old, *OKS[:10]], max_pages=3)
    [share] = by_title(outcome.by_id["IDX-5"], "not live")
    assert share.title == "3 of 14 sitemap URL(s) (21%) are not live, indexable pages" and "reported_under_idx1" not in share.evidence
    assert not by_title(outcome.by_id["IDX-1"], "empty page")


def test_an_empty_page_only_llms_txt_links_to_is_idx1s_empty_page(no_lookups):
    routes = {"/": answer(title="Demo Kafe"), "/gizli": EMPTY, "/menu": answer(title="Menü"),
              "/llms.txt": httpx.Response(200, headers=TEXT, text="# Demo Kafe\n\n- [Gizli](/gizli)\n- [Menü](/menu)\n")}
    outcome = audited(routes, max_pages=1)
    assert "/gizli" in [r.url.removeprefix(KAFE) for r in outcome.result.requests if r.purpose == "llms_link_check"]
    [empty] = by_title(outcome.by_id["IDX-1"], "empty page")
    assert empty.scope["urls"] == [KAFE + "/gizli"]
    assert not by_title(outcome.by_id["ACC-8"], "do not work")


# -- many pages, one line (DECISIONS 218) -----------------------------------------------------------------------------------
CARD = "https://demo-kart.test"


def made(check_id, title, paths, evidence=None):
    return Finding(check_id, title, Severity.S4, Confidence.VERIFIED, "Hypothesis", ["all"], scope_for([CARD + p for p in paths]),
                   evidence or {}, "expected", "fix")


def test_a_problem_on_many_pages_whose_page_line_only_repeats_its_title_is_said_once_in_the_first_row():
    pages = [f"/kart/{n}" for n in range(50)]
    icon = made("STR-10", "50 page(s) use the site icon as share image (og:image is a .ico file)", pages)
    hidden = made("STR-13", "20 page(s) have invisible characters in the main text (31 in all)", pages[:20])
    share = made("RND-7", "33 page(s) have less than 30% of their text in the main content", pages[:33],
                 {"pages": [{"url": CARD + p, "main_share": 0.14} for p in pages[:33]]})
    few = made("STR-13", "4 page(s) have invisible characters in the main text (5 in all)", pages[:4])
    findings = [icon, hidden, share]
    summary_ = problem_summary(to_jsonable(findings), {f.id: f.scope["_all_urls"] for f in findings}, pages_checked=50)
    assert summary_["whole_site"]["finding_ids"] == [icon.id, hidden.id] and summary_["problems"] == 3
    assert {row["url"] for row in summary_["by_page"]} == {CARD + p for p in pages[:33]}
    assert all(row["finding_ids"] == [share.id] for row in summary_["by_page"])
    assert summary_["by_page"][0]["items"][0]["kind"] == "main_share" and not summary_["not_listed"]
    lines = problems_by_page_lines(summary_, {f.id: f.title for f in findings}, CARD, None)  # every page (the Markdown shows 25)
    assert sum("site icon as share image" in line for line in lines) == 1 and sum("Only 14%" in line for line in lines) == 33
    # Few pages, and not most of them: still on each page's row.
    small = problem_summary(to_jsonable([few]), pages_checked=50)
    assert small["whole_site"]["problems"] == 0 and len(small["by_page"]) == 4
    # Five pages of eight read: 60% or more, so said once.
    most = problem_summary(to_jsonable([made("STR-13", "5 page(s) have invisible characters in the main text (5 in all)", pages[:5])]),
                           pages_checked=8)
    assert most["whole_site"]["problems"] == 1 and most["by_page"] == []
    # The web's practical view and the PDF read the same rows.
    table = practical.by_page(summary_, [summary.item(f) for f in to_jsonable(findings)])
    assert table["rows"][0]["whole_site"] and len(table["rows"]) == 34


# -- copies and near-copies (DECISIONS 225) ---------------------------------------------------------------------------------
BANKA = "https://demo-banka.test"


def page_html(title, description, text):
    return httpx.Response(200, headers=HTML_TYPE, text=(
        f'<!doctype html><html lang="tr"><head><title>{title}</title><meta name="description" content="{description}"></head>'
        f'<body><header><nav><a href="/">Ana Sayfa</a></nav></header><main><h1>{title}</h1><p>{text}</p></main></body></html>'))


WORDS = ("Hesabınızdan fatura, vergi ve kart ödemelerini tek ekrandan yapabilir, talimat verebilir ve geçmiş işlemlerinizi "
         "dilediğiniz zaman görebilirsiniz. ") * 6
OTHER = ("Başka bir hesaba havale, EFT ve FAST ile para gönderebilir, kayıtlı alıcılarınızı yönetebilir ve dekontlarınızı "
         "indirebilirsiniz. ") * 6


def banka(**extra):
    groups = {f"/odemeler/{n}": page_html("Ödemeler | Demo Banka", "Ödemelerinizi kolayca yapın.", WORDS) for n in range(1, 5)}
    groups |= {f"/transferler/{n}": page_html("Transferler | Demo Banka", "Para transferi yapın.", OTHER) for n in range(1, 5)}
    groups |= extra
    home = answer("".join(f'<a href="{p}">{p}</a>' for p in groups), title="Demo Banka")
    return audited({"/": home, **groups}, start=BANKA + "/", max_pages=12)


def test_two_groups_of_four_copies_are_one_idx8_finding_with_a_line_a_group_and_nothing_from_str1_or_str16(no_lookups):
    outcome = banka()
    [merged] = outcome.by_id["IDX-8"].findings
    assert merged.title == "2 groups of indexable pages that are copies or near-copies of each other (8 pages)"
    assert merged.how_to_fix == ("For each group, keep one page and redirect the others to it, or give each page its own text, title and "
                                 "description.")
    lines = [detail_sentence(line) for line in detail_lines(to_jsonable(merged))]
    assert lines == ["/odemeler/1, /odemeler/2, /odemeler/3, /odemeler/4: same text, same title, same description",
                     "/transferler/1, /transferler/2, /transferler/3, /transferler/4: same text, same title, same description"]
    assert not by_title(outcome.by_id["STR-1"], "are shared by") and not by_title(outcome.by_id["STR-16"], "are shared by")
    assert "said with the copies and near-copies under IDX-8" in outcome.by_id["STR-1"].summary
    assert wording.title("IDX-8", merged.title, "en")[0] == "2 groups of indexable pages that are copies or near-copies of each other (8 pages)"
    strings.set_language("tr")
    try:
        assert wording.title("IDX-8", merged.title)[0] == "Dizine eklenebilir sayfalardan birbirinin kopyası veya neredeyse kopyası olan 2 grup (8 sayfa)"
        assert practical.details(to_jsonable(merged))[0] == "/odemeler/1, /odemeler/2, /odemeler/3, /odemeler/4: aynı metin, aynı başlık, aynı açıklama"
        assert wording.fix(merged.how_to_fix)[1] and wording.line(outcome.by_id["STR-1"].summary, "tr", check_id="STR-1")[1]
    finally:
        strings.set_language("en")
    # Each page's row says which group it is in.
    summary_ = problem_summary(to_jsonable([merged]), {merged.id: merged.scope["_all_urls"]}, pages_checked=9)
    row = next(r for r in summary_["by_page"] if r["url"] == BANKA + "/odemeler/1")
    assert row["items"][0]["kind"] == "duplicate_group" and row["items"][0]["values"]["others"] == 3
    assert "Copy or near-copy of 3 other pages (same text, same title, same description)" in "\n".join(
        problems_by_page_lines(summary_, {merged.id: merged.title}, BANKA))
    strings.set_language("tr")
    try:
        assert practical.page_line(row["items"][0]) == "3 başka sayfanın kopyası veya neredeyse kopyası (aynı metin, aynı başlık, aynı açıklama)"
    finally:
        strings.set_language("en")


def test_a_shared_title_on_two_pages_with_different_text_stays_str1s_finding(no_lookups):
    outcome = audited({"/": answer('<a href="/a">a</a><a href="/b">b</a>', title="Demo Banka"),
                       "/a": page_html("Kampanyalar | Demo Banka", "Bir.", WORDS), "/b": page_html("Kampanyalar | Demo Banka", "İki.", OTHER)},
                      start=BANKA + "/", max_pages=5)
    assert outcome.by_id["IDX-8"].findings == []
    [shared] = by_title(outcome.by_id["STR-1"], "are shared by")
    assert shared.title == "1 title(s) are shared by 2 different indexable pages"


def test_the_same_problem_on_other_pages_is_one_row_of_the_top_problems_and_the_action_plan():
    blocks = [made("STR-14", f"“div.post-related” block: 1 link(s) have no text (on {n} page(s) of /blog/)",
                   [f"/blog/{n}-{k}" for k in range(n)]) for n in (4, 3, 3)]
    # A merge requires matching semantic evidence, not just titles containing the same words.
    for f in blocks:
        f.evidence['shared_element'] = {'type':'link','href':'/same-target','block':'div.post-related','where':'repeated','pages':f.scope['count']}
    other = made("STR-2", "1 page(s) have no <h1>", ["/x"])
    rows = [summary.item(f) for f in to_jsonable([*blocks, other])]
    one = practical.merged(rows)
    assert len(one) == 2 and one[0]["merged_ids"] == [f.id for f in blocks]
    assert one[0]["title_shown"] == "“div.post-related” block: 1 link has no text (on 4 pages of /blog/) · div.post-related → /same-target: /blog/4-0, /blog/4-1, /blog/4-2 and 4 more"
    executive = practical.executive(rows, None, None, withheld=None)
    assert len(executive["problems"]) == 2 and executive["problems_total"] == 4
    assert len(practical.timeline(rows)[2]["items"]) + len(practical.timeline(rows)[1]["items"]) == 2
    strings.set_language("tr")
    try:
        assert practical.merged(rows)[0]["title_shown"].endswith("/blog/4-0, /blog/4-1, /blog/4-2 ve 4 tane daha")
    finally:
        strings.set_language("en")


# -- a partial audit (DECISIONS 226) ----------------------------------------------------------------------------------------
def test_an_audit_stopped_only_by_its_page_limit_is_a_partial_audit():
    result, gates = run(OPEN, "page_cap", "page cap of 3 reached", unread=9)
    result.config = {"max_pages": 3}
    code, label, sentence = run_outcome(result, gates)
    assert (code, label) == (3, "INCOMPLETE")
    assert sentence == "Partial audit: 3 of 12 known pages were read (the page limit of 3). Findings cover only the pages read."
    assert summary.outcome_label(label, sentence) == "Partial audit: 3 of 12 pages read (page limit)"
    strings.set_language("tr")
    try:
        assert summary.outcome_label(label, sentence) == "Kısmi denetim: 12 sayfanın 3 tanesi okundu (sayfa sınırı)"
        assert wording.outcome(sentence) == ("Kısmi denetim: bilinen 12 sayfanın 3 tanesi okundu (3 sayfalık sınır). Bulgular yalnızca "
                                             "okunan sayfaları kapsar.", True)
    finally:
        strings.set_language("en")


def test_a_page_limit_and_a_time_limit_is_still_an_incomplete_audit():
    result, gates = run(OPEN, "page_cap", "page cap of 3 reached", unread=9, deadline=True)
    code, label, sentence = run_outcome(result, gates)
    assert (code, label) == (3, "INCOMPLETE") and sentence.startswith("The audit finished but is incomplete (")
    assert summary.outcome_label(label, sentence) == "Audit incomplete"


def test_near_copies_merged_keep_idx8s_launch_gate_items_and_a_second_run_changes_nothing():
    from types import SimpleNamespace

    from maya_audit import launch_gate, root_cause
    from maya_audit.findings import CheckResult

    near = [Finding("IDX-8", f"{n} indexable pages have nearly identical main content (estimate)", Severity.S4, Confidence.ESTIMATED,
                    "Hypothesis", ["all"], scope_for([f"{BANKA}/{name}/{k}" for k in range(n)]),
                    {"urls": [f"{BANKA}/{name}/{k}" for k in range(n)], "variant_like": name == "urun", "pairs": []}, "expected", "fix")
            for n, name in ((3, "sayfa"), (2, "urun"))]
    titles = Finding("STR-1", "1 title(s) are shared by 2 different indexable pages", Severity.S4, Confidence.VERIFIED, "Hypothesis",
                     ["all"], scope_for([f"{BANKA}/urun/0", f"{BANKA}/urun/1"]),
                     {"groups": [{"title": "Ürün", "urls": [f"{BANKA}/urun/0", f"{BANKA}/urun/1"]}]}, "expected", "fix")
    checks = [CheckResult("IDX-8", "Duplicates", "findings", "2 duplicate group(s) among 9 indexable self-canonical page(s).", list(near)),
              CheckResult("STR-1", "Titles", "findings", "1 finding(s).", [titles])]
    root_cause.group(checks, SimpleNamespace(sitemap_urls=[]))
    launch_gate.apply(checks)
    [merged] = checks[0].findings
    assert merged.title == "2 groups of indexable pages that are copies or near-copies of each other (5 pages)"
    assert {"LG-21", "LG-41", "LG-69"} <= set(merged.launch_gated) and merged.confidence == Confidence.ESTIMATED
    lines = [detail_sentence(line) for line in detail_lines(to_jsonable(merged))]
    assert lines[0] == "/sayfa/0, /sayfa/1, /sayfa/2: nearly the same main content"
    assert lines[1].startswith("/urun/0, /urun/1: nearly the same main content, same title. These look like variants of one product")
    assert checks[1].findings == [] and checks[1].status == "pass"
    before = (merged.id, merged.title, list(merged.launch_gated), checks[1].summary)
    root_cause.group(checks, SimpleNamespace(sitemap_urls=[]))
    launch_gate.apply(checks)
    assert (checks[0].findings[0].id, checks[0].findings[0].title, list(checks[0].findings[0].launch_gated), checks[1].summary) == before
