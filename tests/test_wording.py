"""The engine's sentences as the reader is shown them: every finding title, fix and expected result has an English
display form and a Turkish translation; numbers and quoted values stay as they are; a sentence with no translation is
shown whole, in English, with a mark. The saved report is never changed.

Every site, finding and run here is made up. Nothing is requested.
"""
import ast
import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from maya_audit.report import audit_status, run_outcome  # noqa: E402
from maya_audit_web import practical, strings, summary, wording  # noqa: E402
from test_web_app import API, BUILT_TITLES, Site, audit_of, engine_title_samples, get, plan, start, web  # noqa: E402,F401

MARK = " (İngilizce)"
TR = wording.TABLES["tr"]
# Words that only an English sentence holds. Names, codes, header names and addresses hold none of them.
ENGLISH_WORDS = re.compile(r"\b(the|was|were|is|are|of|and|not|reached|page|pages|read|could|every|only|through)\b", re.IGNORECASE)


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    strings.set_language("en")


def frames_of(rows):
    return {frame.key: frame for frame in rows}


# -- finding titles --------------------------------------------------------------------------------------------------

def test_every_title_the_engine_writes_has_one_pattern_an_english_form_and_a_turkish_one_with_the_same_holes():
    samples = engine_title_samples()
    assert len(samples) > 170 and {check for check, _ in samples} >= {"ACC-1", "ACC-9", "IDX-3", "RND-5", "STR-13", "STR-23", "PRF-3", "TSEO-1"}
    used, shown_in_turkish = set(), set()
    for check_id, title in samples:
        keys = wording.title_key(check_id, title)
        assert len(keys) == 1, f"{check_id}: {len(keys)} title patterns match {title!r}: {keys}"
        used.update(keys)
        english, _ = wording.title(check_id, title, "en")
        assert "(s)" not in english.replace('(href="#")', ""), f"{check_id}: the English form still says (s): {english!r}"
        turkish, translated = wording.title(check_id, title, "tr")
        if translated:
            shown_in_turkish.update(keys)
            assert MARK not in turkish and "(s)" not in turkish and turkish != title, (check_id, turkish)
    every = {key for rows in wording.TITLES.values() for key, _ in rows}
    assert every == set(wording.ENGLISH) == set(TR["titles"]), every ^ set(TR["titles"])
    # A pattern nothing in today's source writes is there for reports saved by an earlier engine, and says so (`SAVED_ONLY`).
    assert every - used == wording.SAVED_ONLY, f"title patterns that match no title the engine writes: {sorted(every - used - wording.SAVED_ONLY)}"
    old = '30 link(s) on 12 page(s) lead nowhere (href="#" or a javascript: address)'  # STR-19 before team-preview-8
    assert wording.title_key("STR-19", old) == ["str19.lead_nowhere"] and wording.title("STR-19", old, "en")[0] == '30 links on 12 pages lead nowhere (href="#" or a javascript: address)'
    assert wording.title("STR-19", old, "tr") == ('12 sayfadaki 30 bağlantı hiçbir yere götürmüyor (href="#" veya javascript: adresi)', True)
    assert wording.expected("every link has an address a visitor and a crawler can follow", "tr")[1] and wording.label("Links that lead nowhere", "tr")[1]
    assert wording.line("1 finding(s): 30 link(s) without a usable address.", "tr") == ("1 bulgu: 30 bağlantının kullanılabilir adresi yok.", True)
    # A sample read from the source holds a 3 where a label goes; a title as the engine writes it (BUILT_TITLES) does not.
    assert every - shown_in_turkish == wording.SAVED_ONLY, f"titles never shown in Turkish: {sorted(every - shown_in_turkish - wording.SAVED_ONLY)}"
    for check_id, rows in BUILT_TITLES.items():
        for _, title in rows:
            turkish, translated = wording.title(check_id, title, "tr")
            assert translated and MARK not in turkish, f"{check_id}: no Turkish for {title!r}"
    for check_id, rows in wording._TITLES.items():
        for key, frame, english in rows:
            holes = set(wording.Frame(key, frame).kinds)
            assert wording.names(english) == holes, f"{key}: English form uses {wording.names(english)}, the pattern has {holes}"
            assert wording.names(TR["titles"][key]) == holes, f"{key}: Turkish uses {wording.names(TR['titles'][key])}, the pattern has {holes}"
            assert TR["titles"][key].strip() and TR["titles"][key] != english, key
    assert all(isinstance(pattern, str) and re.compile(pattern) for rows in wording.TITLES.values() for _, pattern in rows)


