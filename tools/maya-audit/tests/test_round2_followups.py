"""Round 2, run 1: the batch's brand, the label on the printed lists, the browser step, and where RND-7 is filed
(DECISIONS 207, 212, 213, 214; docs/FALSE-ALARMS.md FA-024).

- `batch` uses the name in the CSV as the brand, as `crawl --dfs-brand` does; `crawl` without a typed name still takes
  the site's own name.
- The printed report puts "Unverified check (LG-…)" after a note's title and after a top problem's title, in English
  and Turkish; a note of a validated rule has no label.
- The team guide's step 5 cannot be skipped by mistake, and Playwright is capped below the version not yet retested.
- RND-7, the main content's share of the page text, is shown under page structure, not JavaScript rendering, in a new
  report and in a saved one; its fix says no JavaScript change is needed. RND-1 stays under JavaScript rendering.

Every site is made up and held in memory or served on loopback; nothing is fetched from the internet.
"""
import json
import re
import tomllib
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from fakeserver.server import Response, Site  # noqa: E402
from maya_audit import cli  # noqa: E402
from maya_audit.report import build_report  # noqa: E402
from maya_audit_web import pdf, practical, strings, summary, wording  # noqa: E402
from test_batch import Sites, brands_file  # noqa: E402
from test_brand_and_launch_gate import no_lookups, page, shown  # noqa: E402,F401
from test_deadline_hosted_hardening import QUIET, _audit_site  # noqa: E402,F401
from test_false_alarms import HTML_TYPE, TR, audited  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NEW_FIX = 'Inspect the measured content region and repeated navigation. A low text ratio does not establish that main is missing. Adjust existing boundaries or content only where the saved page supports it.'
OLD_FIX = "Trim repeated navigation and footer text, or mark up the main content."


# -- (b) the batch's brand -------------------------------------------------------------------------------------------------
def other_name_site(pages=4):
    """`pages` pages, each saying og:site_name "Başka Ad": a name that is not the one in the CSV."""
    head = '<meta property="og:site_name" content="Başka Ad">'
    links = "".join(f'<a href="/sayfa-{n}">Sayfa {n}</a>' for n in range(1, pages))

    def html(title, body=""):
        return Response(body=f'<!doctype html><html lang="tr"><head><title>{title}</title>{head}</head><body><main><h1>{title}</h1>'
                             f"<p>{TR}</p>{body}</main></body></html>")
    return Site({"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
                 "/sitemap.xml": Response(404, "", content_type="text/plain"),
                 "/": html("Ana Sayfa", links), **{f"/sayfa-{n}": html(f"Sayfa {n}") for n in range(1, pages)}})


def test_a_batch_uses_the_csv_name_as_the_brand_and_crawl_without_one_takes_the_sites_name(monkeypatch, tmp_path, capsys):
    sites = Sites(monkeypatch)
    try:
        rows = [("Demo Kafe", sites.add("https://demo-kafe.test/", other_name_site()))]
        out = tmp_path / "batch"
        assert cli.main(["batch", brands_file(tmp_path, rows), "--out", str(out), "--max-pages", "5", "--delay", "0", "--no-firecrawl"]) == 0
    finally:
        sites.close()
    report = json.loads((out / "demo-kafe.json").read_text(encoding="utf-8"))
    assert report["brand"] == {"name": "Demo Kafe", "source": "typed", "confirmed": True, "found_in": None, "pages": None}

    # Healthy: `crawl` with no --dfs-brand still reads the brand from the site itself.
    monkeypatch.setattr(cli, "run_audit", lambda *args, **kwargs: _audit_site(other_name_site(), max_pages=5))
    path = tmp_path / "crawl.json"
    assert cli.main(["crawl", "https://demo-kafe.test/", "--json", str(path), "--no-firecrawl"]) == 0
    capsys.readouterr()
    found = json.loads(path.read_text(encoding="utf-8"))["brand"]
    assert found["name"] == "Başka Ad" and found["source"] == "site" and found["confirmed"] is False


# -- (c) the label on the printed lists ------------------------------------------------------------------------------------
def bare(title):
    """A page with no <main> or <article>: RND-7's note, which carries LG-22."""
    return httpx.Response(200, headers=HTML_TYPE, text=f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body>'
                                                       f'<div><h1>{title}</h1><p>{TR}</p><a href="/">Ana</a></div></body></html>')


