"""The whole Turkish report, not only its findings: check and gate titles and summaries, what could not be checked and
why, the Firecrawl, DataForSEO, Core Web Vitals and archive panels, the allow-list steps. Each kind is read from the
engine's own source (or made by the engine's own function) and must have a Turkish wording; what is knowingly not
covered is named in an allow-list here, never passed over. The saved report stays English, byte for byte.

Every site, provider and run here is made up. Nothing is requested.
"""
import ast
import json
import re
from html import unescape
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

import maya_audit  # noqa: E402
from maya_audit import allowlist, archives, crux, ownership  # noqa: E402
from maya_audit.dataforseo import insights  # noqa: E402
from maya_audit.dataforseo import panel as dfs_panel  # noqa: E402
from maya_audit.firecrawl import panel as fc_panel  # noqa: E402
from maya_audit.firecrawl import reader as fc_reader  # noqa: E402
from maya_audit_web import demo, paid, strings, summary, wording  # noqa: E402
from test_firecrawl import Firecrawl  # noqa: E402
from test_web_app import API, Site, cloudflare, confirm, get, plan, start, web  # noqa: E402,F401
from test_web_firecrawl import PAGES, services  # noqa: E402

MARK = " (İngilizce)"
TR = wording.TABLES["tr"]
ENGINE = Path(maya_audit.__file__).parent
CHECK_FILES = [*sorted((ENGINE / "checks").glob("*.py")), ENGINE / "technical_seo.py"]


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    strings.set_language("en")


def turkish(kind, text, check_id=None):
    """(shown, translated) for one engine sentence of a kind."""
    return {"label": wording.label, "line": wording.line}[kind](text, "tr", check_id=check_id)


# -- "1 page", not "1 page(s)", in English ---------------------------------------------------------------------------------

@pytest.mark.parametrize("engine, shown", [
    ("1 URL(s) were skipped per robots.txt.", "1 URL was skipped per robots.txt."),
    ("0 URL(s) were skipped per robots.txt.", "0 URLs were skipped per robots.txt."),
    ("this check ran on the 3 page(s) that were read; 1 more page(s) were found and not read", "this check ran on the 3 pages that were read; 1 more page was found and not read"),
    ("2 finding(s): 1 link(s) to content without an address a crawler can follow, 2 footer entry(ies) without an address", "2 findings: 1 link to content without an address a crawler can follow, 2 footer entries without an address"),
    ("1 other fetch(es) got no answer and were not checked", "1 other fetch got no answer and were not checked"),
    ("All 3 job page(s) and careers list(s) read carry JobPosting structured data.", "All 3 job pages and careers lists read carry JobPosting structured data."),
    ("Left out as not content: 0 tracking, consent or hidden iframe(s) and 1 decorative canvas(es).", "Left out as not content: 0 tracking, consent or hidden iframes and 1 decorative canvas."),
    ("so 7 template(s) and 1 key page(s) were not rendered", "so 7 templates and 1 key page were not rendered"),  # two things: the verb stays plural
    ("1 page(s) marked noindex were not rendered", "1 page marked noindex was not rendered"),
    ("1 link(s) to another site use the path of a page on this one.", "1 link to another site uses the path of a page on this one."),
    ("5 of 6 page request(s)", "5 of 6 page requests"), ("Cloudflare on 1 of 1 request(s). 3 page(s) were read", "Cloudflare on 1 of 1 request. 3 pages were read"),
    ("about 1,840.5 estimated organic visit(s) a month", "about 1,840.5 estimated organic visits a month"),
    ("rated 4.4 from 212 review(s)", "rated 4.4 from 212 reviews"), ("1 keyword(s) rank in positions 4 to 20", "1 keyword ranks in positions 4 to 20"),
    ("Restore the missing page(s) or remove the links.", "Restore the missing pages or remove the links."),  # no number: a plain plural
    ("served over http(s)://", "served over http(s)://"), ("No brackets here.", "No brackets here."),
])
def test_english_says_one_page_and_three_pages_where_the_engine_writes_page_s(engine, shown):
    assert wording.english(engine) == shown
    assert wording.line(engine, "en") == (shown, True) and wording.label(engine, "en") == (shown, True)


# -- check and gate titles, and the parts of a check that were not assessed -----------------------------------------------------

def check_and_gate_titles():
    """Every title a check or a gate can carry: `title = "..."` in its function, or a literal in the call."""
    found = set()
    for path in CHECK_FILES:
        source = path.read_text(encoding="utf-8")
        found.update(re.findall(r'^\s+title = "([^"]+)"$', source, re.MULTILINE))
        found.update(re.findall(r'(?:CheckResult|GateResult)\(\s*"[A-Z]+-\d+",\s*"([^"]+)"', source))
    return found