def test_numbers_and_quoted_values_are_kept_and_one_is_said_as_one_in_both_languages():
    title = "16 internal link(s) on 4 page(s) carry tracking parameters (utm_source=gemini)"
    assert wording.title("IDX-6", title, "en") == ("16 internal links on 4 pages carry tracking parameters (utm_source=gemini)", True)
    turkish, translated = wording.title("IDX-6", title, "tr")
    assert translated and "(s)" not in turkish and MARK not in turkish
    assert re.findall(r"\d+", turkish) == ["4", "16"] and "utm_source=gemini" in turkish and "sayfadaki" in turkish
    assert wording.title("IDX-6", "1 internal link(s) on 1 page(s) carry tracking parameters (utm_term)", "en")[0] == \
        "1 internal link on 1 page carries tracking parameters (utm_term)"
    assert wording.title("IDX-4", "1 page(s) are canonicalized to a URL with different content", "en")[0] == "1 page is canonicalized to a URL with different content"
    assert wording.title("IDX-4", "3 page(s) are canonicalized to a URL with different content", "en")[0] == "3 pages are canonicalized to a URL with different content"
    # Turkish: the bare number, the noun once with its ending, no plural after a number.
    assert wording.title("IDX-4", "1 page(s) are canonicalized to a URL with different content", "tr")[0].startswith("1 sayfanın canonical")
    assert wording.title("IDX-4", "3 page(s) are canonicalized to a URL with different content", "tr")[0].startswith("3 sayfanın canonical")
    # Bot names, header names, addresses and quoted site text come back untouched.
    for check_id, title, kept in (
            ("ACC-4", "Requests with search bot user agents were blocked on 3 URL(s): GPTBot, ClaudeBot (seen once, not retried)", ["GPTBot, ClaudeBot", "3 URL"]),
            ("IDX-6", "Link target returns 404, linked from 2 page(s): https://made-up.example/old?a=1", ["404", "https://made-up.example/old?a=1"]),
            ("IDX-8", "33 indexable pages share the title 'Winter Sale (page 2)'", ["33", "'Winter Sale (page 2)'"]),
            ("STR-18", "The homepage title does not name the brand ('Welcome | Home')", ["'Welcome | Home'"]),
            ("STR-13", "3 page(s) have unfilled template markers in the title: {{page_title}}, [[brand]]", ["{{page_title}}, [[brand]]"]),
            ("ACC-3", "noindex via X-Robots-Tag (googlebot) on 5 page(s)", ["X-Robots-Tag (googlebot)", "noindex"]),
            ("STR-7", "27% of 515 content image(s) are offered in WebP or AVIF", ["%27", "515", "WebP", "AVIF"]),
            ("ACC-9", "The site blocks or challenges automated visitors: Cloudflare (bot challenge) answered 5 of 6 page request(s). AI crawlers may be affected too",
             ["Cloudflare (bot doğrulaması)", "6 sayfa isteğinden 5"])):
        turkish, translated = wording.title(check_id, title, "tr")
        assert translated and all(piece in turkish for piece in kept), (turkish, kept)
        assert turkish[0] == turkish[0].upper()
    assert wording.title("ACC-4", "Requests with search bot user agents were blocked on 1 URL(s): GPTBot", "tr")[0].startswith("Arama botlarının")
    assert wording.title("ACC-8", "llms.txt is present", "tr") == ("llms.txt dosyası mevcut", True)  # a file name is not capitalised


def test_a_sentence_with_no_translation_is_shown_whole_in_english_with_a_mark_never_dropped_or_half_translated():
    unknown = "A made-up thing the engine will only say next year, on 3 page(s)"
    plain = "A made-up thing the engine will only say next year, on 3 pages"  # English: the engine's words, with "(s)" resolved
    assert wording.title("STR-1", unknown, "en") == (plain, True)
    assert wording.title("STR-1", unknown, "tr") == (unknown + MARK, False)
    assert wording.title("XYZ-9", unknown, "tr") == (unknown + MARK, False)  # a check this layer has never heard of
    assert wording.fix("Do a made-up thing.", "tr") == ("Do a made-up thing." + MARK, False) and wording.fix("Do a made-up thing.", "en") == ("Do a made-up thing.", True)
    assert wording.expected("a made-up state", "tr")[0].endswith(MARK) and wording.note("A made-up note.", "tr")[0].endswith(MARK)
    assert wording.fix("", "tr") == ("", True) and wording.outcome(None, "tr") == (None, True)
    # A label inside a known frame that has no translation: the whole sentence falls back, nothing is half-translated.
    half = "Requests with search bot user agents were teleported on 3 URL(s): GPTBot"
    assert wording.title("ACC-4", half, "tr") == (half + MARK, False) and wording.title("ACC-4", half, "en")[1]
    finding = {"id": "STR-1-made-up", "check_id": "STR-1", "title": unknown, "severity": "S3", "confidence": "verified", "how_to_fix": "Do a made-up thing.",
               "expected": "every indexable page has a title", "notes": ["A made-up note.", "Capped at S4: Hypothesis."], "scope": {"kind": "page", "count": 1, "urls": []}}
    strings.set_language("tr")
    finding.setdefault("evidence", {"pages": [{"url": "https://translation.example/page", "source": "synthetic", "requested_at": "2026-10-19T10:00:00Z", "field": "title", "value": finding["title"]}]})
    row = summary.item(finding)
    assert row["title"] == unknown and row["title_shown"] == unknown + MARK and row["what"] == unknown + MARK and row["untranslated"] is True
    assert row["fix"] == "Do a made-up thing." and row["fix_shown"] == "Do a made-up thing." + MARK
    assert row["expected_shown"] == "dizine eklenebilir her sayfanın bir başlığı var"
    assert row["notes"] == finding["notes"] and row["notes_shown"] == ["A made-up note." + MARK, "S4 ile sınırlandı: Hipotez."] and row["notes_untranslated"] == 1
    strings.set_language("en")
    finding.setdefault("evidence", {"pages": [{"url": "https://translation.example/page", "source": "synthetic", "requested_at": "2026-10-19T10:00:00Z", "field": "title", "value": finding["title"]}]})
    row = summary.item(finding)
    assert row["title"] == unknown and row["title_shown"] == plain and row["fix_shown"] == "Do a made-up thing." and row["untranslated"] is False and row["notes_shown"] == finding["notes"]