FOOTER = "<footer>" + "<p>Adres, telefon, e-posta bilgileri ve çalışma saatleri burada yazılıdır. </p>" * 30 + "</footer>"


def crowded(title):
    """A page whose <main> holds a line and whose footer holds the rest: RND-7's Low finding."""
    return httpx.Response(200, headers=HTML_TYPE, text=f'<!doctype html><html lang="tr"><head><title>{title}</title></head><body>'
                                                       f'<header><nav><a href="/">Ana Sayfa</a></nav></header><main><h1>{title}</h1>'
                                                       f"<p>Kısa metin.</p></main>{FOOTER}</body></html>")


def kafe_site():
    return {"/": page("Ana Sayfa | Demo Kafe", '<a href="/menu">Menü</a><a href="/iletisim">İletişim</a>'),
            "/menu": bare("Menü | Demo Kafe"), "/iletisim": crowded("İletişim | Demo Kafe")}


def kafe():
    return audited(kafe_site(), sitemap=("/", "/menu", "/iletisim"))


def test_a_note_and_a_top_problem_carry_the_unverified_label_in_print_in_both_languages(no_lookups):  # noqa: F811
    outcome = kafe()
    findings = {f.title: f for f in outcome.by_id["RND-7"].findings}
    note = findings["1 page(s) have no <main> or <article> element"]
    low = findings["1 page(s) have less than 30% of their text in the main content"]
    assert note.severity.value == "Info" and note.launch_gated == ["LG-22"] and low.launch_gated == ["LG-22"]
    _report, _view, rows, printed = shown(outcome)
    notes = printed.split("<h3>Notes (nothing to fix)</h3>")[1].split("</ul>")[0]
    assert '1 page has no &lt;main&gt; or &lt;article&gt; element <span class="unverified small"><b>Unverified check</b> (LG-22)</span>' in notes
    problems = printed.split("problems</h3>", 1)[1].split("</ol>")[0]
    assert ('1 page has less than 30% of its text in the main content <span class="unverified small"><b>Unverified check</b> (LG-22)</span>'
            in notes)
    assert 'less than 30%' not in problems  # An editorial diagnostic, not a technical failure.
    _, _, _, turkish = shown(outcome, "tr")
    assert '<span class="unverified small"><b>Doğrulanmamış kontrol</b> (LG-22)</span>' in turkish and "Unverified check" not in turkish

    # Healthy: a note of a validated rule (no og:title, STR-10) and a problem of one (STR-3) have no label.
    [og_title] = [line for line in notes.split("<li") if "og:title" in line]
    assert "unverified" not in og_title
    [organization] = [line for line in problems.split("<li") if "Organization" in line]
    assert "unverified" not in organization
    assert next(r for r in rows if "og:title" in r["title"])["unverified"] is None
    # A finding whose items are only the bot registry's reasons (English sentences) shows the label alone.
    registry = {"label": "Unverified check", "items": ["Amazonbot: role not verified against vendor docs (provisional)"], "note": "…"}
    assert pdf._chip(registry) == '<span class="unverified small"><b>Unverified check</b></span> ' and pdf._chip(None) == ""


# -- (d) the browser step and the Playwright cap ---------------------------------------------------------------------------
def test_the_team_guide_says_the_browser_step_cannot_be_skipped_and_playwright_is_capped():
    guide = (ROOT / "TEAM-SETUP.md").read_text(encoding="utf-8")
    step = guide.split("## 5. Install the browser component")[1].split("## 6.")[0]
    message = strings.STRINGS["en"]["result.pdf_unavailable"].split(". ")[0] + "."
    bold = re.sub(r"\s+", " ", step.split("**")[1])
    assert bold == f"Do not skip this step. Without it the PDF button says “{message}” and pages are not rendered with JavaScript."
    assert "```sh\n.venv/bin/python -m playwright install chromium\n```" in step
    assert step.index("**Do not skip") < step.index("```sh")
    assert "Run it again after every reinstall or update (step 4)." in step
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for name in ("dev", "render", "team"):
        assert "playwright>=1.45,<1.64" in extras[name], name
    assert not any("playwright" in requirement for requirement in extras["web"])