def coverage_calls():
    """The `part(name, reason, ...)`, `_listed(evidence, key, count key, name, reason)` and `_left_out(reason)` calls of
    maya_audit.coverage, as (name node, reason node)."""
    out = []
    for node in ast.walk(ast.parse((ENGINE / "coverage.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("part", "_listed", "_left_out") and node.args:
            names = {"part": (0, 1), "_listed": (3, 4), "_left_out": (None, 0)}[node.func.id]
            if len(node.args) > names[1]:
                out.append((node.args[names[0]] if names[0] is not None else None, node.args[names[1]]))
    return out


def test_every_check_title_gate_title_and_unassessed_part_has_a_turkish_name():
    titles = check_and_gate_titles()
    assert len(titles) >= 61 and {"robots.txt availability", "Crawl completeness", "Retrieval vs training attribution note", "Thin content"} <= titles
    parts = {node.value for node, _ in coverage_calls() if isinstance(node, ast.Constant)} | {"pages found but not read", "pages left out of this comparison",
                                                                                               "pages not checked because the crawl was incomplete"}
    assert len(parts) >= 45 and "og:image URLs" in parts
    # The one part whose name is a variable is the helper's own parameter (`part(name, reason, n, lower)` inside `_listed`).
    assert [ast.unparse(node) for node, _ in coverage_calls() if node is not None and not isinstance(node, ast.Constant)] == ["CRAWL_GAP", "name", "f'links in {name}'"]
    # ACC-8's part is named after the file it is about (DECISIONS 208).
    for file in ("llms.txt", "llms-full.txt"):
        assert wording.label(f"links in {file}", "tr")[1]
    for text in sorted(titles | parts):
        shown, translated = wording.label(text, "tr")
        assert translated and MARK not in shown and shown.strip(), f"no Turkish name for {text!r}"
        assert wording.label(text, "en") == (text, True)
    assert sum(1 for text in titles | parts if wording.label(text, "tr")[0] == text) <= 2  # "robots.txt ..." names apart, each is reworded


# -- check and gate summaries -----------------------------------------------------------------------------------------------------

def sample(node):
    """Every text a string expression can make, with 3 where a value goes ("3%" for a percentage, "'3'" for a quoted value)."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else ["3"]
    if isinstance(node, ast.JoinedStr):
        out = [""]
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                out = [text + piece.value for text in out]
            else:
                spec = ast.unparse(piece.format_spec) if piece.format_spec else ""
                out = [text + ("3%" if "%" in spec else "'3'" if piece.conversion == 114 else "3") for text in out]
        return out
    if isinstance(node, ast.IfExp):
        return sample(node.body) + sample(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [left + right for left in sample(node.left) for right in sample(node.right)]
    return ["3"]


def engine_summaries():
    """Every summary a check or a gate can write, as (check id, sample): each `summary = ...`, `summary += ...` and each
    summary written in the `CheckResult(` or `GateResult(` call itself, read from the engine's source."""
    out = []
    for path in CHECK_FILES:
        for function in [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.FunctionDef)]:
            results = [call for call in ast.walk(function) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in ("CheckResult", "GateResult")]
            ids = {call.args[0].value for call in results if call.args and isinstance(call.args[0], ast.Constant)}
            if len(ids) != 1:
                continue  # a helper that passes a check id on (the answer-engine panel's "no data" results): read below
            check_id = ids.pop()
            for node in ast.walk(function):
                written = []
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "summary" for target in node.targets):
                    written.append(node.value)
                if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "summary":
                    written.append(node.value)
                if node in results:
                    at = 3 if node.func.id == "CheckResult" else 4
                    if len(node.args) > at and not isinstance(node.args[at], ast.Name):
                        written.append(node.args[at])
                out += [(check_id, text) for expression in written for text in sample(expression)]
    return out


# A summary whose sample holds a 3 where a phrase, a list or another sentence goes: the sample as read from the source ->
# summaries as the engine writes them. Each listed sample is checked to be one the source still makes.
BUILT_SUMMARIES = {
    # STR-21 says after its summary which kinds are linked from the footer and were not read (DECISIONS 197).
    ("STR-21", "1 finding: not found: 3.3"): ["1 finding: not found: FAQ. Contact: linked from the footer (/bize-ulasin), not among the pages read."],
    ("STR-21", "No basic page is missing among the 3 page(s) read. 3"): [
        "No basic page is missing among the 12 page(s) read. Contact: linked from the footer (/bize-ulasin), not among the pages read. "
        "About: linked from the footer (/hikayemiz/), not among the pages read."],
    ("STR-21", "Not found among the 3 page(s) read: 3. The crawl did not read every page it found, so they may exist.3"): [
        "Not found among the 48 page(s) read: Product or service, FAQ. The crawl did not read every page it found, so they may exist. "
        "Contact: linked from the footer (/bize-ulasin), not among the pages read."],
    ("ACC-1", "robots.txt answered 3 on all 3 fetches (3)."): [
        "robots.txt answered [200] on all 3 fetches (parsed normally).", "robots.txt answered [403] on all 1 fetches (RFC 9309 treats 4xx as no restrictions).",
        "robots.txt answered [429] on all 2 fetches (rate limited: back off and retry later)."],
    ("ACC-2", "3 finding(s); most severe: [3] 3"): [
        "3 finding(s); most severe: [S2] robots.txt line 4 (Disallow: /) blocks search bot(s) GPTBot, OAI-SearchBot sitewide",
        "1 finding(s); most severe: [Info] robots.txt line 3 (Disallow: /cart) blocks training bot(s) GPTBot on 1 sampled URL(s)"],
    ("ACC-4", "3 Reason: 3. robots.txt rules (ACC-2) were checked, but they cannot show WAF or edge blocks."): [
        "Firewall blocking was not assessed. Reason: ownership not verified (no site verification token configured). robots.txt rules (ACC-2) were checked, but they cannot show WAF or edge blocks.",
        "Firewall blocking was not assessed. Reason: probes disabled in configuration. robots.txt rules (ACC-2) were checked, but they cannot show WAF or edge blocks.",
        "Firewall blocking was not assessed. Reason: ownership not verified (homepage has no verification meta tag matching the configured token; the domain has no DNS TXT record matching the configured token). "
        "robots.txt rules (ACC-2) were checked, but they cannot show WAF or edge blocks."],
    ("ANS-2", "3 finding(s) and 3 review item(s) from 3 claim(s) across 3 engine(s). 3."): [
        "1 finding(s) and 2 review item(s) from 9 claim(s) across 2 engine(s). citation data from made-up-export.json, fetched 2026-10-01T08:00:00Z (upstream refresh: daily)."],
    ("ANS-2", "All 3 claim(s) match the cited pages. 3."): ["All 4 claim(s) match the cited pages. citation data from made-up-export.json, fetched 2026-10-01T08:00:00Z (upstream refresh: daily)."],
    ("ANS-2", "Not assessed: 3"): [
        "Not assessed: no claims in the citation file and no prices in the answer text",
        "Not assessed: 3 of 5 record(s) carry neither claims nor answer text, so there is nothing to compare. Maya's citation API returns no answer text today (README), "
        "so this check needs claims in the citation file."],
    ("IDX-2", " 3."): [
        "Certificates valid and http:// redirects to https:// on made-up.example. www variant not checked: the start URL is served over plain http.",
        "Certificates valid and http:// redirects to https:// on shop.made-up.example. no www variant checked: shop.made-up.example is not a registrable domain (it is a subdomain, "
        "or a host on a shared hosting domain), so www.shop.made-up.example is not an address this site is reached by.",
        "Certificates valid and http:// redirects to https:// on made-up.example. www variant www.made-up.example does not resolve (NXDOMAIN); nothing to check."],
    ("INT-1", " Only 3 rest on Verified classifications, so this result is an estimate."): [
        "Audit degraded: 6/20 (30.0%) of fetched pages were blocked or rate-limited, at or above the 20% threshold. Only 2/20 (10.0%) rest on Verified classifications, so this result is an estimate."],
    ("INT-1", "3 of fetched pages were blocked or rate-limited, below the 3% threshold; the audit is not degraded."): [
        "2/50 (4.0%) of fetched pages were blocked or rate-limited, below the 20% threshold; the audit is not degraded. 1 page(s) failed at the transport level."],
    ("RND-5", "3 finding(s).3"): ["2 finding(s).", "1 finding(s). Consent, login, age, geo, and paywall text signatures are English and Turkish only: 7 page(s) without a match were NOT assessed "
                                  "(another language, or language unknown), so no wall found there means nothing."],
    ("RND-5", "Redirect walls: none found. In-page walls and paywalls: not assessed.3"): [
        "Redirect walls: none found. In-page walls and paywalls: not assessed. Consent, login, age, geo, and paywall text signatures are English and Turkish only: 12 page(s) without a "
        "match were NOT assessed (another language, or language unknown), so no wall found there means nothing."],
    ("RND-5", "No walls or unmarked paywalls detected on 3 English or Turkish page(s); redirect walls checked on every page.3"): [
        "No walls or unmarked paywalls detected on 48 English or Turkish page(s); redirect walls checked on every page."],
}
# Summaries that are other sentences put together at run time, as the engine writes them (their pieces are in the engine's source).
MORE_SUMMARIES = [
    ("ACC-6", ("· Live fetch", "partly blocked ("), "OpenAI: Training (GPTBot): blocked · Search (OAI-SearchBot): allowed · Live fetch (ChatGPT-User): partly blocked (2/5 sampled URLs) | "
                                                     "Common Crawl: Training (CCBot): blocked · Search: no token · Live fetch: no token"),
    ("ACC-8", ("is present",), "llms.txt is present, llms-full.txt is present"),
    ("ACC-1", ("Applied policy: {policy.reason}.", "robots.txt parsed"), "robots.txt answered [200] on all 3 fetches (parsed normally). Applied policy: robots.txt parsed."),
    ("ACC-1", ("got no answer and were not checked", "network problem on this computer"),
     "robots.txt answered [200] on all 2 fetches (parsed normally). Applied policy: robots.txt parsed. 1 other fetch(es) got no answer and were not checked (network problem on this computer)."),
    ("ACC-1", ("none of {len(samples)} robots.txt fetch(es) got an answer", "no answer reached this computer; whether the site or the connection failed is not known"),
     "Not checked (no answer reached this computer; whether the site or the connection failed is not known): none of 3 robots.txt fetch(es) got an answer. Nothing is reported against the site."),
    ("ACC-2", ("Not checked: {policy.reason}.",), "Not checked: robots.txt was not checked: network problem on this computer (E-123). This says nothing about the site; Maya's own crawler requested no page."),
    ("ACC-2", ("ACC-1 reports the sitewide block",), "robots.txt unavailable (robots.txt returned 503; RFC 9309: assume complete disallow); ACC-1 reports the sitewide block."),
    ("ACC-9", ("page request(s) to Maya's crawler",), "1 finding: Cloudflare (bot challenge) answered 5 of 6 page request(s) to Maya's crawler; 1 page(s) were read."),
    ("ACC-9", ("answered Maya's direct crawler;",), "1 note: Cloudflare (bot challenge) answered Maya's direct crawler; 3 page(s) were read through Firecrawl. Genuine AI-crawler access was not measured."),
    ("IDX-1", ("Missing-page test: {verdict['text']}.", "a made-up address answers {status}, as it should"),
     "No 4xx, persistent 5xx, or persistent transport errors across 51 fetched URL(s). Missing-page test: a made-up address answers 404, as it should."),
    ("IDX-1", ("a made-up address redirects ({status}) to the homepage",), "2 finding(s) across 51 fetched URL(s). Missing-page test: a made-up address redirects (301) to the homepage."),
    ("IDX-1", ("not run ({probe.get('reason')})", "no page of the site answered 200, so a missing page cannot be told from the rest"),
     "No 4xx, persistent 5xx, or persistent transport errors across 1 fetched URL(s). Missing-page test: not run (no page of the site answered 200, so a missing page cannot be told from the rest)."),
    ("IDX-7", ("No deep pages; orphans {orphan_status}.", "not assessed: crawl incomplete ({int2.summary})"),
     "No deep pages; orphans not assessed: crawl incomplete (Incomplete: stopped early (page_cap): page cap of 50 reached.)."),
    ("IDX-7", ("this site writes links with JavaScript (", "page(s) of the rendering sample had clearly more links than their raw HTML"),
     "1 finding(s); orphans not assessed: this site writes links with JavaScript (3 page(s) of the rendering sample had clearly more links than their raw HTML), and only some pages "
     "were rendered, so a page without a known link may still be linked."),
    ("IDX-10", ("Bing lookups not run: {data.bing_skipped} ",),
     "Bing lookups not run: launch-gated: the Bing Webmaster JSON endpoint path and response shape are not verified against Microsoft's documentation (their published example is XML). "
     "Calls to the real API stay disabled until someone confirms them and sets bing_api_verified in code. Index status itself cannot be verified from Bing's documented API."),
    ("PRF-1", ("Not assessed: {reason}.", "no sampled URL had {cfg.prf_min_samples} successful fetches"), "Not assessed: no sampled URL had 3 successful fetches."),
    ("PRF-2", ("The 3-attempt sampling did not run ({reason})", "the extra fetch rounds did not run"),
     "0 failure(s) in 51 counted fetch(es); no URL failed intermittently. The 3-attempt sampling did not run (the extra fetch rounds did not run), so only crawl fetches and IDX-1 refetches count."),
    ("STR-6", ("no date is in the future, and article pages show a date.", "date signals agree on the {compared_pages} of {len(rows)} page(s) that carry two or more"),
     "Date signals agree on the 12 of 48 page(s) that carry two or more; no date is in the future, and article pages show a date."),
    ("STR-6", ("carries two date signals, so agreement",), "None of the 48 page(s) carries two date signals, so agreement could not be checked; no date is in the future, and article pages show a date."),
    ("STR-18", ("the homepage title does not contain", '" or ".join(repr(n) for n in names)'), "1 finding: the homepage title does not contain 'Made-Up Kettles' or 'made-up-kettles'."),
    ("STR-21", ("Not found among the {len(pages)} page(s) read:",), "Not found among the 48 page(s) read: Product or service, Contact, FAQ. The crawl did not read every page it found, so they may exist."),
    ("STR-23", ("careers page(s) listing openings", "' and '.join(parts)"), "2 finding(s): 3 of 4 job page(s) and 1 careers page(s) listing openings."),
    ("STR-1", ("Source: Firecrawl",), "Source: Firecrawl. All 48 indexable page(s) have distinct, non-generic titles (English placeholder list)."),
    ("STR-2", ("Maya could read none of the {access['fetched']} page(s) it fetched",),
     "Not assessed: Maya could read none of the 1 page(s) it fetched (1 blocked or rate-limited; see INT-1), so there was nothing to check. (Before this: All 0 page(s) have one <h1> and long pages are sectioned.)"),
    ("INT-2", ("stopped early ({result.stop_reason.value}): {result.stop_detail}", "page(s) could not be read, so links on them were not followed"),
     "Incomplete: stopped early (page_cap): page cap of 50 reached; 2 page(s) could not be read, so links on them were not followed."),
    ("INT-2", ("assembled from {len(rows)} sessions between",), "Incomplete: assembled from 2 sessions between 2026-10-01T08:00:00+00:00 and 2026-10-02T09:00:00+00:00; pages were not all seen at the same moment."),
    ("INT-4", ("Violation: ", "request(s) went to URLs robots.txt disallows", "smallest gap between requests to {host} was"),
     "Violation: 2 request(s) went to URLs robots.txt disallows; smallest gap between requests to demo-kafe.test was 120ms, below the required 1000ms."),
    ("INT-4", ("the audit deadline expired before any HTTP request could be attempted",),
     "Not assessed: the audit deadline expired before any HTTP request could be attempted. Requests skipped after the deadline are excluded from INT-4."),
    ("INT-1", ("the start URL was {start.fetch_class.value}",), "Audit degraded: 1/1 (100.0%) of fetched pages were blocked or rate-limited, at or above the 20% threshold; the start URL was blocked."),
]
# Knowingly not covered: shown whole, in English, with the mark. (check id, what) -> why.
SUMMARIES_NOT_COVERED = {
    ("IDX-2", "a host's own TLS or redirect error text"): "the network library's words for one host (`tls['error']`), joined with '; ': free text, not a sentence of the engine",
    ("INT-4", "Maya's optional information page could not be checked ({reason})"): "the reason is the fetcher's own error text; the frame is translated, an English reason inside it stays as the value it is",
}


def test_every_check_and_gate_summary_the_engine_can_write_has_a_turkish_wording():
    samples = engine_summaries()
    assert len(samples) > 200 and {check_id for check_id, _ in samples} >= {"ACC-1", "IDX-5", "RND-5", "STR-19", "STR-23", "TSEO-1", "PRF-2", "ANS-1", "ANS-5", "INT-1", "INT-3", "INT-4"}
    uncovered = set()
    for check_id, text in samples:
        if text.strip() in ("", "3"):
            continue  # a whole summary taken from a variable: `MORE_SUMMARIES` holds what such variables are made of
        shown, translated = wording.line(text.strip(), "tr", check_id=check_id)
        if translated:
            assert MARK not in shown and "(s)" not in shown and shown != text.strip(), (check_id, shown)
            assert "(s)" not in wording.line(text.strip(), "en")[0], (check_id, wording.line(text.strip(), "en")[0])
        else:
            uncovered.add((check_id, text))
    assert uncovered == set(BUILT_SUMMARIES), f"summaries with no Turkish wording and no listed sample: {sorted(uncovered ^ set(BUILT_SUMMARIES))}"
    sources = "".join(path.read_text(encoding="utf-8") for path in [*CHECK_FILES, *ENGINE.glob("*.py"), *(ENGINE / "firecrawl").glob("*.py")])
    built = [(check_id, text) for (check_id, _), texts in BUILT_SUMMARIES.items() for text in texts]
    for check_id, pieces, text in MORE_SUMMARIES:
        for piece in pieces:
            assert piece in sources, f"{check_id}: the engine's source no longer holds {piece!r}"
        built.append((check_id, text))
    for check_id, text in built:
        shown, translated = wording.line(text, "tr", check_id=check_id)
        assert translated and MARK not in shown and "(s)" not in shown, f"{check_id}: no Turkish for {text!r}"
        assert "(s)" not in wording.line(text, "en")[0]
    # Numbers, bot names, addresses and quoted values come through unchanged.
    said = wording.line("robots.txt answered [403] on all 1 fetches (RFC 9309 treats 4xx as no restrictions). Applied policy: robots.txt returned 403; RFC 9309: unavailable, crawling allowed.", "tr")[0]
    assert "[403]" in said and "RFC 9309" in said and "robots.txt" in said
    said = wording.line("3 finding(s); most severe: [S2] robots.txt line 4 (Disallow: /) blocks search bot(s) GPTBot, OAI-SearchBot sitewide", "tr", check_id="ACC-2")[0]
    assert said.startswith("3 bulgu; en ciddisi: [S2] robots.txt 4. satır (Disallow: /)") and "GPTBot, OAI-SearchBot" in said
    assert wording.line("1 finding: the homepage title does not contain 'Made-Up Kettles' or 'made-up-kettles'.", "tr")[0].endswith("'Made-Up Kettles' veya 'made-up-kettles'.")
    # A sentence nobody listed is shown whole, in English, with the mark; one unknown sentence marks the whole run of sentences.
    odd = "2 finding(s). A made-up sentence the engine will only say next year."
    assert wording.line(odd, "tr") == (odd + MARK, False) and wording.line(odd, "en") == ("2 findings. A made-up sentence the engine will only say next year.", True)
    assert wording.label("A made-up check title", "tr") == ("A made-up check title" + MARK, False)
    for (_, what), why in SUMMARIES_NOT_COVERED.items():
        assert what and why


# -- the answer-engine panel's findings ---------------------------------------------------------------------------------------------

# The panel's notes are put together per finding from the citation data (which site check a failure was copied from,
# how a claim was compared): knowingly not covered, shown in English with the mark.
ANS_NOT_COVERED = {"the notes of the answer-engine panel's findings (ANS-1, ANS-2, ANS-4)": "built per finding from the citation data; no pattern yet"}


def test_the_answer_engine_panels_findings_have_turkish_titles_fixes_and_expected_results():
    from test_wording import KEYWORDS, POSITIONS
    found = {"expected": set(), "fix": set()}
    for node in ast.walk(ast.parse((ENGINE / "checks" / "answers.py").read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("Finding", "ReviewItem")):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        for kind, position in zip(("expected", "fix"), POSITIONS[node.func.id]):
            value = next((keywords[name] for name in KEYWORDS[kind] if name in keywords), None)
            if value is None and position < len(node.args):
                value = node.args[position]
            assert isinstance(value, ast.Constant) and isinstance(value.value, str), ast.unparse(value)  # every one is a fixed sentence
            found[kind].add(value.value)
    assert len(found["expected"]) == 4 and len(found["fix"]) == 4
    for kind, translate in (("expected", wording.expected), ("fix", wording.fix)):
        for text in found[kind]:
            shown, translated = translate(text, "tr")
            assert translated and MARK not in shown and shown != text, f"no Turkish for the answer panel's {kind} {text!r}"
    for check_id, title in (("ANS-1", "Cited URL fails a site check (http_404, noindex): https://made-up.example/old-pricing"),
                            ("ANS-2", "2 answer(s) state a price or plan that the cited page contradicts"), ("ANS-2", "1 answer claim(s) state something the cited page does not show"),
                            ("ANS-4", "perplexity cited 41 domain-mentions on this topic and none from this site")):
        shown, translated = wording.title(check_id, title, "tr")
        assert translated and MARK not in shown and "(s)" not in shown and "(s)" not in wording.title(check_id, title, "en")[0], title
    assert "https://made-up.example/old-pricing" in wording.title("ANS-1", "Cited URL fails a site check (http_404, noindex): https://made-up.example/old-pricing", "tr")[0]
    assert wording.title("ANS-2", "1 answer(s) state a fact that the cited page contradicts", "en")[0] == "1 answer states a fact that the cited page contradicts"
    assert ANS_NOT_COVERED


# -- why a part of a check was not assessed ------------------------------------------------------------------------------------------

# A reason that maya_audit.coverage takes from a check's evidence: the source expression -> reasons as the engine writes them.
REASONS_FROM_EVIDENCE = {
    "never.removeprefix('not assessed: ')": ["no IP ranges loaded for any search bot"],
    "f\"probe cap of {ev.get('cap')} requests reached before every pair was probed\"": ["probe cap of 40 requests reached before every pair was probed"],
    "str(probe.get('verdict'))": [],  # the verdict is a dict in the evidence; its text is the missing-page sentences of IDX-1 (`MORE_SUMMARIES`)
    "'; '.join(ev['not_assessed'])[:300]": ["made-up.example: loopback test run over http; HTTPS not probed", "made-up.example: TLS not checked", "made-up.example: HTTP to HTTPS redirect not checked"],
    "orphans.removeprefix('not assessed: ')": [
        "crawl incomplete (Incomplete: stopped early (page_cap): page cap of 50 reached.)",
        "this site writes links with JavaScript (2 page(s) rendered during the crawl had clearly more links than their raw HTML), and only some pages were rendered, "
        "so a page without a known link may still be linked"],
    "status.removeprefix('not assessed: ')": ["Bing's documented UrlInfo object (GetUrlInfo) has no field that states whether a URL is indexed, so 'not indexed' cannot be verified."],
    "reason": ["on another site; external link checks are off (--no-external-links)", "the audit's time limit was reached before this image was checked",
               "robots.txt for https://cdn.made-up.example disallows it: disallowed by line 3: Disallow: /img/"],
    "completeness.removeprefix('incomplete: ')": ["paged: 100 of 250 record(s) returned", "every one of 4 record(s) was invalid"],
    "f'{reason} ({detail})'": [
        "a shared description on these pages could not be judged fairly (1 content arrives after JavaScript runs (RND-1); 2 page 2, 3, ... of a list; 1 language version of a page already counted)",
        "whether these pages lead on could not be told from their HTML, or they end by design (1 page with a form; 3 thank-you, confirmation, login, legal or cart page; "
        "1 runs scripts and was not opened in a browser, so its links may be added there; 2 page cut at the size limit)",
        "their own text arrives only after JavaScript runs, so its length could not be judged (2 content arrives after JavaScript runs (RND-1))"],
    "f'this check ran on the {read} page(s) that were read' + (f'; {unread} more page(s) were found and not read' if unread else '') + f' ({detail}). Its result says nothing about pages that were not read'": [
        "this check ran on the 50 page(s) that were read; 536 more page(s) were found and not read (page cap of 50 reached). Its result says nothing about pages that were not read",
        "this check ran on the 3 page(s) that were read; 1 more page(s) were found and not read (every discovered URL was fetched or skipped). Its result says nothing about pages that were not read",
        "this check ran on the 12 page(s) that were read (time limit of 300s reached). Its result says nothing about pages that were not read",
        "this check ran on the 9 page(s) that were read; 4 more page(s) were found and not read (stopped on request before every page was fetched). Its result says nothing about pages that were not read",
        "this check ran on the 20 page(s) that were read; 2 more page(s) were found and not read (overall audit deadline reached during post-crawl checks). Its result says nothing about pages that were not read"],
    "f\"rendering did not run ({ev.get('render_reason')}); pages were checked with raw-HTML heuristics only, and finding no signal is not evidence of no gap\"": [
        "rendering did not run (rendering disabled in configuration); pages were checked with raw-HTML heuristics only, and finding no signal is not evidence of no gap",
        "rendering did not run (Playwright is not installed (pip install playwright; playwright install chromium)); pages were checked with raw-HTML heuristics only, and finding no signal is not evidence of no gap"],
    "f\"the crawl stopped at {ev.get('crawl_stop_reason')}; their metadata and headings were not read\"": [
        "the crawl stopped at page_cap; their metadata and headings were not read", "the crawl stopped at time_limit; their metadata and headings were not read"],
}
# Why a sitemap URL or an llms.txt link was not checked (DECISIONS 206, 208): each reason of the two tables.
from maya_audit.coverage import LLMS_NOT_CHECKED, SITEMAP_NOT_CHECKED  # noqa: E402

REASONS_FROM_EVIDENCE["SITEMAP_NOT_CHECKED[key]"] = list(SITEMAP_NOT_CHECKED.values())
REASONS_FROM_EVIDENCE["LLMS_NOT_CHECKED[key]"] = list(LLMS_NOT_CHECKED.values())
# An image file on another site that the other-site check did not ask (DECISIONS 211) gives one of its reasons.
from maya_audit.external_links import REASONS as EXTERNAL_REASONS  # noqa: E402
REASONS_FROM_EVIDENCE["reason"] += list(EXTERNAL_REASONS.values())
# ACC-4 without ownership: the browser itself got an empty or error page (DECISIONS 216).
from maya_audit.probes import BROWSER_NOT_REAL_REASON  # noqa: E402
REASONS_FROM_EVIDENCE["BROWSER_NOT_REAL_REASON"] = [BROWSER_NOT_REAL_REASON]
REASONS_NOT_COVERED = {
    "an IDX-2 host's own TLS or redirect error text": "the network library's words for one host; shown in English with the mark",
    "the detail of a crawl that stopped for a reason this layer has no sentence for": "shown in English with the mark, like any new stop detail (run B's rule)",
}


REASONS_FROM_EVIDENCE["f\"{len(roles)} saved role records represent {len(instances)} distinct page/element/source/time instances; {len({r.get('src') for r in roles if r.get('src')})} source image URLs. Purpose, displayed CSS/pixels and equivalent text require review; neither a pass nor a confirmed missing description.\""] = ['3 saved role records represent 3 distinct page/element/source/time instances; 3 source image URLs. Purpose, displayed CSS/pixels and equivalent text require review; neither a pass nor a confirmed missing description.']


def _canonical_source(source: str) -> str:
    """The expression's syntax tree. ast.unparse writes f-string quotes differently across Python versions
    (3.11, 3.12, 3.13), so the reasons are compared as trees, not as text."""
    return ast.dump(ast.parse(source, mode="eval").body)


def test_every_reason_a_part_was_not_assessed_has_a_turkish_wording():
    fixed, built, heads = [], set(), []
    for name, node in coverage_calls():
        if isinstance(node, ast.Constant):
            (fixed if name is not None else heads).append(node.value)  # `_left_out(reason)`: the head of a reason, finished with its counts
        else:
            built.add(ast.dump(node))
    assert len(fixed) >= 33 and len(heads) == 3
    assert all(any(text.startswith(head + " (") for text in REASONS_FROM_EVIDENCE["f'{reason} ({detail})'"]) for head in heads)
    for text in fixed:
        shown, translated = wording.line(text, "tr")
        assert translated and MARK not in shown and shown != text, f"no Turkish for the reason {text!r}"
        assert wording.line(text, "en") == (wording.english(text), True)
    # Every place a reason is put together is known, and each reason it makes is translated.
    expected = {_canonical_source(source) for source in REASONS_FROM_EVIDENCE}
    assert built == expected, built ^ expected
    for source, reasons in REASONS_FROM_EVIDENCE.items():
        for text in reasons:
            shown, translated = wording.line(text, "tr", capital=True)
            assert translated and MARK not in shown and "(s)" not in shown, f"{source}: no Turkish for {text!r}"
            assert "(s)" not in wording.line(text, "en")[0]
    # A reason on a line of its own begins with a capital; a host name is not capitalised.
    assert wording.line("the URL Inspection request failed", "tr", capital=True)[0] == "URL Denetimi isteği başarısız oldu"
    assert wording.line("month names and date labels are read in English only", "tr", capital=True)[0].startswith("Ay adları")
    assert wording.line("made-up.example: TLS not checked", "tr", capital=True)[0] == "made-up.example: TLS kontrol edilmedi"
    assert REASONS_NOT_COVERED
    # The numbers are the engine's own.
    said = wording.line("this check ran on the 50 page(s) that were read; 536 more page(s) were found and not read (page cap of 50 reached). Its result says nothing about pages that were not read", "tr")[0]
    assert re.findall(r"\d+", said) == ["50", "536", "50"]


def test_a_coverage_gap_row_keeps_the_reports_words_and_adds_what_is_shown():
    check = {"check_id": "STR-9", "title": "Language and locale declaration", "status": "partial", "summary": "Language declarations are present and hreflang links are reciprocal.",
             "findings": [], "coverage": {"not_assessed": [{"part": "hreflang targets", "reason": "the target was not fetched (another origin, cap, or robots.txt) or failed", "count": 3},
                                                           {"part": "a made-up part", "reason": "a made-up reason nobody listed", "count": 1}]}}
    whole = {"check_id": "IDX-9", "title": "Google index status of key pages", "status": "not_assessed", "findings": [], "coverage": {"not_assessed": []},
             "summary": "No key pages are marked, and this check runs on key pages only."}
    report = {"checks": [check, whole], "answer_engine_panel": [], "gates": [], "crawl": {"pages": []}}
    english = summary.coverage_gaps(report)
    assert [(gap["part"], gap["part_shown"], gap["reason_shown"]) for gap in english] == [(gap["part"], gap["part"], gap["reason"]) for gap in english]
    strings.set_language("tr")
    rows = summary.coverage_gaps(report)
    assert [(gap["part"], gap["reason"]) for gap in rows] == [(gap["part"], gap["reason"]) for gap in english]  # the report's own words stay
    assert (rows[0]["part_shown"], rows[0]["untranslated"]) == ("Hreflang hedefleri", False) and rows[0]["reason_shown"].startswith("Hedef getirilmedi")
    assert rows[1]["part_shown"] == "A made-up part" + MARK and rows[1]["reason_shown"] == "a made-up reason nobody listed" + MARK and rows[1]["untranslated"]
    assert rows[2]["part_shown"] == "Önemli sayfaların Google dizin durumu" and rows[2]["reason_shown"] == "Önemli sayfa işaretlenmedi ve bu kontrol yalnızca önemli sayfalarda çalışır."
    row = summary.check_row(check)
    assert (row["title"], row["summary"]) == (check["title"], check["summary"]) and row["title_shown"] == "Dil ve yerel ayar beyanı" and not row["untranslated"]
    assert row["summary_shown"] == "Dil beyanları mevcut ve hreflang bağlantıları karşılıklı."
    gate = summary.gate_row({"check_id": "INT-2", "title": "Crawl completeness", "state": "incomplete", "summary": "Incomplete: stopped early (page_cap): page cap of 50 reached."})
    assert (gate["title_shown"], gate["state_label"], gate["summary_shown"]) == ("Taramanın tamlığı", "tamamlanmadı", "Tamamlanmadı: erken durdu (sayfa sınırı): 50 sayfalık sınıra ulaşıldı.")
    strings.set_language("en")
    gate = summary.gate_row({"check_id": "INT-4", "title": "Maya crawler identity and robots.txt compliance", "state": "compliant",
                             "summary": "Compliant: all 5 of Maya's own requests used one user agent, robots.txt was fetched before any other request to its origin, no request went to a disallowed URL, and 1 URL(s) were skipped per robots.txt."})
    assert gate["state_label"] == "compliant" and gate["summary_shown"].endswith("and 1 URL was skipped per robots.txt.") and "(s)" in gate["summary"]


# -- gates: the fragments their summaries and fixes are made of ----------------------------------------------------------------------

def test_every_gate_reason_and_fix_has_a_turkish_wording():
    tree = ast.parse((ENGINE / "checks" / "integrity.py").read_text(encoding="utf-8"))
    pieces = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in ("reasons", "problems", "probe_problems", "caveats") and node.args:
            pieces += sample(node.args[0])
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in ("how_to_fix", "fixes") for target in node.targets):
            values = node.value.values if isinstance(node.value, ast.Dict) else [node.value]
            pieces += [text for value in values if not isinstance(value, (ast.Call, ast.Constant)) or isinstance(getattr(value, "value", None), str) for text in sample(value)]
    pieces = [text for text in pieces if text.strip() not in ("", "3")]
    assert len(pieces) >= 20, pieces
    # A piece is a phrase inside "Incomplete: ...; ..." (a term) or a sentence of its own (a line).
    samples_with_a_label = {"the start URL was 3": "the start URL was blocked", "stopped early (3): 3": "stopped early (page_cap): page cap of 50 reached",
                            "3 of fetched pages were blocked or rate-limited, at or above the 3% threshold": "6/20 (30.0%) of fetched pages were blocked or rate-limited, at or above the 20% threshold"}
    for text in pieces:
        text = samples_with_a_label.get(text, text)
        said = wording.term(text, "tr") or wording.line(text, "tr")[0]
        assert said and MARK not in said and "(s)" not in said, f"no Turkish for the gate piece {text!r}"
    for text in ("No pages were fetched, so there is nothing to classify.", "Complete: every discovered URL was fetched or skipped (51 page fetches).",
                 "Raw HTML for every page, plus a rendered view (JavaScript executed) for 20 of 20 render slots. Not rendered: 7 template(s), 0 key page(s). 457 image, media and font "
                 "request(s) were not fetched while rendering: they are not needed to read a page's text, and the rendered views are not screenshots. Resources on other origins were "
                 "not loaded while rendering, so a site whose scripts live on a CDN may look less rendered than it is.",
                 "Compliant: all 994 of Maya's own requests used one user agent, robots.txt was fetched before any other request to its origin, no request went to a disallowed URL, "
                 "and 0 URL(s) were skipped per robots.txt. No separate Maya information page was configured; the site audit continued.",
                 "Maya's crawler (user agent \"Maya-Audit/0.2\") was blocked or rate-limited on 1 page(s). If you own this site, allowlist that user agent in your WAF, bot-protection, "
                 "and rate-limiting rules, then re-run the audit. Content checks do not run on those pages, so no finding describes them."):
        shown, translated = wording.line(text, "tr")
        assert translated and MARK not in shown, text
    assert all(strings.has(f"result.gate.{state}", "tr") and strings.t(f"result.gate.{state}", "en") == state
               for state in ("ok", "degraded", "not_assessed", "complete", "incomplete", "disclosure", "compliant", "violation"))


# -- the Firecrawl section ------------------------------------------------------------------------------------------------------------

def firecrawl_section(**changes):
    base = {"used": True, "purpose": fc_reader.MAIN_PURPOSE, "proxy": "basic", "owner_approved_bypass": False, "pages_read": 3, "page_cap": 50, "skipped_by_robots": 1,
            "checks_from_firecrawl": ["STR-1", "IDX-8", "TSEO-1"], "notice": fc_reader.MAIN_NOTICE, "zero_data_retention": {"status": "applied"},
            "credits": {"used_or_reserved": 10, "estimated_max": 106}, "usd": {"used_or_reserved": None, "note": "no dollar price per credit is configured, so only credits are shown"},
            "requests_sent": 5, "errors": [], "robots": {}}
    return {**base, **changes}


FIRECRAWL_SECTIONS = {
    "the page reader of an audit": firecrawl_section(sitemap={"documents": [{"outcome": "read"}, {"outcome": "failed"}], "addresses_found": 14, "note": None},
                                                     coverage={"causes": {"error_status": 1, "reader_challenged": 2, "empty_document": 1}}),
    "a blocked site read afterwards, with a price": firecrawl_section(purpose="content reader for a blocked site", notice=fc_reader.AI_NOTICE, proxy="enhanced", owner_approved_bypass=True,
                                                                      usd={"used_or_reserved": 0.0106, "note": None}, zero_data_retention={"status": "waived by the user for this audit"},
                                                                      stopped_because="the last 3 pages asked for came back unreadable, so no more were requested",
                                                                      sitemap={"documents": [{"outcome": "read"}], "addresses_found": 3, "note": "2 more sitemap document(s) were not asked for (at most 5 per audit through a reader)"},
                                                                      robots={"source": "Maya's own crawler", "reason": "robots.txt parsed"}),
    "not used": firecrawl_section(used=False, reason=None, notice=None),
    "not used: nothing allowed": firecrawl_section(used=False, reason="there was no page robots.txt allows", notice=None, zero_data_retention={"status": "not available"},
                                                   needs_decision="zero_data_retention"),
    "also blocked": firecrawl_section(used=False, reason="Firecrawl basic was also blocked: 3 page(s) tried, 2 came back as a challenge or block page and 1 came back as an error or no document",
                                      notice=None, pages=[{"outcome": "blocked"}, {"outcome": "blocked"}, {"outcome": "error"}], robots={"read": True}),
    "a provider error": firecrawl_section(used=False, reason="Firecrawl could not load the page as a website; see provider errors below", notice=None, errors=[
        {"meaning": "Firecrawl could not load the page as a website", "url": "https://made-up.example/", "http_status": 500, "message": "All scraping engines failed (made-up provider text)",
         "engines_tried": ["fire-engine", "fetch"], "note": "No website document was returned. This alone does not prove a bot-protection block."}]),
}
# Knowingly not covered in the Firecrawl section: shown in English with the mark.
FIRECRAWL_NOT_COVERED = {
    "Firecrawl was not started: <why>": "the reason is the spending guard's or the client's own message (budget, key, network): many sources, shown as written",
    "Stopped early: <a client error>": "when the reader stops on an exception, the reason is that exception's text; the two counted reasons (first/last N pages unreadable) are translated",
    "Not used: <a zero-data-retention refusal>": "the provider's refusal as the client reports it",
}


def test_every_line_of_the_firecrawl_section_has_a_turkish_wording():
    seen = set()
    for name, section in FIRECRAWL_SECTIONS.items():
        lines = fc_panel.summary_lines(section)
        assert lines, name
        for text in lines:
            shown, translated = wording.line(text, "tr")
            assert translated and MARK not in shown and "(s)" not in shown and shown != text, f"{name}: no Turkish for {text!r}"
            assert "(s)" not in wording.line(text, "en")[0]
            seen.add(text.split(":")[0].split(" (")[0])
    assert {"Used as", "Pages read through Firecrawl", "Sitemap through Firecrawl", "Asked for and not read", "Checks that rest on Firecrawl's reading", "Zero data retention", "Cost",
            "Not used", "Stopped early", "Provider error", "Engines tried", "Robots policy"} <= seen
    strings.set_language("tr")
    from maya_audit_web import fc
    view = fc.view(FIRECRAWL_SECTIONS["the page reader of an audit"], {})
    assert view["lines"] == fc_panel.summary_lines(FIRECRAWL_SECTIONS["the page reader of an audit"]) and view["notice"] == fc_reader.MAIN_NOTICE  # the report's own words
    assert view["untranslated"] == 0 and len(view["lines_shown"]) == len(view["lines"]) and view["notice_shown"].startswith("Sayfa içeriği, üçüncü taraf bir sayfa okuyucu olan Firecrawl")
    assert "Firecrawl üzerinden okunan sayfa: 3 (sınır 50); 1 tanesi robots.txt yasakladığı için dışarıda bırakıldı." in view["lines_shown"]
    assert "İstendi ve okunmadı: boş belge: 1, hata durumu: 1, sayfa okuyucu da doğrulamaya yönlendirildi: 2." in view["lines_shown"]
    odd = fc.view(firecrawl_section(used=False, reason="Firecrawl was not started: a made-up guard said no", notice=None), {})
    assert odd["untranslated"] == 1 and odd["lines_shown"][0] == "Not used: Firecrawl was not started: a made-up guard said no." + MARK
    assert FIRECRAWL_NOT_COVERED


# -- DataForSEO: titles, sentences, figure and column names ------------------------------------------------------------------------------

DFS_SENTENCES = [  # (pieces of the engine's source, a sentence as the engine writes it)
    (("referring domain(s) and", "backlink(s) in DataForSEO's index; DataForSEO rank"), "96 referring domain(s) and 1,840 backlink(s) in DataForSEO's index; DataForSEO rank 212."),
    (("look like spam (spam score ≥", "highest-ranked referring domains listed ("),
     "96 referring domain(s) and 1,840 backlink(s) in DataForSEO's index; DataForSEO rank 212. 4 of 40 highest-ranked referring domains listed (96 in the index) look like spam (spam score ≥ 50)."),
    (('"referring domains"',), "3 referring domain(s) and 12 backlink(s) in DataForSEO's index; DataForSEO rank 7. 0 of 3 referring domains look like spam (spam score ≥ 50)."),
    (("How many referring domains look like spam was not assessed",),
     "3 referring domain(s) and 12 backlink(s) in DataForSEO's index; DataForSEO rank not reported. How many referring domains look like spam was not assessed: the referring-domain list was not obtained."),
    (("referring domain(s) listed, highest DataForSEO rank first",), "40 referring domain(s) listed, highest DataForSEO rank first, of 96 in the index. 4 of the 40 listed look like spam (spam score ≥ 50)."),
    (("keyword(s) ranked in Google's top 100", "estimated organic visit(s) a month", ", by DataForSEO's index."),
     "164 keyword(s) ranked in Google's top 100 and about 1,840.5 estimated organic visit(s) a month, by DataForSEO's index."),
    (("Not reported by the provider:", "keywords in position {band}"), "12 keyword(s) ranked in Google's top 100, by DataForSEO's index. Not reported by the provider: estimated organic visits, keywords in position 2–3."),
    (("Context review:", "no classification of provider totals"),
     "Context review: 3 uncertain and 1 related-organization searches in this sample; no classification of provider totals."),
    (("DataForSEO returned an empty sample for this domain in this market",),
     "DataForSEO returned an empty sample for this domain in this market: no ranking data in its index. That is the provider's coverage, not a measurement that the site ranks for nothing."),
    (("keyword(s) listed of", "of those listed are in the top 10", "look unrelated (shown separately)"),
     "5 keyword(s) listed of 164 the domain ranks for, most searched first; 2 of those listed are in the top 10. Of the 5 listed, 2 name the brand, 0 are about what the site offers and 3 "
     "look unrelated (shown separately)."),
    (("Also listed: the bare word", "so the listed keyword sample may include"),
     "5 keyword(s) listed of 164 the domain ranks for, most searched first; 2 of those listed are in the top 10. Of the 5 listed, 2 name the brand, 1 are about what the site offers and 1 "
     "look unrelated (shown separately). Also listed: the bare word “kettle”, which is ambiguous and not counted. “Kettle” is also an ordinary word, so the listed keyword sample may include "
     "searches that only share the word."),
    (("keyword(s) rank in positions", "These are the nearest to more visits"),
     "58 keyword(s) rank in positions 4 to 20; the 3 most searched are listed (4,580 searches a month between them). These are the nearest to more visits: improve the ranking page for each."),
    (("domain(s) listed that rank for the same keywords", "are left out."), "10 domain(s) listed that rank for the same keywords, of 37 found. The very largest sites (marketplaces, encyclopaedias) are left out."),
    (("other domain(s) listed that rank for the same keywords", "Possibly generic-word overlap"),
     "2 other domain(s) listed that rank for the same keywords, of 37 found. The very largest sites (marketplaces, encyclopaedias) and the audited domain itself are left out. Possibly "
     "generic-word overlap: shared queries alone do not establish business competition. Review each domain and its overlapping queries; the keyword sample does not classify all provider totals."),
    (("AI answer(s) in DataForSEO's sample match this domain", "the questions are asked about"),
     "38 AI answer(s) in DataForSEO's sample match this domain: the domain is cited as a source of an AI answer, named in its text, or listed among the search results that supported it; the "
     "questions are asked about 12,400 time(s) a month. This is wider than \"the brand is mentioned in the answer\", and it is a sample of the platform's answers, not every answer."),
    (("Measured zero: none of the AI answers in DataForSEO's sample",),
     "Measured zero: none of the AI answers in DataForSEO's sample for this platform and market matched this domain (the domain is cited as a source of an AI answer, named in its text, or "
     "listed among the search results that supported it). A sample of answers, not every answer, so this is not proof of absence."),
    (("DataForSEO returned an empty sample: no AI answer in its collection",),
     "DataForSEO returned an empty sample: no AI answer in its collection for this platform and market matched this domain (the domain is cited as a source of an AI answer, named in its "
     "text, or listed among the search results that supported it). A sample of answers, not every answer, so this is not proof of absence."),
    (("Lab test on a simulated phone: performance", "past Google's \\\"good\\\" threshold:", "within the threshold:", "One lab run, not what real visitors experienced."),
     "Lab test on a simulated phone: performance 62 of 100; past Google's \"good\" threshold: Largest Contentful Paint, Total Blocking Time; within the threshold: Cumulative Layout Shift. "
     "One lab run, not what real visitors experienced."),
    (("the three main lab metrics are within Google's \\\"good\\\" thresholds",),
     "Lab test on a simulated phone: performance 97 of 100; the three main lab metrics are within Google's \"good\" thresholds. One lab run, not what real visitors experienced."),
    (("no performance score was reported", "not measured in this answer, so not judged:"),
     "Lab test on a simulated phone: no performance score was reported; not measured in this answer, so not judged: Largest Contentful Paint, Cumulative Layout Shift. One lab run, not "
     "what real visitors experienced."),
    (("Profile found:", "NOT confirmed: the profile was found by name only", "Check the address and website by hand"),
     "Profile found: Demo Cafe (made-up), rated 4.4 from 212 review(s). Identity NOT confirmed: the profile was found by name only, and its website (https://demo-cafe.example/) is not the "
     "audited domain (demo-shop.example). Check the address and website by hand before changing anything: another business may share the name."),
    (("confirmed: the profile's website is the audited domain", "Missing on the profile:"),
     "Profile found: Made-Up Kettles, rated 4.8 from 31 review(s). Identity confirmed: the profile's website is the audited domain. Missing on the profile: phone, claimed by the owner."),
    (("Nothing is missing among phone, website, category and owner claim.", "and it lists no website to compare"),
     "Profile found: Made-Up Kettles, rated not reported from not reported review(s). Identity NOT confirmed: the profile was found by name only, and it lists no website to compare. "
     "Check the address and website by hand before changing anything: another business may share the name."),
    (("DataForSEO returned no Google Business Profile under this name",),
     "DataForSEO returned no Google Business Profile under this name in this country. Check the name, or the business may not have a profile."),
    (("is not a public domain name, so a search index has nothing to look up",), "'demo-shop.localhost' is not a public domain name, so a search index has nothing to look up. No request was sent."),
    (("Context is insufficient or mixed.",),
     "Context is insufficient or mixed. These rows are not counted as confirmed brand searches or opportunities."),
    # The account's balance (DECISIONS 180): a refusal for no credit, the requests left out after it, a run started without paid data.
    (("the DataForSEO account balance ran out earlier in this audit", "No request was sent."),
     "not requested: the DataForSEO account balance ran out earlier in this audit. No request was sent."),
    (("DataForSEO refused a request because the account has no credit, so the remaining", "were not sent. Nothing was charged for them."),
     "DataForSEO refused a request because the account has no credit, so the remaining 6 were not sent. Nothing was charged for them."),
    (("Search data was not requested:", "the DataForSEO balance was unknown when the audit started", "when the audit started"),
     "Search data was not requested: the DataForSEO balance was $0.00 when the audit started."),
    (("the DataForSEO balance was unknown when the audit started",), "Search data was not requested: the DataForSEO balance was unknown when the audit started."),
    (("not requested: ", ". No request was sent."), "not requested: the DataForSEO balance was $0.00 when the audit started. No request was sent."),
    (("not requested: ",), "not requested: the DataForSEO balance was unknown when the audit started. No request was sent."),
    # One audit's own spending limit (DECISIONS 192): the requests left out once it is reached, and the panel's note.
    (("this audit reached its $", "DataForSEO limit"), "not requested: this audit reached its $5.00 DataForSEO limit. No request was sent."),
    (("This audit reached its $", "request(s) were not sent:", "Nothing was charged for them."),
     "This audit reached its $5.00 DataForSEO limit after DFS-6, so the remaining 2 request(s) were not sent: DFS-7, DFS-8. Nothing was charged for them."),
    (("before its first request",),
     "This audit reached its $5.00 DataForSEO limit before its first request, so the remaining 3 request(s) were not sent: DFS-1, DFS-2, DFS-3. Nothing was charged for them."),
    (("These share a word with the site or its name",),
     "These share a word with the site or its name but are not about what the site offers, by word matching against the brand name and the site's own titles, headings and descriptions. "
     "Check before discarding."),
]
# Knowingly not covered in the data panels. A panel that could not run is worded by this layer already (`paid.refusal`).
DFS_NOT_COVERED = {
    "a response the engine could not read (\"the <what> answer holds no ...\")": "an error about the provider's response format, said in the summary of a check that is 'not assessed': "
                                                                               "the web layer replaces that summary with its own refusal sentence (`paid.refusal`, translated)",
    "market_warning (the plan's country is not one DataForSEO can be asked about)": "shown on the plan card before a run, not in the report; the plan card has its own Turkish sentence",
    "figures the provider names itself (Lighthouse displayValue, a profile's category)": "third-party cells, shown as they came",
}


def dfs_names():
    """Every figure name and column name the data panels can show, read from the engine's source: the keys of `metrics`
    dicts, the `columns` lists, the side tables' titles and the lab metrics' names."""
    names = set()
    for path in (Path(insights.__file__), Path(dfs_panel.__file__)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "columns" and isinstance(value, ast.List):
                        names.update(item.value for item in value.elts if isinstance(item, ast.Constant))
                    if isinstance(key, ast.Constant) and key.value == "title" and isinstance(value, ast.Constant):
                        names.add(value.value)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(target, ast.Name) and target.id == "metrics":
                    for key in node.value.keys:
                        names.update(sample(key) if key is not None else [])
    names.update(["Relevance", *(label for _, label in insights.LAB_METRICS), "Performance score (0–100)", "Accessibility score (0–100)",
                  "Best practices score (0–100)", "SEO score (0–100)", "Keywords in position 2–3", "Keywords in position 21–100"])
    return {name for name in names if isinstance(name, str) and name.strip() and name != "3"}


def test_every_data_panel_title_sentence_and_column_name_has_a_turkish_wording():
    titles = set()
    for country, brand in (("US", "Made-Up Kettles"), ("TR", "Uydurma Çaydanlık"), ("Germany", ""), (None, "Made-Up"), ("Atlantis", "Made-Up")):
        titles.update(call.title for call in insights.audit_plan("https://made-up.example/", country=country, brand=brand, key_pages=["https://made-up.example/pricing"], local_business=True))
    titles.update(["Backlink profile summary", f"Top {dfs_panel.REFERRING_DOMAINS_LIMIT} referring domains"])
    assert len(titles) >= 25 and any("default market" in title for title in titles) and any("Turkey, tr" in title for title in titles)
    for title in sorted(titles):
        shown, translated = wording.label(title, "tr")
        assert translated and MARK not in shown and shown != title, f"no Turkish for the panel title {title!r}"
    assert wording.label("Ranked keywords: the 100 with the most searches (Turkey, tr)", "tr")[0] == "Sıralanan anahtar kelimeler: en çok aranan 100 tanesi (Türkiye, tr)"
    assert wording.label("Lighthouse lab test (mobile): https://made-up.example/pricing", "tr")[0].endswith(": https://made-up.example/pricing")
    assert "“Uydurma Çaydanlık”" in wording.label("Google Business Profile for “Uydurma Çaydanlık” (Turkey)", "tr")[0]
    names = dfs_names()
    assert len(names) >= 30 and {"Keyword", "Searches a month", "Their average position", "Claimed by the owner", "Largest Contentful Paint", "Keywords in position 2–3"} <= names
    for name in sorted(names):
        shown, translated = wording.label(name, "tr")
        assert translated and MARK not in shown, f"no Turkish for the figure or column name {name!r}"
    sources = Path(insights.__file__).read_text(encoding="utf-8") + Path(dfs_panel.__file__).read_text(encoding="utf-8")
    for pieces, text in DFS_SENTENCES:
        for piece in pieces:
            assert piece in sources, f"the engine's source no longer holds {piece!r}"
        shown, translated = wording.line(text, "tr")
        assert translated and MARK not in shown and "(s)" not in shown and shown != text, f"no Turkish for {text!r}"
        assert "(s)" not in wording.line(text, "en")[0]
    # The provider's own values come through unchanged.
    said = wording.line(DFS_SENTENCES[20][1], "tr")[0]
    assert "Demo Cafe (made-up)" in said and "https://demo-cafe.example/" in said and "demo-shop.example" in said and "4.4" in said and "212" in said
    # What a panel shows: names in the reader's language, every provider cell as it came.
    data = {"metrics": {"Name": "Demo Cafe (made-up)", "Claimed by the owner": "yes", "Rating": 4.4},
            "table": {"columns": ["Keyword", "Searches a month", "Position", "Ranking page", "Relevance"], "rows": [["made-up kettle reviews", 880, 7, "https://made-up.example/k", "branded"]]},
            "unrelated": {"title": "Unrelated searches (not counted as opportunities)", "columns": ["Keyword", "Searches a month"], "rows": [["kettle bell", 9000]], "note": DFS_SENTENCES[-1][1]}}
    strings.set_language("tr")
    shown = paid.shown_data(data)
    assert shown["labels"]["Keyword"] == "Anahtar kelime" and shown["labels"]["branded"] == "marka" and shown["labels"]["yes"] == "evet" and shown["labels"]["Name"] == "Ad"
    assert "made-up kettle reviews" not in shown["labels"] and "Demo Cafe (made-up)" not in shown["labels"] and shown["notes"]["unrelated"].startswith("Bunlar siteyle")
    assert shown["labels"]["Unrelated searches (not counted as opportunities)"] == "İlgisiz aramalar (fırsat olarak sayılmaz)" and set(shown["word_columns"]) == {"Relevance", "Claimed by the owner"}
    assert DFS_NOT_COVERED


# -- Core Web Vitals, archived copies, the allow-list, ownership ------------------------------------------------------------------------

OTHER_NOT_COVERED = {
    "an archive's own error for one address (\"<url>: <error>\")": "the archive client's exception text for one capture; the fixed archive answers are translated",
    "Core Web Vitals: \"<why> before Google was asked\" with a reason this layer has no sentence for": "the run clock's reason; shown in English with the mark",
    "metric names (Largest Contentful Paint, Interaction to Next Paint, Cumulative Layout Shift, Speed Index, ...)": "Google's own names for its metrics: kept as they are, as SEO practice has them",
}


def test_core_web_vitals_archives_the_allow_list_and_ownership_are_worded_in_turkish():
    # Core Web Vitals: every fixed sentence in the module, and an assessed section worded from its own figures.
    fixed = [node.value for node in ast.walk(ast.parse(Path(crux.__file__).read_text(encoding="utf-8")))
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(("Core Web Vitals not available", "Real visitors on phones: all"))
             and node.value.rstrip().endswith((".", ")")) and not node.value.endswith(" (")]
    assert len(fixed) >= 5
    for text in [*fixed, crux.SOURCE, "Core Web Vitals not available: Google's Chrome UX Report could not be reached (ConnectError).",
                 "Core Web Vitals not available: Google's Chrome UX Report answered HTTP 403 (API key not valid). Check the API key and that the Chrome UX Report API is enabled for it.",
                 "Core Web Vitals not available: Google's Chrome UX Report answered HTTP 500. Check the API key and that the Chrome UX Report API is enabled for it.",
                 "Real visitors on phones: Largest Contentful Paint (LCP) 2.9 s (needs improvement); Cumulative Layout Shift (CLS) 0.31 (poor).",
                 "Real visitors on phones: the metrics published are good, but not all three are published."]:
        said = wording.line(text, "tr") if text != crux.SOURCE else wording.label(text, "tr")
        assert said[1] and MARK not in said[0] and said[0] != text, text
    section = {"source": crux.SOURCE, "status": "assessed", "data_until": "2026-10-01", "summary": "Real visitors on phones: Largest Contentful Paint (LCP) 2.9 s (needs improvement).",
               "metrics": [{"metric": "largest_contentful_paint", "label": "Largest Contentful Paint (LCP)", "shown": "2.9 s", "rating": "needs improvement"},
                           {"metric": "time_to_first_byte", "label": "Time to First Byte", "shown": "410 ms", "rating": None}]}
    assert summary.speed_view(section)["summary_shown"] == section["summary"] and summary.speed_view(section)["metrics"][0]["rating_shown"] == "needs improvement"
    strings.set_language("tr")
    view = summary.speed_view(section)
    assert view["summary"] == section["summary"] and view["summary_shown"] == "Telefonlardaki gerçek ziyaretçiler: Largest Contentful Paint (LCP) 2.9 s (iyileştirilmeli)."
    assert view["metrics"][0]["rating_shown"] == "iyileştirilmeli" and view["metrics"][1]["rating_shown"] == "" and view["source_shown"].startswith("Chrome UX Report (Google): telefonlardaki")
    assert summary.speed_view(crux.unavailable())["summary_shown"] == "Core Web Vitals kullanılamıyor (API anahtarı yok)"
    # Archived copies.
    for text in ("Historical content only; live access findings are unchanged.", "No available capture: http://made-up.example/", "No Common Crawl index is available",
                 "No indexed capture: http://made-up.example/a", "Archive returned HTTP 429; back off and retry later. Retry-After: 30", "Archive returned HTTP 503; no redirect or live fallback followed",
                 "Archive request failed (ConnectError); retry later", "Coverage: newest Common Crawl collection only (CC-MAIN-2026-40); older collections were not searched.",
                 "Source: Wayback Machine; " + archives.NOTICE.format(date="2026-09-30"), "Archive collection stopped", "Archive returned invalid JSON",
                 "Source: Common Crawl; archived content only. All 3 indexable page(s) have distinct, non-generic titles (English placeholder list)."):
        shown, translated = wording.line(text, "tr")
        assert translated and MARK not in shown and shown != text, text
    shown = summary.archives_view({"notice": "Historical content only; live access findings are unchanged.", "sources": [
        {"id": "wayback", "name": "Wayback Machine", "pages_read": 1, "status": "read", "notes": ["No available capture: http://made-up.example/b"],
         "pages": [{"url": "http://made-up.example/", "title": "Made-Up Kettles", "label": "Source: Wayback Machine; " + archives.NOTICE.format(date="2026-09-30"), "archive_url": "x"}],
         "findings": [{"check_id": "STR-10", "severity": "S4", "title": "1 page(s) have no meta description", "how_to_fix": "Add meta description."}]}]})
    source = shown["sources"][0]
    assert shown["notice_shown"] == "Yalnızca geçmiş içerik; canlı erişim bulguları değişmedi." and source["notes_shown"] == ["Kullanılabilir kopya yok: http://made-up.example/b"]
    assert source["pages"][0]["label_shown"].startswith("Kaynak: Wayback Machine; arşivlenmiş") and source["pages"][0]["title"] == "Made-Up Kettles"
    assert source["findings"][0]["title_shown"] == "1 sayfada meta açıklaması yok" and source["findings"][0]["title"] == "1 page(s) have no meta description"
    assert wording.note("Source: Common Crawl; " + archives.NOTICE.format(date="2026-09-30"), "tr")[1]
    # The allow-list steps for the site's owner: every firewall the engine has steps for.
    steps = 0
    for name in ("Cloudflare", "Akamai", None, "A made-up firewall"):
        for block in allowlist.instructions("Maya-Audit", "Maya-Audit/0.2 (+https://made-up.example/bot)", name):
            assert wording.label(block["title"], "tr")[1], block["title"]
            for step in block["steps"]:
                shown, translated = wording.line(step, "tr")
                steps += 1
                assert translated and MARK not in shown and shown != step, step
                assert "Maya-Audit" in shown or "Maya-Audit" not in step  # the user agent is put back unchanged
    assert steps >= 12
    assert '(http.user_agent contains "Maya-Audit")' in wording.line(allowlist.instructions("Maya-Audit", "Maya-Audit/0.2", "Cloudflare")[0]["steps"][1], "tr")[0]
    # Ownership: both outcomes, every reason the engine gives, and the steps.
    token = ownership.token_for("made-up.example", "made-up-secret")
    for step in ownership.instructions("made-up.example", token):
        shown, translated = wording.line(step, "tr")
        assert translated and MARK not in shown and (token in shown or token not in step), step
    for found in ({"verified": True, "method": "meta_tag"}, {"verified": True, "method": "dns_txt"}, {"verified": False, "reason": "no site verification token configured"},
                  {"verified": False, "reason": "homepage has no verification meta tag matching the configured token; the domain has no DNS TXT record matching the configured token"},
                  {"verified": False, "reason": "homepage could not be read, so the meta tag could not be checked; the domain has no DNS TXT record matching the configured token"},
                  {"verified": False}):
        section = ownership.section(found, "made-up.example", token, "2026-10-11T08:00:00+00:00")
        view = summary.ownership_view(section)
        assert view["summary"] == section["summary"] and MARK not in view["summary_shown"] and "made-up.example" in view["summary_shown"] and len(view["instructions_shown"]) == 4, view["summary_shown"]
    assert OTHER_NOT_COVERED


# -- the pages a person sees -----------------------------------------------------------------------------------------------------------

# Words that only an English sentence holds. ("not" is Turkish for "note", "on" for "ten", "in" and "at" are Turkish words.)
STOP_WORDS = re.compile(r"\b(the|of|is|are|was|were|with|for|and|that|this|page|pages|from|has|have|by|or|to|could|only|every|which|than|when|its|their|been|did|does|"
                        r"not checked|not assessed|not read|was not|were not)\b", re.IGNORECASE)
# Text in the Turkish page that is knowingly not Turkish: (what it is, a pattern for the whole text run).
ALLOWED_ENGLISH = (
    ("the demo site's own name on the cover and in the page title", re.compile(r"(Maya Audit: )?demo-shop\.localhost")),
    ("a firewall expression inside an allow-list step (code)", re.compile(r".*\(ip\.src eq AUDITOR_IP\).*")),
)
# "(s)" that is not a count: an address form the engine names, and the example of a link coded as a control.
ALLOWED_S = ('(href="#")', "http(s)://")


def text_runs(html):
    """The text of a printed report as a list of runs, without what is not a sentence of the report: styles, code and
    examples (`<code>`, `<pre>`), addresses (class "url") and third-party or site values (class "tp": a provider's
    table cells, a page's own title and heading)."""
    html = re.sub(r"<style>.*?</style>", " ", html, flags=re.DOTALL)
    html = re.sub(r"<(code|pre)\b[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    html = re.sub(r'<(li|td|span|p) class="[^"]*\b(?:url|tp)\b[^"]*">.*?</\1>', " ", html, flags=re.DOTALL)
    return [unescape(run).strip() for run in re.split(r"<[^>]+>", html) if run.strip()]


def without_values(run):
    """A text run without the values inside it that are shown unchanged: quoted site text, addresses, a user agent."""
    run = re.sub(r"“[^”]*”|'[^']*'|\"[^\"]*\"", " ", run)
    run = re.sub(r"https?://\S+|\b[\w.-]+\.(?:localhost|example|com|org)\b\S*|/v3/\S+|Maya-Audit/\S+( \(\+\S+\))?", " ", run)
    return run


def english_runs(html):
    """Text runs of a Turkish page that still read as English: two English stop words or more in one run."""
    found = []
    for run in text_runs(html):
        if any(pattern.fullmatch(run) for _, pattern in ALLOWED_ENGLISH):
            continue
        hits = STOP_WORDS.findall(without_values(run))
        if len(hits) >= 2:
            found.append(run)
    return found


def printed(client, audit, language):
    assert client.put(f"{API}/session/language", json={"language": language}).status_code == 200
    return client.get(f"{API}/audits/{audit['id']}/print?full=true&lang={language}").text


def displayed(client, audit):
    """Every sentence the results card is given for one audit: the text of every `*_shown` field, at any depth."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("_shown") and key != "data_shown":
                    out.extend(value if isinstance(value, list) else [value])
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(get(client, audit, "/summary"))
    walk(get(client, audit, "/findings", limit=100))
    return [text for text in out if isinstance(text, str)]


def check_both_languages(client, audit):
    saved = client.get(f"{API}/audits/{audit['id']}/result").content
    markdown = client.get(f"{API}/audits/{audit['id']}/downloads/markdown?draft=true").content
    english_page = printed(client, audit, "en")
    english_card = get(client, audit, "/summary")
    # English: no "(s)" in what the web layer displays, in the page or on the card.
    for run in text_runs(english_page):
        left = run
        for allowed in ALLOWED_S:
            left = left.replace(allowed, "")
        assert "(s)" not in left and "(es)" not in left and "(ies)" not in left, f"English page still says (s): {run!r}"
    for text in displayed(client, audit):
        for allowed in ALLOWED_S:
            text = text.replace(allowed, "")
        assert "(s)" not in text, f"English card still says (s): {text!r}"
    assert MARK not in english_page and "(İngilizce)" not in json.dumps(english_card, ensure_ascii=False)
    # Turkish: no mark, no English sentence.
    page = printed(client, audit, "tr")
    assert page.startswith('<!doctype html><html lang="tr">')
    assert MARK.strip() not in page, [run for run in text_runs(page) if MARK.strip() in run]
    assert english_runs(page) == []
    card = get(client, audit, "/summary")
    marked = [text for text in displayed(client, audit) if MARK.strip() in text]
    assert marked == [], marked
    for run in text_runs(page):
        assert "(s)" not in run.replace("http(s)://", ""), run
    # The saved report and its downloads are the engine's English, byte for byte, in both languages.
    assert client.get(f"{API}/audits/{audit['id']}/result").content == saved and client.get(f"{API}/audits/{audit['id']}/downloads/json?draft=true").content == saved
    # A site nothing could read is a draft (DECISIONS 287): the banner is in the person's language, the report
    # under it is the engine's English, byte for byte.
    turkish = client.get(f"{API}/audits/{audit['id']}/downloads/markdown?draft=true").content
    assert turkish.startswith("> **TASLAK:".encode()) == markdown.startswith(b"> **DRAFT:")
    unbanner = lambda md: md.split(b"\n\n", 1)[1] if md.startswith(b"> **") else md  # noqa: E731
    assert unbanner(turkish) == unbanner(markdown)
    # Every row keeps the report's own words beside what is shown.
    report = json.loads(saved)
    by_id = {check["check_id"]: check for check in report["checks"] + report.get("answer_engine_panel", [])}
    rows = [row for area in card["areas"] for row in area["checks"]] + card["answers"]["checks"]
    assert rows and all(row["title"] == by_id[row["check_id"]]["title"] and row["summary"] == by_id[row["check_id"]]["summary"] for row in rows)
    assert all(row["title_shown"] != row["title"] or row["title"].startswith("robots.txt") for row in rows) and not any(row["untranslated"] for row in rows)
    gates = {gate["check_id"]: gate for gate in report["gates"]}
    assert all(row["title"] == gates[row["check_id"]]["title"] and row["summary"] == gates[row["check_id"]]["summary"] and row["state"] == gates[row["check_id"]]["state"]
               and row["summary_shown"] != row["summary"] and not row["untranslated"] for row in card["gates"])
    own = lambda view: [(gap["part"], gap["reason"]) for gap in view["coverage"]["gaps"] if not gap.get("blocked")]  # noqa: E731 (the block's own row is worded by this layer)
    assert own(card) == own(english_card) and all(gap["part_shown"] and gap["reason_shown"] for gap in card["coverage"]["gaps"])
    assert not any(gap["untranslated"] for gap in card["coverage"]["gaps"])
    return page, card, english_page, english_card


def test_the_turkish_report_of_a_shop_with_search_data_and_backlinks_has_no_english_sentence(web):
    client = web()
    engine = client.app.state.runner.engine
    engine.crux_key, engine.crux_transport = (lambda: "made-up-google-key"), demo.CRUX_TRANSPORT
    audit = start(client, confirm(client, plan(client, search_data=True, market_default_accepted=True, backlinks=True, local_business=True, key_pages=["/about"])))
    assert audit["state"] == "finished"
    page, card, english_page, english_card = check_both_languages(client, audit)
    # The data panels: names and sentences in Turkish, the provider's cells as they came.
    panels = {check["check_id"]: check for check in card["backlinks"]["checks"]}
    assert len(panels) >= 9 and not any(check["untranslated"] for check in panels.values())
    assert panels["DFS-5"]["title"].startswith("Quick wins: keywords ranked 4 to 20") and panels["DFS-5"]["title_shown"].startswith("Hızlı kazanımlar: 4–20. sıralardaki anahtar kelimeler")
    assert "rated 4.4 from 212 review(s)" in panels["DFS-12"]["summary"] and "212 yorumdan 4.4 puan" in panels["DFS-12"]["summary_shown"]
    assert "<th>Anahtar kelime</th><th>Aylık arama</th><th>Sıra</th><th>Sıralanan sayfa</th><th>İlgililik</th>" in page and "made-up kettle reviews" in page
    assert "<th>Keyword</th>" in english_page and "Quick wins: keywords ranked 4 to 20" in english_page and "rated 4.4 from 212 reviews" in english_page
    assert {check["check_id"]: check["summary"] for check in english_card["backlinks"]["checks"]} == {check_id: check["summary"] for check_id, check in panels.items()}
    # Core Web Vitals and "What else we checked".
    assert card["crux"]["summary_shown"] == "Telefonlardaki gerçek ziyaretçiler: Largest Contentful Paint (LCP) 2.9 s (iyileştirilmeli)." and card["crux"]["summary"].startswith("Real visitors on phones")
    passed = [check for area in card["practical"].get("passed", []) for check in area["checks"]] or [row for area in card["areas"] for row in area["checks"] if row["status"] == "pass"]
    assert passed and all(MARK not in check["summary_shown"] for check in passed)
    assert "ACC-7 Yapay zekâ botlarına karşı Crawl-delay ve hız sınırı tutumu." in page and "No Crawl-delay of 60s or more applies to AI bots." not in page
    assert "INT-2 Taramanın tamlığı: tamamlanmadı." in page and "sayfa sınırı: 50 sayfalık sınıra ulaşıldı" in page
    assert card["method"]["stop_detail"] == "page cap of 50 reached" and card["method"]["stop_shown"] == "sayfa sınırı: 50 sayfalık sınıra ulaşıldı"
    assert english_card["method"]["stop_shown"] == "page_cap: page cap of 50 reached" and "INT-2 Crawl completeness: incomplete." in english_page


def test_the_turkish_report_of_an_audit_read_through_the_reader_has_no_english_sentence(web, tmp_path):
    client = web(site=Site(respond=cloudflare), firecrawl=services(tmp_path, Firecrawl(PAGES)))
    audit = start(client, plan(client))
    assert audit["outcome"]["code"] == "COMPLETED" and audit["outcome"]["reason"].startswith("We read 3 page(s) through Firecrawl")
    page, card, english_page, english_card = check_both_languages(client, audit)
    reader = card["firecrawl"]
    assert reader["used"] and reader["untranslated"] == 0 and reader["lines"] == english_card["firecrawl"]["lines"] and reader["lines_shown"] != reader["lines"]
    assert "Kullanım amacı: ana sayfa okuyucu. Proxy: basic." in page and "Used as: main page reader. Proxy: basic." in english_page
    assert "Cost: 10 credits spent or reserved, of at most 106; 5 requests sent." in english_page
    # A state the report names in one English word is worded too ("applied"), in the section and in the cost line.
    assert "Sıfır veri saklama: uygulandı." in page and "sıfır veri saklama: uygulandı" in page and ": applied" not in page
    assert card["spend"]["firecrawl"]["zero_data_retention"] == "applied" and card["spend"]["firecrawl"]["zero_data_retention_shown"] == "uygulandı"
    # The challenge is a note in both languages, with its numbers.
    row = next(row for row in get(client, audit, "/findings", limit=100)["items"] if row["check_id"] == "ACC-9")
    assert row["title"].startswith("Cloudflare challenged Maya's direct crawler on 1 of 1 request(s).") and not row["untranslated"] and row["notes_untranslated"] == 0
    assert row["title_shown"].startswith("Cloudflare, Maya'nın doğrudan tarayıcısını 1 istekten 1 tanesinde doğrulamaya aldı. Bunun yerine 3 sayfa Firecrawl üzerinden okundu.")
    assert "direct crawler on 1 of 1 request. 3 pages were read through Firecrawl instead." in english_page and "1 of 1 request(s)" not in english_page


def test_the_turkish_report_of_a_blocked_site_has_no_english_sentence(web):
    client = web(site=Site(respond=cloudflare))
    client.app.state.runner.engine.archives_transport = httpx.MockTransport(demo._no_archives)
    audit = start(client, plan(client, archives=True))
    assert audit["outcome"]["code"] == "DEGRADED"
    page, card, english_page, english_card = check_both_languages(client, audit)
    allow = card["blocked"]["allowlist"]["blocks"]
    assert [block["title"] for block in allow] == [block["title"] for block in english_card["blocked"]["allowlist"]["blocks"]]
    assert all(block["steps_shown"] != block["steps"] and len(block["steps_shown"]) == len(block["steps"]) for block in allow)
    assert "Cloudflare panelinde siteyi açın" in page and "In the Cloudflare dashboard open the site" in english_page
    assert card["archives"]["notice_shown"] == "Yalnızca geçmiş içerik; canlı erişim bulguları değişmedi." and card["archives"]["notice"].startswith("Historical content only")
    assert "INT-1 Sayfa başına getirme sınıflandırması: zayıfladı." in page and "Denetim zayıfladı: getirilen sayfaların 1/1 (100.0%) kadarı engellendi" in page


def test_the_launch_gate_says_what_is_translated_what_is_a_draft_and_what_stays_english():
    raw = json.loads((strings.LOCALES / "findings" / "tr.json").read_text(encoding="utf-8"))
    assert raw["_review"] == "machine-translated, needs native-speaker review" and {"labels", "label_patterns", "lines", "line_patterns"} <= set(raw)
    assert set(raw["label_patterns"]) == {frame.key for frame in wording.LABEL_PATTERNS} and set(raw["line_patterns"]) == {frame.key for frame in wording.LINE_PATTERNS}
    for section, frames in (("label_patterns", wording.LABEL_PATTERNS), ("line_patterns", wording.LINE_PATTERNS)):
        for frame in frames:
            assert wording.names(raw[section][frame.key]) <= set(frame.kinds), (frame.key, wording.names(raw[section][frame.key]), set(frame.kinds))
            # A plain hole is put back unchanged, so it may hold only a value: a hole that holds words is a "~" hole.
    gate = (Path(__file__).parent.parent / "docs" / "LAUNCH-GATE.md").read_text(encoding="utf-8")
    for said in ("check titles and summaries", "What could not be checked", "DataForSEO", "Firecrawl", "machine draft", "native speaker", "remains English"):
        assert said in gate, said
    for allow_list in (SUMMARIES_NOT_COVERED, REASONS_NOT_COVERED, FIRECRAWL_NOT_COVERED, DFS_NOT_COVERED, OTHER_NOT_COVERED, ANS_NOT_COVERED):
        assert all(isinstance(what if isinstance(what, str) else what[1], str) and why for what, why in allow_list.items())


# -- the "Example" row of a finding --------------------------------------------------------------------------------
# Examples that are code and nothing else: shown as they are in every language.
EXAMPLES_THAT_ARE_ONLY_CODE = (r"no Organization structured data", r"og:image|have no og:|have no twitter:")


def test_every_example_with_words_in_it_has_turkish_words_and_keeps_its_code():
    import re
    from maya_audit_web import practical, strings, wording
    table = wording.TABLES["tr"]["examples"]
    for pattern, example in practical.EXAMPLES:
        if pattern in EXAMPLES_THAT_ARE_ONLY_CODE:
            assert example not in table, pattern
            continue
        turkish = table.get(example)
        assert turkish and turkish != example, pattern
        # Tags, attribute names and addresses in the example are the same code in both languages.
        code = lambda text: sorted(set(re.findall(r"</?[a-z0-9]+|https?://[^\s\"<]+|\"@type\":\"[A-Za-z]+\"", text)))  # noqa: E731
        assert code(turkish) == code(example), pattern
    title = "1 page(s) are canonicalized to a URL with different content"
    assert practical.example_for(title).endswith("(one per page, pointing to a page that works)")
    strings.set_language("tr")
    try:
        assert practical.example_for(title).endswith("(her sayfada bir tane; çalışan bir sayfayı göstermeli)")
        assert practical.example_for("3 page(s) have no <title>") == table[dict(practical.EXAMPLES)[r"no <title>|generic title"]]
    finally:
        strings.set_language("en")