def test_the_row_keeps_the_reports_own_title_and_fix_and_adds_what_is_shown():
    finding = {"id": "IDX-4-made-up", "check_id": "IDX-4", "title": "1 page(s) are canonicalized to a URL with different content", "severity": "S2",
               "confidence": "estimated", "expected": "a page whose own content should be cited is self-canonical",
               "how_to_fix": "Engines that honor the canonical will index the target instead of this page's own content. Make the page self-canonical "
                             "if its content should be cited, or mark it as intended.",
               "notes": [], "scope": {"kind": "page", "count": 1, "urls": ["https://made-up.example/a"]}}
    finding["evidence"] = {"pages": [{"url": "https://made-up.example/a", "canonical": "https://made-up.example/b", "same_content": False, "source": "synthetic", "requested_at": "2026-10-19T10:00:00Z"}]}
    english = summary.item(finding)
    assert english["title"] == finding["title"] and english["fix"] == finding["how_to_fix"] and english["expected"] == finding["expected"]
    assert english["title_shown"] == "1 page is canonicalized to a URL with different content" and english["fix_shown"] == finding["how_to_fix"]
    assert english["untranslated"] is False
    strings.set_language("tr")
    turkish = summary.item(finding)
    assert turkish["title"] == finding["title"] and turkish["fix"] == finding["how_to_fix"]  # the catalog, the example and the comparison key on these
    assert turkish["title_shown"] == "1 sayfanın canonical etiketi farklı içerikli bir URL'yi gösteriyor" and turkish["untranslated"] is False
    assert turkish["fix_shown"].startswith("Canonical'a uyan motorlar") and turkish["expected_shown"].endswith("kendisini gösterir")
    assert practical.example_for(turkish["title"]) and practical.issue(turkish)["what"] == turkish["title_shown"]
    actions = practical.first_actions([turkish])
    # An action says what to do, and for this finding on one page it names the page (team-preview-12).
    assert actions[0]["text"] == "/a sayfasının canonical etiketini /a adresinin kendisine yöneltin." and actions[0]["titles"] == [turkish["title_shown"]]


# -- fixes and expected results: every sentence in the engine's source ---------------------------------------------------

POSITIONS = {"Finding": (8, 9, None), "_finding": (8, 9, 11), "_note": (6, 7, 9), "ReviewItem": (2, 7, None)}
KEYWORDS = {"expected": ("expected", "why_review"), "fix": ("how_to_fix", "fix", "suggested_action"), "notes": ("notes",)}
SITE_CHECKS = ("ACC", "IDX", "RND", "STR", "PRF", "TSEO")


def engine_sentences():
    """What the engine's findings and review items say besides their title, read from its source: the fixed sentences
    by kind ("expected" also holds a review item's reason, "fix" its suggested action), and the places where a sentence
    is put together at run time, as (check id, kind, the source expression)."""
    import maya_audit
    root = Path(maya_audit.__file__).parent
    fixed, built = {"expected": [], "fix": [], "notes": []}, []
    for path in [*sorted((root / "checks").glob("*.py")), root / "technical_seo.py"]:
        module = importlib.import_module("maya_audit." + ("checks." if path.parent.name == "checks" else "") + path.stem)

        def collect(node, kind, check_id):
            if node is None:
                return
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str) and node.value.strip():
                    fixed[kind].append(node.value)
            elif isinstance(node, ast.IfExp):
                collect(node.body, kind, check_id), collect(node.orelse, kind, check_id)
            elif isinstance(node, (ast.List, ast.Tuple)):
                for element in node.elts:
                    collect(element, kind, check_id)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                collect(node.left, kind, check_id), collect(node.right, kind, check_id)
            elif isinstance(node, ast.Starred):
                collect(node.value, kind, check_id)
            elif isinstance(node, ast.Name) and isinstance(getattr(module, node.id, None), str):
                fixed[kind].append(getattr(module, node.id))
            else:
                built.append((check_id, kind, ast.unparse(node)))

        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in POSITIONS):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            first = node.args[0] if node.args else keywords.get("check_id")
            if not (isinstance(first, ast.Constant) and str(first.value).startswith(SITE_CHECKS)):
                continue  # the answer-engine panel (ANS), and the helpers that pass a finding's fields on
            for kind, position in zip(("expected", "fix", "notes"), POSITIONS[node.func.id]):
                value = next((keywords[name] for name in KEYWORDS[kind] if name in keywords), None)
                if value is None and position is not None and position < len(node.args):
                    value = node.args[position]
                collect(value, kind, first.value)
    return {kind: list(dict.fromkeys(rows)) for kind, rows in fixed.items()}, built