# -- Item 4: RND-7 is page structure (FA-024) ------------------------------------------------------------------------------
def test_the_main_content_share_is_filed_under_page_structure_not_javascript(no_lookups):  # noqa: F811
    outcome = kafe()
    low = next(f for f in outcome.by_id["RND-7"].findings if 'less than' in f.title)
    assert low.severity.value == 'Info'
    assert low.how_to_fix == NEW_FIX
    assert wording.fix(NEW_FIX, "tr") == ('Ölçülen içerik bölgesini ve tekrarlanan gezinmeyi inceleyin. Düşük metin oranı main öğesinin eksik olduğunu kanıtlamaz. Mevcut sınırları veya içeriği yalnızca kayıtlı sayfa destekliyorsa düzenleyin.', True)
    assert "Low content ratio does not mean main is absent" in practical.example_for(low.title)

    # A report saved at 1.14, before this change: its RND-7 is shown under page structure, and its old fix still reads.
    report = json.loads(json.dumps(build_report(outcome.result, outcome.gates, outcome.checks), default=str))
    assert report["schema_version"] == "1.24"
    report['schema_version']='1.14'  # Explicit legacy fixture; historical severities must not be silently rewritten.
    report.pop('generation')
    for check in report["checks"]:
        for finding in check["findings"]:
            # A real 1.14 artifact predates derived judgment metadata.
            finding['evidence'].pop('judgment', None)
            if finding["check_id"] == "RND-7" and 'less than' in finding['title']:
                finding['severity']='S4'
                finding["how_to_fix"] = OLD_FIX
    view = summary.build(report, outcome="COMPLETED", reason="as saved")
    rows = summary.search(report, limit=100)["items"]
    areas = {area["area"]: area for area in view["areas"]}
    assert "RND-7" in [c["check_id"] for c in areas["STR"]["checks"]] and areas["STR"]["label"] == "Page structure and markup"
    assert "RND-7" not in [c["check_id"] for c in areas["RND"]["checks"]]
    mine = [row for row in rows if row["check_id"] == "RND-7"]
    assert len(mine) == 2 and all(row["area"] == "STR" and row["area_label"] == "Page structure and markup" for row in mine)
    assert summary.search(report, area="STR", limit=100)["total"] >= 2 and not summary.search(report, area="RND", limit=100)["items"]
    scorecard = {row["area"]: row for row in practical.scorecard(view["areas"], rows)}
    structure = [row for row in rows if row["area"] == "STR"]
    assert scorecard["STR"]["by_severity"]["S4"] == sum(row["severity"] == "S4" for row in structure)
    assert any(row['severity']=='S4' for row in mine)
    assert scorecard["STR"]["notes"] == sum(row["severity"] == "Info" for row in structure)
    assert scorecard["RND"]["by_severity"]["S4"] == 0 and scorecard["RND"]["notes"] == 0
    assert scorecard["RND"]["checks"] == len(areas["RND"]["checks"]) and "RND-7" not in [c["check_id"] for c in areas["RND"]["checks"]]
    saved = next(row for row in mine if row["severity"] == "S4")
    assert saved["judgment"]["source"]["how_to_fix"] == OLD_FIX and wording.fix(OLD_FIX, "tr")[1]
    assert "ARIA" in saved["fix"] and "only if" in saved["fix"]
    strings.set_language("tr")
    try:
        printed = pdf.render_html(summary.build(report, outcome="COMPLETED", reason="as saved"), rows=summary.search(report, limit=100)["items"],
                                  plan=summary.action_plan(report), generated_at="2026-10-14T00:00:00+00:00")
    finally:
        strings.set_language("en")
    section = printed.split("<h3>Sayfa yapısı ve işaretleme</h3>")[1].split("<h3>")[0]
    assert "RND-7" in section

    # Healthy: RND-1 and the other RND checks stay under JavaScript rendering.
    assert "RND-1" in [c["check_id"] for c in areas["RND"]["checks"]]
    assert summary._family("RND-1") == "RND" and summary._family("RND-6") == "RND" and summary._family("STR-1") == "STR"