# A fix or an expected result the engine puts together at run time: (check id, kind, the source expression) -> the
# sentences it can produce, as the engine writes them. A new place fails the test until it is listed here.
BUILT = {
    ("STR-7", "fix", "FORMAT_ACTION"): [__import__("maya_audit.evidence_accuracy", fromlist=["FORMAT_ACTION"]).FORMAT_ACTION],
    ("STR-7", "expected", "FORMAT_EXPECTED"): [__import__("maya_audit.evidence_accuracy", fromlist=["FORMAT_EXPECTED"]).FORMAT_EXPECTED],
    ("ACC-9", "fix", None): ['If you own this site: allow the user agent "Maya-Audit" in the firewall or bot-protection rules and run the audit again; verify ownership '
                             "so ACC-4 can test what AI crawlers receive; or try again later if this was a rate limit. Then check the same rules for the AI crawlers "
                             "you want to reach you (OAI-SearchBot, ClaudeBot, PerplexityBot and others).",
                             # DECISIONS 288: 429 on pages while the site's files are served (FIX_429), named and unnamed blocker
                             'Check the bot and rate-limit rules in Cloudflare that answer page requests with 429 while robots.txt and the sitemap '
                             'are served: allow the user agent "Maya-Audit" and run the audit again. AI crawlers may get the same treatment: check '
                             "the same rules for OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you.",
                             "Check the bot and rate-limit rules in the site's firewall that answer page requests with 429 while robots.txt and the "
                             'sitemap are served: allow the user agent "Maya-Audit" and run the audit again. AI crawlers may get the same treatment: '
                             "check the same rules for OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you."],
    ("ACC-2", "fix", "_role_how_to_fix(role, engines, line)"): [
        "If ChatGPT search, Perplexity should be able to find and cite these pages, remove or narrow the rule on line 4 for these user agents. If blocking them is deliberate, mark it as intended.",
        "Live fetchers may not follow robots.txt at all (see ACC-4 for what they actually receive). If you want users' AI assistants to read these pages, remove the rule on line 7.",
        "These user agents serve: OpenAI model training; Common Crawl corpus (used in model training). If blocking them matches your policy, record it in the declared bot policy; otherwise change line 9."],
    ("ACC-2", "expected", None): ["robots.txt blocks training bots, as declared", "robots.txt blocks search bots, as declared"],
    ("ACC-2", "fix", None): ["Add Disallow rules for these user agents, or change the declared training-bot policy.",
                             "Under RFC 9309 a bot obeys only its most specific group. If line 12 should also apply to GPTBot, CCBot, repeat it inside their group."],
    ("ACC-7", "expected", None): ["Crawl-delay below 10s for bots you want refreshing your pages"],
    ("STR-13", "fix", "FIX[where]"): [
        "Fill the structured-data fields with real values, or remove the block. Engines read these fields as data.", "Fill the meta tag with its real value, or remove it.",
        "Replace the marker in the <title> with the real text.", "Replace the address with the real one. As it is, the link or image cannot load.",
        "Replace the marker with the real text, or remove the unfinished passage.",
        "Nothing to fix for readers. To give crawlers that do not run JavaScript the real text, send it in the page's HTML from the server."],
    ("IDX-2", "expected", None): ["more than 14 days of validity left"],
    ("IDX-3", "fix", "fix"): ["Redirect to the https:// address. If the http:// address then redirects back to https://, remove the detour.",
                              "Nothing to fix if the move is intended. To have the destination checked, audit that host as well."],
    ("PRF-1", "expected", None): ["HTML returned in under 1.5 s"],
    ("PRF-2", "expected", None): ["under 5% of fetches fail"],
    ("RND-5", "fix", "fix"): ["Serve the content to cookie-less visitors and overlay the wall instead of redirecting, or mark it intended.",
                              "Put the content in the HTML and show the wall as an overlay, or mark it intended.",
                              "Add paywalled-content structured data (isAccessibleForFree: false with hasPart) so engines can tell a paywall from cloaking."],
    ("RND-4", "fix", "fix"): ["Review the embedded content and its text alternative; add equivalent page text only if essential information is otherwise unavailable.",
                              "Add a text equivalent (a table, aria-label, or fallback content) for what the canvas shows.",
                              "If these images contain text, put that text in the HTML or in descriptive alt text."],
    ("STR-18", "fix", None): ["Put the brand name in the homepage <title>, for example “Made-Up Kettles | what you do”."],
    ("STR-19", "expected", "expected"): ["every link to content has an address a crawler can follow", "an entry listed among the footer's links leads to its page"],
    ("STR-19", "fix", "fix"): ["Give each link the address of the page it should open. If it only triggers a script, make it a <button>.",
                               "Link each footer entry to its page, or remove the entries whose pages do not exist yet."],
    ("STR-4", "expected", None): [f"the structured-data {field} matches what the page shows" for field in ("price", "currency", "availability", "rating", "date", "product name", "author")],
    ("STR-11", "expected", None): ["every description of one entity gives the same dateModified", "every description of one entity gives the same price"],
    ("STR-6", "fix", None): ["Set Last-Modified header from the content's real last edit.", "Set sitemap <lastmod> from the content's real last edit.",
                             "Set schema dateModified from the content's real last edit."],
    ("STR-10", "expected", None): ["meta description present", "og:image present", "og:title present", "og:title has a value"],
    ("STR-10", "fix", None): ["Add meta description.", "Add og:image.", "Add og:description.", "Give og:title a value."],
    ("STR-9", "fix", "fix"): ["Add lang to the <html> element.", "Use a BCP 47 code such as en or tr-TR.", "Use a language code with an optional ISO 3166-1 region (en-GB, not en-UK), or x-default.",
                              "Use fully-qualified URLs; Google's docs require the scheme and host."],
    ("TSEO-1", "expected", "expected"): ["A page-specific title around 10–60 characters, where that fits the page.", "A concise, page-specific title around 10–60 characters, where that fits.",
                                         "A useful page summary around 70–160 characters, where practical.", "A concise page summary around 70–160 characters, where practical.",
                                         "Headings progress through levels without skipping an intermediate level."],
    ("TSEO-1", "fix", "fix"): ["Expand the title with the page topic so readers can distinguish it in search results and shared links.",
                               "Move the page topic toward the start and remove words that do not help identify this page.",
                               "Add a specific summary of the page and the useful next step it offers.", "Keep the central page summary and remove repeated or secondary detail.",
                               "Use the next heading level in sequence (for example, follow an H2 with an H3 before an H4)."],
}
# Notes are translated where the sentence is fixed. A note the engine puts together at run time is listed here when it
# has no pattern yet: it is shown in English with the mark (the rule above), and this list says so out loud.
NOTES_WITHOUT_A_PATTERN: set = set()
# Two places take their notes from elsewhere in the engine; each note they can hold is one of the engine's own lines.
NOTES_FROM_ELSEWHERE = {
    ('STR-7', "assessment['limits']"): ["Markup references are not served formats. Responses describe only their recorded client/time; unobserved negotiation and alternative resources remain unassessed. Resource and occurrence counts differ."],
    ("ACC-4", "sorted(notes)"): [  # what one probe saw (maya_audit.probes)
        "the bot response lacks the X-Powered-By header the browser response had: it was likely answered at the edge, before the application ran",
        "transport failure for the bot user agent (ReadTimeout) while the browser request succeeded"],
    ("IDX-7", "int2.evidence.get('caveats', [])"): [  # the caveats of the integrity gate INT-2
        "3 URL(s) were skipped because robots.txt disallows them for Maya's user agent; links on those pages were not followed, so pages linked only from them may look orphaned.",
        "Link discovery used rendering: 14 link(s) on 2 page(s) exist only after JavaScript runs and were followed. Only the homepage and key pages were rendered for links, so pages "
        "linked only from the rendered view of other pages may be missing from this crawl.",
        "sitemap discovery stopped after 4 document(s) with 9 still queued: it had used its share of the crawl's time limit. Sitemap-based coverage is partial."],
}


def test_every_fix_and_expected_sentence_in_the_engines_source_has_a_turkish_entry():
    fixed, built = engine_sentences()
    assert len(fixed["fix"]) > 100 and len(fixed["expected"]) > 100 and len(fixed["notes"]) > 70
    for kind, translate in (("fix", wording.fix), ("expected", wording.expected)):
        missing = [text for text in fixed[kind] if not translate(text, "tr")[1]]
        assert missing == [], f"{kind} sentences with no Turkish: {missing}"
        for text in fixed[kind]:
            turkish, _ = translate(text, "tr")
            assert MARK not in turkish and turkish != text and translate(text, "en") == (wording.english(text), True) and "(s)" not in translate(text, "en")[0]
    # Every place a fix or an expected result is put together at run time is known, and each sentence it makes is translated.
    places = {(check_id, kind) for check_id, kind, _ in built if kind != "notes"}
    assert places == {(check_id, kind) for check_id, kind, _ in BUILT}, places ^ {(check_id, kind) for check_id, kind, _ in BUILT}
    # Every string the engine's check modules hold (a sentence written over two lines is one string).
    constants = {node.value for path in [*(Path(__file__).parent.parent / "maya_audit" / "checks").glob("*.py"), Path(__file__).parent.parent / "maya_audit" / "technical_seo.py", Path(__file__).parent.parent / "maya_audit" / "evidence_accuracy.py"]
                 for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for (check_id, kind, _), sentences in BUILT.items():
        for text in sentences:
            turkish, translated = (wording.fix if kind == "fix" else wording.expected)(text, "tr")
            assert translated and MARK not in turkish, f"{check_id} {kind}: no Turkish for {text!r}"
            if text in TR["fixes"] or text in TR["expected"]:  # a fixed sentence chosen from a table: still in the engine's source
                assert text in constants, f"{check_id}: the engine's source no longer holds {text!r}"
    # Notes: every fixed note is translated; the notes put together at run time are either patterned or listed.
    assert [text for text in fixed["notes"] if not wording.note(text, "tr")[1] and text.strip() != "Each page's content_delta quotes that text."] == []
    loose = {(check_id, source) for check_id, kind, source in built if kind == "notes"}
    patterned = {("ACC-2", "notes"), ("ACC-4", "unconfirmed_note"), ("ACC-6", "notes"), ("IDX-9", "notes"), ("PRF-1", "common_notes"),
                 ("STR-4", "INFERRED_BASIS[field]"), ("STR-4", "ESTIMATED_BASIS[field]"), ("ACC-5", "window {logs"), ("ACC-7", "Estimated effect"), ("IDX-1", "Inferred: assumes answer engines"), ("IDX-1", "final_url_note"),
                 ("IDX-3", "The redirect and its target are Verified"), ("IDX-3", "further request(s) made after it"), ("IDX-6", "requested once and returned"), ("IDX-5", "listed URL(s) were not fetched"), ("IDX-5", "notes"), ("ACC-8", "First line"), ("IDX-7", "incomplete_note"),
                 ("PRF-1", "generalizes from"), ("PRF-1", "threshold is policy"), ("PRF-1", "A URL that times out on every attempt"), ("STR-1", "note"),
                 ("STR-1", "The titles are different in full"), ("STR-6", "Thresholds ("), ("STR-12", "each passage of main content"),
                 ("STR-12", "a heading is assigned a language"), ("STR-13", "notes"), ("TSEO-1", "note")}
    unknown = {(check_id, source) for check_id, source in loose - NOTES_WITHOUT_A_PATTERN - set(NOTES_FROM_ELSEWHERE)
               if not any(check_id == check and piece in source for check, piece in patterned)}
    assert set(NOTES_FROM_ELSEWHERE) <= loose
    for place, notes in NOTES_FROM_ELSEWHERE.items():
        for text in notes:
            turkish, translated = wording.note(text, "tr")
            assert translated and MARK not in turkish and "(s)" not in turkish, f"{place}: no Turkish for the note {text!r}"
    assert unknown == set(), f"notes put together at run time that are neither patterned nor listed as untranslated: {unknown}"
    for text in ("Only IP-verified requests count; window 2026-09-01 to 2026-09-30.", "Thresholds (5 pages, 90%) are uncalibrated guesses.",
                 "Estimated effect: at most about 8640 fetches per day per bot, assuming the bot honors Crawl-delay (it is non-standard; not all do).",
                 "One request was made, to a random address generated for this audit. the redirect was recorded, not followed (one request only)",
                 "The redirect and its target are Verified. The target was not fetched: the audit stays on https://made-up.example, so nothing is known about the page a visitor ends on.",
                 "The 1.5 s threshold is policy (spec default: 1.5 s).", "Source: Firecrawl.", "A URL that times out on every attempt is an IDX-1 finding, not this one.",
                 "Heuristic only: these character bands are editorial guidance, not Google limits or a ranking guarantee.",
                 "The marker is Verified as present in the page source at the place shown.",
                 "Reported as Info: the blocked path is a private or technical one (cart, checkout), which sites normally keep bots out of, and none of the blocked URLs is "
                 "the homepage, a key page or listed in the sitemap.", "GPTBot is also blocked. That is reported once, as an ACC-2 finding, not repeated here.",
                 "Not confirmed: the probe cap was reached before this difference could be retried (2 retries configured). The response itself is Verified; that it is a "
                 "lasting block rather than a transient one is Estimated. Re-run with a larger probe cap (CrawlConfig.max_probe_requests) to confirm.",
                 "Blocking GPTBot does not block OAI-SearchBot (ChatGPT search) or ChatGPT-User.", "robots.txt may not apply to live fetchers; ACC-4 checks what they actually receive.",
                 "Estimated: matched on English stock wording ('sold out', 'in stock', 'add to cart').",
                 "Capped at S4: Hypothesis. See spec §8 Q5 for the evidence that could re-evaluate this.",
                 "The crawl is incomplete, so these figures cover the fetched pages only: a page may have more links to it, and a shorter path to it, than is shown."):
        assert wording.note(text, "tr")[1], text


def test_the_turkish_file_is_marked_for_review_and_holds_no_entry_the_code_does_not_know():
    raw = json.loads((strings.LOCALES / "findings" / "tr.json").read_text(encoding="utf-8"))
    assert raw["_review"] == "machine-translated, needs native-speaker review"
    assert set(raw) - {"_review", "_about"} == set(wording.SECTIONS)
    for section, frames in (("fix_patterns", wording.FIX_PATTERNS), ("expected_patterns", wording.EXPECTED_PATTERNS), ("note_patterns", wording.NOTE_PATTERNS),
                            ("outcomes", wording.OUTCOMES), ("term_patterns", wording.TERM_PATTERNS)):
        assert set(raw[section]) == set(frames_of(frames)), (section, set(raw[section]) ^ set(frames_of(frames)))
        for key, frame in frames_of(frames).items():
            assert wording.names(raw[section][key]) <= set(frame.kinds), (key, wording.names(raw[section][key]), set(frame.kinds))
    assert all(value.strip() for rows in raw.values() if isinstance(rows, dict) for value in rows.values())
    assert "Bulgu başlıkları ve çözüm önerileri makine çevirisidir" in strings.LANGUAGE_NOTES["tr"] and "İngilizce yazılır" not in strings.LANGUAGE_NOTES["tr"]
    gate = (Path(__file__).parent.parent / "docs" / "LAUNCH-GATE.md").read_text(encoding="utf-8")
    assert "machine-translated" in gate and "native speaker" in gate


# -- the outcome sentence and "What this audit covers" -------------------------------------------------------------------

def page(url, kind="ok", status=200):
    return SimpleNamespace(url=url, status=status, fetch_class=SimpleNamespace(value=kind), readable_document=lambda: kind == "ok" and status == 200)


def run(pages, stop="exhausted", detail="every discovered URL was fetched or skipped", *, gates=(), unread=0, stopped=False, deadline=False, collectors=None):
    result = SimpleNamespace(pages=pages, stop_reason=SimpleNamespace(value=stop), stop_detail=detail, collector_errors=collectors or {}, stopped=stopped,
                             deadline_hit=deadline, not_fetched_urls=[f"https://made-up.example/later-{n}" for n in range(unread)],
                             discovered_urls=[p.url for p in pages], elapsed_s=12.5)
    return result, [SimpleNamespace(check_id=check_id, state=state) for check_id, state in gates]


def reader(read, *, cached=0, blocked=True, not_reached=False, **coverage):
    rows = [{"url": f"https://made-up.example/p{n}", "outcome": "read", "from_cache": n < cached, "observed_at": f"2026-10-0{n + 1}T08:15:00+00:00"} for n in range(read)]
    return {"used": True, "purpose": "main page reader", "pages_read": read, "pages": rows, "stopped_because": coverage.pop("stopped_because", None),
            "crawl_blocked": {"blocked": blocked, "direct_not_reached": not_reached}, "coverage": coverage}


SITE = "https://made-up.example"
OPEN = [page(f"{SITE}/{n}") for n in range(3)]
WALLED = [page(f"{SITE}/", "blocked", 403)]
NO_ANSWER = ("robots.txt was not checked: no answer reached this computer (E-123). Whether the site or the connection failed is not known; "
             "Maya's own crawler requested no page")
RUNS = {
    "open site": (run(OPEN), None, "COMPLETED"),
    "open site, some requests refused": (run(OPEN + [page(f"{SITE}/x", "blocked", 403)]), None, "COMPLETED"),
    "challenged and read through the reader": (run(WALLED, gates=[("INT-1", "degraded")]), reader(4, cached=2), "COMPLETED"),
    "the reader stopped": (run(WALLED, gates=[("INT-1", "degraded")]),
                           reader(4, stopped_because="the last 3 pages asked for came back unreadable, so no more were requested", known_urls_not_requested=7,
                                  not_requested_because="reader_kept_failing", requested_without_a_readable_document=3,
                                  causes={"empty_document": 2, "reader_challenged": 1}, key_pages_not_read=[f"{SITE}/pricing"]), "INCOMPLETE"),
    "the reader's page cap": (run(WALLED, gates=[("INT-1", "degraded")]), reader(50, known_urls_not_requested=694, cap_reached=True, page_cap=50), "INCOMPLETE"),
    # The request allowance used before the pages read reached the cap: one sentence, and no word about credit.
    "the reader used its request allowance": (run(WALLED, gates=[("INT-1", "degraded")]),
                                              reader(43, known_urls_not_requested=449, not_requested_because="request_allowance_used", page_requests=51,
                                                     requests_without_a_new_page=8, unread_left_out={"robots_disallowed": 9, "not_a_page": 3},
                                                     stopped_because="the Firecrawl request allowance of 50 for this audit is used. No request was sent."), "INCOMPLETE"),
    "the reader ran out of time": (run(WALLED, gates=[("INT-1", "degraded")], deadline=True), reader(5, known_urls_not_requested=2, not_requested_because="time_limit"), "INCOMPLETE"),
    "the reader was stopped on request": (run(WALLED, gates=[("INT-1", "degraded")], stopped=True), reader(5, known_urls_not_requested=2, not_requested_because="stopped_on_request"), "INCOMPLETE"),
    "nothing read": (run(WALLED, gates=[("INT-1", "degraded")]), None, "DEGRADED"),
    "rate limited": (run([page(f"{SITE}/", "rate_limited", 429), page(f"{SITE}/a", "rate_limited", 429), page(f"{SITE}/b", "blocked", 403)], "rate_limit",
                         "5 consecutive rate-limited responses", gates=[("INT-1", "degraded"), ("INT-2", "violation")], collectors={"links": "boom"}), None, "DEGRADED"),
    "network problem": (run([], "network_problem", NO_ANSWER), None, "DEGRADED"),
    "network problem, read through the reader": (run([], "network_problem", NO_ANSWER), reader(6, blocked=False, not_reached=True), "COMPLETED"),
    "network problem, reader cut short": (run([], "network_problem", NO_ANSWER), reader(6, blocked=False, not_reached=True, known_urls_not_requested=3,
                                                                                       not_requested_because="credit_or_request_limit"), "INCOMPLETE"),
    "robots.txt forbids": (run([], "robots_disallowed", "robots.txt disallows the start URL for this user agent; no pages could be fetched"), None, "DEGRADED"),
    "page cap": (run(OPEN, "page_cap", "page cap of 50 reached", unread=694), None, "INCOMPLETE"),
    "fetch budget": (run(OPEN, "page_cap", "fetch budget of 150 requests (pages plus redirects) reached", unread=9), None, "INCOMPLETE"),
    "time limit": (run(OPEN, "time_limit", "the crawl used its share (70%) of the 300s time limit; the rest is kept for the checks that run after it", unread=12, deadline=True),
                   None, "INCOMPLETE"),
    "whole time limit": (run(OPEN, "time_limit", "time limit of 300s reached", unread=2), None, "INCOMPLETE"),
    "checks out of time": (run(OPEN, deadline=True), None, "INCOMPLETE"),
    "stopped on request": (run(OPEN, "stopped", "stopped on request before every page was fetched", unread=5, stopped=True), None, "INCOMPLETE"),
}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_outcome_sentence_and_the_status_rows_are_turkish_for_every_kind_of_run(name):
    (result, gates), firecrawl, word = RUNS[name]
    code, label, sentence = run_outcome(result, gates, firecrawl)
    assert label == word, sentence
    status = audit_status(result, gates, [], firecrawl)
    report = {"audit_status": {**status, "timing": {"crawl_and_checks_s": 12.5, "all_phases_s": 20.0}}, "crawl": {"stop_reason": result.stop_reason.value},
              "firecrawl": firecrawl}
    english = summary.status_view(report)
    # English: the engine's own sentences, unchanged but for "1 page(s)" said as "1 page" (decision 166).
    plain = wording.english
    assert wording.outcome(sentence, "en") == (plain(sentence), True) and english["rows"][0]["note"] == plain(status["direct_access"]["note"])
    assert english["rows"][2]["note"] == plain(status["vendor_crawler_evidence"]["note"]) and english["rows"][1]["note"].startswith(plain(status["content_coverage"]["note"]))
    assert not any("(s)" in row["note"] for row in english["rows"]) and "(s)" not in wording.outcome(sentence, "en")[0]
    strings.set_language("tr")
    shown, translated = wording.outcome(sentence)
    assert translated and MARK not in shown, sentence
    view = summary.status_view(report)
    said = [shown, *(row["note"] for row in view["rows"]), *([view["cache_note"]] if view["cache_note"] else []), view["duration_line"]]
    assert view["untranslated"] == 0, [text for text in said if MARK in text]
    for text in said:
        assert MARK not in text and not text.isascii(), text
        assert not ENGLISH_WORDS.search(text), (ENGLISH_WORDS.search(text).group(0), text)
        assert not re.search(r"\b(page_cap|time_limit|rate_limit|network_problem|robots_disallowed|stopped_on_request|reader_kept_failing)\b", text), text
    # The numbers are the report's.
    coverage = status["content_coverage"]
    assert str(coverage["readable_unique_urls"]) in view["rows"][1]["note"] or coverage["level"] == "none"
    assert len(view["rows"][1]["note"].split("; ")) >= len(coverage["reasons"])
    for number in re.findall(r"\d+", sentence):
        assert number in shown, (number, shown)
    assert (view["cache_note"] is not None) == (english["cache_note"] is not None)
    if view["cache_note"]:
        assert "2026-10-01 08:15" in view["cache_note"] and view["cache_note"].startswith("Kayıtlı kopyalar: ")


def test_stop_codes_come_out_as_words_and_an_unknown_reason_takes_the_mark():
    sentence = "The audit finished but is incomplete (page_cap: page cap of 50 reached; 694 discovered URL(s) were not read). Findings cover only what was fetched."
    assert wording.outcome(sentence, "tr") == ("Denetim bitti ancak eksik (sayfa sınırı: 50 sayfalık sınıra ulaşıldı; keşfedilen 694 URL okunmadı). "
                                               "Bulgular yalnızca getirilen sayfaları kapsar.", True)
    assert wording.reason("Maya's crawl stopped: page_cap (page cap of 50 reached)", "tr") == ("Maya'nın taraması durdu: sayfa sınırı (50 sayfalık sınıra ulaşıldı)", True)
    assert wording.reason("694 more discovered URL(s) remain unchecked (the page cap of 50 was reached)", "tr")[0] == \
        "keşfedilen 694 URL daha kontrol edilmedi (50 sayfalık sınıra ulaşıldı)"
    odd = "reading stopped early (a made-up provider said something new)"
    assert wording.reason(odd, "tr") == (odd + MARK, False) and wording.reason(odd, "en") == (odd, True)
    new = "The audit did a made-up thing nobody planned for."
    assert wording.outcome(new, "tr") == (new + MARK, False) and wording.outcome(new, "en") == (new, True)


# -- the pages a person sees ---------------------------------------------------------------------------------------------

def section(html, start, end):
    at = html.index(start)
    return html[at:html.index(end, at + len(start))]


def test_the_turkish_report_of_a_demo_audit_has_turkish_titles_fixes_and_coverage_and_says_it_is_a_draft(web):
    client = web()
    audit = audit_of(client)  # the demo shop, audited in English
    saved = client.get(f"{API}/audits/{audit['id']}/result")
    english_rows = get(client, audit, "/findings", limit=100)["items"]
    report = saved.json()
    by_id = {f["id"]: f for check in report["checks"] for f in check["findings"]}
    assert english_rows and all(row["title"] == by_id[row["id"]]["title"] and row["fix"] == by_id[row["id"]]["how_to_fix"] for row in english_rows)
    assert not any(row["untranslated"] for row in english_rows) and not any("(s)" in row["title_shown"].replace('(href="#")', "") for row in english_rows)
    assert any("(s)" in row["title"] for row in english_rows)  # the report's own words are untouched
    english_page = client.get(f"{API}/audits/{audit['id']}/print?full=true").text
    assert english_page.startswith('<!doctype html><html lang="en">') and "Türkçe çeviri taslaktır" not in english_page and MARK not in english_page
    english_view = get(client, audit, "/summary")
    # Stopped at its page limit only: a partial audit, said with its figures (DECISIONS 226).
    assert english_view["outcome"]["reason"] == audit["outcome"]["reason"] and audit["outcome"]["reason"].startswith("Partial audit: ")
    assert english_view["outcome"]["label"].startswith("Partial audit: ") and english_view["outcome"]["label"].endswith("pages read (page limit)")
    assert english_view["outcome"]["reason_shown"] == wording.english(audit["outcome"]["reason"]) and "(s)" not in english_view["outcome"]["reason_shown"]

    assert client.put(f"{API}/session/language", json={"language": "tr"}).status_code == 200
    assert client.get(f"{API}/audits/{audit['id']}/result").content == saved.content  # the saved report, byte for byte, in both languages
    rows = get(client, audit, "/findings", limit=100)["items"]
    assert [(row["id"], row["title"], row["fix"], row["expected"], row["notes"]) for row in rows] == \
        [(row["id"], row["title"], row["fix"], row["expected"], row["notes"]) for row in english_rows]
    assert [row["title_shown"] for row in rows if row["untranslated"]] == []
    assert not any(MARK in text or "(s)" in text.replace('(href="#")', "") for row in rows for text in (row["title_shown"], row["fix_shown"], row["expected_shown"]))
    assert all(row["title_shown"] != row["title"] and row["fix_shown"] != row["fix"] for row in rows)
    view = get(client, audit, "/summary")
    assert view["outcome"]["reason"] == english_view["outcome"]["reason"] and view["outcome"]["reason_shown"] != view["outcome"]["reason"]
    assert MARK not in view["outcome"]["reason_shown"] and not view["outcome"]["reason_untranslated"] and view["status"]["untranslated"] == 0
    assert get(client, audit)["outcome"]["reason_shown"] == view["outcome"]["reason_shown"]
    executive = view["practical"]["executive"]
    shown = {row["title_shown"] for row in rows}
    assert executive["problems"] and all(problem["title"] in shown for problem in executive["problems"])
    assert executive["actions"] and all(not ENGLISH_WORDS.search(action["text"]) and set(action["titles"]) <= shown for action in executive["actions"])
    assert not any(MARK in line for line in executive["opportunities"])

    page = client.get(f"{API}/audits/{audit['id']}/print?full=true&lang=tr").text
    assert page.startswith('<!doctype html><html lang="tr">')
    assert '<p class="muted small review-note">Türkçe çeviri taslaktır; ana dili Türkçe olan biri tarafından gözden geçirilecektir.</p>' in page
    cover = section(page, '<section class="cover">', "</section>")
    assert "Türkçe çeviri taslaktır" in cover
    for part in (section(page, '<section class="exec', "</section>"), section(page, '<section class="bypage-sec">', "</section>"),
                 section(page, f"<h2>{strings.t('pdf.findings_by_area', 'tr')}</h2>", "<h2>")):
        assert MARK.strip() not in part and "(s)" not in part.replace("(href=&quot;#&quot;)", "")
    exec_page = section(page, '<section class="exec', "</section>")
    from html import escape
    assert escape(view["outcome"]["reason_shown"], quote=True) in exec_page and escape(view["outcome"]["reason"], quote=True) not in exec_page
    for row in view["status"]["rows"]:
        assert escape(row["note"], quote=True) in exec_page and not ENGLISH_WORDS.search(row["note"]), row["note"]
    for action in executive["actions"]:
        assert escape(action["text"], quote=True) in exec_page
    # The Markdown and the JSON downloads stay the engine's English.
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown").text
    assert audit["outcome"]["reason"] in markdown and "sayfanın" not in markdown
    assert client.get(f"{API}/audits/{audit['id']}/downloads/json").content == saved.content
    # Search finds a finding by the words shown as well as by the report's own.
    word = rows[0]["title_shown"].split()[-1]
    assert get(client, audit, "/findings", q=word)["total"] >= 1
