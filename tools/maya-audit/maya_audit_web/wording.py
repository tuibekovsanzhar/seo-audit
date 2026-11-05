"""The engine's own sentences, as the reader is shown them: finding titles, fixes, expected results, notes, the
outcome sentence and the coverage reasons, in the reader's language.

The engine writes English ("16 internal link(s) on 4 page(s) carry tracking parameters (utm_source=gemini)"). The saved
report, the Markdown and JSON downloads keep that text. This module rewords it at display time only:

- English: a finding title is shown through its English display template, so "1 page(s) are" becomes "1 page is".
  Fixes, expected results, notes and every other sentence are shown as the engine wrote them, with a counted "(s)"
  resolved the same way (`english`).
- Another language (locales/findings/<language>.json): every sentence is looked up by its key or by its exact English
  text. Numbers, addresses, bot names, header names and quoted site text are taken out of the English sentence by the
  pattern's named holes and put back unchanged.
- A sentence with no entry is never dropped and never half-translated: it is shown whole, in English, followed by
  " (İngilizce)" in the Turkish view.

A new sentence needs table entries only: a line in `_TITLES` (or `FIX_PATTERNS`, `EXPECTED_PATTERNS`, `NOTE_PATTERNS`,
`OUTCOMES`, `TERM_PATTERNS`) and its translation under the same key in the JSON file; a fixed sentence needs only its
English text and translation in the JSON file. `tests/test_wording.py` reads the engine's source and fails when a
title, a fix or an expected result has no entry.

Everything else the engine says on the results card and in the printed report goes through two more doors (their
frames are in `sentences.py`, the same kind of table):

- `label`: a short name: a check's or a gate's title, the part of a check that was not assessed, a data panel's title,
  a column or a figure's name (`labels`, `label_patterns`).
- `line`: a sentence or a run of sentences: a check's or a gate's summary, the reason a part was not assessed, a line
  of the Firecrawl or DataForSEO section (`lines`, `line_patterns`). A run of sentences is put into the reader's
  language sentence by sentence; when one of them has no entry the whole run is shown in English with the mark.

In English both show the engine's text with "1 page(s)" said as "1 page" (`english`).

A frame is the engine's sentence with holes:
  {name}        any text, put back unchanged          {name#}   a number
  {name%}       a percentage ("27%")                  {name*}   any text, possibly none
  {name~}       a word or phrase that is itself translated (`terms`, `TERM_PATTERNS`); no translation, no match
  {name:regex}  any of the above with its own regular expression (no braces in it)
  [[name: text]]  a fixed piece that may be absent
A template (English display, or a translation) uses the same names: "{n:page is|pages are}" writes the number and the
word for one or many; "[n:its|their]" writes only the word.
"""

from __future__ import annotations

import json
import re
from typing import Any

from maya_audit.report import phrase

from functools import lru_cache

from . import strings
from .sentences import LABEL_PATTERNS as _LABEL_ROWS, LINE_PATTERNS as _LINE_ROWS, TERM_PATTERNS as _TERM_ROWS

# Said after a sentence that has no translation yet, in that language's view.
MARKS = {"tr": " (İngilizce)"}

_HOLE = re.compile(r"\{(\w+)([#~%*]?)(?::([^{}]*))?\}|\[\[(\w+):(.*?)\]\]")
_SILENT = re.compile(r"\[(\w+):([^\[\]|]*)\|([^\[\]]*)\]")
_DEFAULTS = {"": r".+?", "*": r".*?", "#": r"\d+(?:\.\d+)?", "%": r"\d+(?:\.\d+)?%", "~": r"[\w'<>/.-]+(?: [\w'<>/.-]+)?(?: [\w'<>/.-]+)?"}
_CODE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?")  # a language code the engine had no name for


class Frame:
    """One engine sentence with holes, compiled once."""

    def __init__(self, key: str, frame: str) -> None:
        self.key, self.frame, self.kinds = key, frame, {}
        out, at = [], 0
        for hole in _HOLE.finditer(frame):
            out.append(re.escape(frame[at:hole.start()]))
            at = hole.end()
            if hole.group(4):  # [[name: text]]
                self.kinds[hole.group(4)] = "?"
                out.append(f"(?P<{hole.group(4)}>{re.escape(hole.group(5))})?")
            else:
                name, kind, custom = hole.group(1), hole.group(2), hole.group(3)
                self.kinds[name] = kind
                out.append(f"(?P<{name}>{custom if custom is not None else _DEFAULTS[kind]})")
        out.append(re.escape(frame[at:]))
        self.regex = re.compile("".join(out), re.DOTALL)

    def values(self, text: str) -> dict[str, Any] | None:
        found = self.regex.fullmatch(text)
        if not found:
            return None
        return {name: (int(value) if self.kinds[name] == "#" and value.isdigit() else value or "")
                for name, value in found.groupdict().items()}


def _frames(rows: tuple[tuple[str, ...], ...]) -> tuple[Frame, ...]:
    return tuple(Frame(row[0], row[1]) for row in rows)


def fill(template: str, values: dict[str, Any]) -> str:
    """`template` with its holes filled: "[n:its|their]" first (the word only), then `phrase` ("{n:page|pages}")."""
    def word(found: re.Match) -> str:
        value = values.get(found.group(1))
        return found.group(2) if value == 1 or str(value).strip() == "1" else found.group(3)
    return phrase(_SILENT.sub(word, template), **values)


def names(template: str) -> set[str]:
    """The hole names a template uses, whatever form each takes."""
    return set(re.findall(r"\{(\w+)(?:[:!][^{}]*)?\}", template)) | {found.group(1) for found in _SILENT.finditer(template)}


# -- finding titles ----------------------------------------------------------------------------------------------------
# check id -> ((key, the engine's title as a frame, the English display template), ...). Exactly one frame of a check
# matches a title. The translation is `titles[key]` in the language file.
_TITLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "ACC-1": (
        ("acc1.server_error", "robots.txt returned a server error on {failed#} of {samples#} fetches",
         "robots.txt returned a server error on {failed} of {samples} fetches"),
        ("acc1.large", "robots.txt is larger than 500 KiB", "robots.txt is larger than 500 KiB"),
        ("acc1.html", "robots.txt returns an HTML page", "robots.txt returns an HTML page"),
        # A rule above the first User-agent line belongs to no group (H17).
        ("acc1.ungrouped", "{n#} robots.txt rule(s) come before any User-agent line, so no crawler applies them",
         "{n:robots.txt rule comes|robots.txt rules come} before any User-agent line, so no crawler applies them"),
    ),
    "ACC-2": (
        ("acc2.blocks.sitewide", "robots.txt line {line#} (Disallow: {pattern}) blocks {role~} bot(s) {tokens} sitewide",
         "robots.txt line {line} (Disallow: {pattern}) blocks {role} bots {tokens} sitewide"),
        ("acc2.blocks.sample", "robots.txt line {line#} (Disallow: {pattern}) blocks {role~} bot(s) {tokens} on {n#} sampled URL(s)",
         "robots.txt line {line} (Disallow: {pattern}) blocks {role} bots {tokens} on {n:sampled URL|sampled URLs}"),
        ("acc2.mismatch", "Policy mismatch: declared policy blocks {role~} bots, but robots.txt allows {allowed} on at least one sampled URL",
         "Policy mismatch: declared policy blocks {role} bots, but robots.txt allows {allowed} on at least one sampled URL"),
        ("acc2.precedence", "Group precedence: {tokens} have their own robots.txt group, so the * rule on line {line#} does not apply to them",
         "Group precedence: {tokens} have their own robots.txt group, so the * rule on line {line} does not apply to them"),
        ("acc2.retired", "robots.txt has rules for {tokens}, which no longer have any effect", "robots.txt has rules for {tokens}, which no longer have any effect"),
    ),
    "ACC-3": (
        # The checklist's quick checks (DECISIONS 304).
        ("acc3.robots_noindex", "{n#} page(s) carry noindex but robots.txt blocks search crawlers from reading it",
         "{n:page carries|pages carry} noindex but robots.txt blocks search crawlers from reading it"),
        ("acc3.noindex", "noindex via {where}[[review: (page intent should be reviewed)]] on {n#} page(s)", "noindex via {where}{review} on {n:page|pages}"),
        ("acc3.noindex_utility", "noindex via {where} on {n#} utility page(s) (such as a QR menu or a print page): check that this is intended",
         "noindex via {where} on {n:utility page|utility pages} (such as a QR menu or a print page): check that this is intended"),
        # noindex on a page only the sitemap puts forward, and the sitemap listing it (H26, CR-33).
        ("acc3.noindex_listed", "noindex via {where} on {n#} page(s) the sitemap lists: check that this is intended",
         "noindex via {where} on {n:page|pages} the sitemap lists: check that this is intended"),
        ("acc3.sitemap_noindex", "The sitemap lists {n#} page(s) that carry noindex", "The sitemap lists {n:page that carries|pages that carry} noindex"),
        # The site's own search results and cart answer 200 with no noindex (DECISIONS 300).
        ("acc3.utility_indexable", "{n#} internal search or cart page(s) can be indexed (no noindex)",
         "{n:internal search or cart page|internal search or cart pages} can be indexed (no noindex)"),
        # unavailable_after: a date that has passed works like noindex; one to come is a note (B06).
        ("acc3.unavailable_passed", "unavailable_after (date passed) via {where}[[review: (page intent should be reviewed)]] on {n#} page(s)",
         "unavailable_after (date passed) via {where}{review} on {n:page|pages}"),
        ("acc3.unavailable_listed", "unavailable_after (date passed) via {where} on {n#} page(s) the sitemap lists: check that this is intended",
         "unavailable_after (date passed) via {where} on {n:page|pages} the sitemap lists: check that this is intended"),
        ("acc3.unavailable_future", "unavailable_after {date:[^()]+?} via {where} on {n#} page(s)", "unavailable_after {date} via {where} on {n:page|pages}"),
        ("acc3.nosnippet", "nosnippet via {where} on {n#} page(s)", "nosnippet via {where} on {n:page|pages}"),
        ("acc3.max_snippet_zero", "max-snippet:0 via {where} on {n#} page(s)", "max-snippet:0 via {where} on {n:page|pages}"),
        ("acc3.max_snippet_low", "max-snippet below {limit#} via {where} on {n#} page(s)", "max-snippet below {limit} via {where} on {n:page|pages}"),
        ("acc3.noarchive", "noarchive via {where} on {n#} page(s)", "noarchive via {where} on {n:page|pages}"),
        ("acc3.nocache", "nocache via {where} on {n#} page(s)", "nocache via {where} on {n:page|pages}"),
        ("acc3.data_nosnippet", "main content inside data-nosnippet on {n#} page(s)", "Main content inside data-nosnippet on {n:page|pages}"),
        ("acc3.robots_outside_head", "{n#} page(s) carry a robots tag outside <head>: browsers ignore it; some crawlers may not",
         "{n:page carries|pages carry} a robots tag outside <head>: browsers ignore it; some crawlers may not"),
    ),
    "ACC-4": (
        ("acc4.outcome", "Requests with {role~} bot user agents were {outcome~} on {n#} URL(s): {tokens:.+?}[[once: (seen once, not retried)]]",
         "Requests with {role} bot user agents were {outcome} on {n:URL|URLs}: {tokens}{once}"),
        ("acc4.redirected", "Requests with {role~} bot user agents were redirected somewhere a browser was not sent on {n#} URL(s): {tokens}",
         "Requests with {role} bot user agents were redirected somewhere a browser was not sent on {n:URL|URLs}: {tokens}"),
        ("acc4.different", "Requests with {role~} bot user agents received different content than a browser on {n#} URL(s): {tokens}",
         "Requests with {role} bot user agents received different content than a browser on {n:URL|URLs}: {tokens}"),
        # Ownership not verified: a browser and Googlebot's user agent, one request each (DECISIONS 205).
        ("acc4.ua_check.status", "A request with Googlebot's user agent got {status:\\d+} on {n#} of {m#} URL(s) where a browser got {browser:\\d+}",
         "A request with Googlebot's user agent got {status} on {n} of {m:URL|URLs} where a browser got {browser}"),
        ("acc4.ua_check.size", "{n#} of {m#} URL(s) sent Googlebot's user agent a page of very different size than a browser's",
         "{n} of {m:URL|URLs} sent Googlebot's user agent a page of very different size than a browser's"),
        # An empty page to Googlebot's user agent (A21); a CDN challenge to an unverified Googlebot (A22).
        ("acc4.ua_check.empty", "{n#} of {m#} URL(s) sent Googlebot's user agent an empty page where a browser got the page",
         "{n} of {m:URL|URLs} sent Googlebot's user agent an empty page where a browser got the page"),
        ("acc4.ua_check.challenged", "{n#} of {m#} URL(s) challenged Googlebot's user agent from Maya's address: the real Googlebot may be on a verified-bot allowlist",
         "{n} of {m:URL|URLs} challenged Googlebot's user agent from Maya's address: the real Googlebot may be on a verified-bot allowlist"),
    ),
    "ACC-5": (
        ("acc5.never", "{n#} crawled page(s) that search bots may fetch were not fetched by any IP-verified search bot in the log window",
         "{n:crawled page|crawled pages} that search bots may fetch [n:was|were] not fetched by any IP-verified search bot in the log window"),
    ),
    "ACC-6": (
        ("acc6.scope", "{vendor:[^:]+}: Training{training*}: {ts~:[^·]+?} · Search{search*}: {ss~:[^·]+?} · Live fetch{live*}: {ls~:[^·]+}",
         "{vendor}: Training{training}: {ts} · Search{search}: {ss} · Live fetch{live}: {ls}"),
    ),
    "ACC-7": (
        ("acc7.delay", "Crawl-delay: {seconds#}s (robots.txt line {line#}) applies to {tokens}", "Crawl-delay: {seconds}s (robots.txt line {line}) applies to {tokens}"),
        ("acc7.capped", "robots.txt asks {agent} to wait {seconds#}s between requests (line {line#}); Maya honored {cap#}s, its cap",
         "robots.txt asks {agent} to wait {seconds}s between requests (line {line}); Maya honored {cap}s, its cap"),
    ),
    "ACC-8": (
        ("acc8.present", "{file:[\\w.-]+} is present", "{file} is present"),
        # Where the links of llms.txt lead, and its first line (DECISIONS 208).
        # Links that lead to IDX-1's empty pages are said there (DECISIONS 215).
        ("acc8.links.idx1", "{bad#} of {checked#} link(s) in {file:[\\w.-]+} lead to pages that do not work ({kinds~:.+}); {same#} of them lead to "
                            "the empty pages reported under IDX-1",
         "{bad} of {checked:link|links} in {file} lead to pages that do not work ({kinds}); {same} of them lead to the empty pages reported under IDX-1"),
        ("acc8.links", "{bad#} of {checked#} link(s) in {file:[\\w.-]+} lead to pages that do not work ({kinds~:.+})",
         "{bad} of {checked:link|links} in {file} lead to pages that do not work ({kinds})"),
        ("acc8.no_title", "{file:[\\w.-]+} does not open with a “# ” title line", "{file} does not open with a “# ” title line"),
        ("acc8.redirecting", "{n#} link(s) in {file:[\\w.-]+} point to an address that redirects",
         "{n:link|links} in {file} [n:points|point] to an address that redirects"),
    ),
    "ACC-9": (
        ("acc9.blocked_429", "Maya's crawler blocked (429 on pages): {who~:.+?} answered {blocked#} of {requested#} page request(s) with 429 while robots.txt and the sitemap were served. AI crawlers may get the same treatment",
         "Maya's crawler blocked (429 on pages): {who} answered {blocked} of {requested:page request|page requests} with 429 while robots.txt and the sitemap were served. AI crawlers may get the same treatment"),
        ("acc9.rate_limited_429", "Maya's crawler rate-limited (429 on pages): {who~:.+?} answered {blocked#} of {requested#} page request(s) with 429. AI crawlers may get the same treatment",
         "Maya's crawler rate-limited (429 on pages): {who} answered {blocked} of {requested:page request|page requests} with 429. AI crawlers may get the same treatment"),
        ("acc9.blocked", "The site blocks or challenges automated visitors: {who~:.+?} answered {blocked#} of {requested#} page request(s). AI crawlers may be affected too",
         "The site blocks or challenges automated visitors: {who} answered {blocked} of {requested:page request|page requests}. AI crawlers may be affected too"),
        # The same finding after the pages were read through Firecrawl (maya_audit.firecrawl.reader.note_the_challenge).
        ("acc9.reader.site.counted", "The site's bot protection {did~:challenged|rate-limited} Maya's direct crawler on {hit#} of {asked#} request(s). {read#} page(s) were read through Firecrawl instead. "
                                     "Genuine AI-crawler access was not measured.",
         "The site's bot protection {did} Maya's direct crawler on {hit} of {asked:request|requests}. {read:page was|pages were} read through Firecrawl instead. "
         "Genuine AI-crawler access was not measured."),
        ("acc9.reader.site", "The site's bot protection {did~:challenged|rate-limited} Maya's direct crawler. {read#} page(s) were read through Firecrawl instead. "
                             "Genuine AI-crawler access was not measured.",
         "The site's bot protection {did} Maya's direct crawler. {read:page was|pages were} read through Firecrawl instead. Genuine AI-crawler access was not measured."),
        ("acc9.reader.counted", "{who:(?!The site's bot protection).+?} {did~:challenged|rate-limited} Maya's direct crawler on {hit#} of {asked#} request(s). {read#} page(s) were read through Firecrawl instead. "
                                "Genuine AI-crawler access was not measured.",
         "{who} {did} Maya's direct crawler on {hit} of {asked:request|requests}. {read:page was|pages were} read through Firecrawl instead. "
         "Genuine AI-crawler access was not measured."),
        ("acc9.reader", "{who:(?!The site's bot protection).+?} {did~:challenged|rate-limited} Maya's direct crawler. {read#} page(s) were read through Firecrawl instead. "
                        "Genuine AI-crawler access was not measured.",
         "{who} {did} Maya's direct crawler. {read:page was|pages were} read through Firecrawl instead. Genuine AI-crawler access was not measured."),
    ),
    "IDX-1": (
        ("idx1.5xx", "{n#} URL(s) return a server error (5xx) on every attempt", "{n:URL returns|URLs return} a server error (5xx) on every attempt"),
        ("idx1.connection", "{n#} URL(s) fail at the connection level on every attempt", "{n:URL fails|URLs fail} at the connection level on every attempt"),
        ("idx1.timeout", "{n#} URL(s) time out on every attempt ({limit#}s limit)", "{n:URL times|URLs time} out on every attempt ({limit}s limit)"),
        ("idx1.4xx.referenced", "{n#} URL(s) return a client error (4xx), linked internally or listed in the sitemap",
         "{n:URL returns|URLs return} a client error (4xx), linked internally or listed in the sitemap"),
        ("idx1.4xx.unreferenced", "{n#} URL(s) return a client error (4xx), not referenced by any crawled page or the sitemap",
         "{n:URL returns|URLs return} a client error (4xx), not referenced by any crawled page or the sitemap"),
        ("idx1.soft404.redirect", "A page that does not exist redirects ({status#}) to the homepage (soft 404)",
         "A page that does not exist redirects ({status}) to the homepage (soft 404)"),
        ("idx1.soft404.200", "A page that does not exist answers 200, as if the page existed (soft 404)",
         "A page that does not exist answers 200, as if the page existed (soft 404)"),
        # A 2xx answer with nothing in it, and an error message with the server's paths (DECISIONS 204).
        ("idx1.empty", "{n#} page(s) answer with an empty page (under {limit#} bytes)",
         "{n:page answers|pages answer} with an empty page (under {limit} bytes)"),
        ("idx1.empty.bot", "{n#} page(s) answer with an empty page to automated clients only (under {limit#} bytes); "
                           "a browser gets content",
         "{n:page answers|pages answer} with an empty page to automated clients only (under {limit} bytes); a browser "
         "gets content"),
        ("idx1.error_text", "{n#} page(s) show a server error message with the server's file paths",
         "{n:page shows|pages show} a server error message with the server's file paths"),
        # A server error seen once, not asked again (review B17); IDX-6's dead targets said under IDX-1 (review H10).
        ("idx1.5xx.once", "{n#} URL(s) returned a server error (5xx) on the one request made",
         "{n:URL|URLs} returned a server error (5xx) on the one request made"),
        ("idx1.4xx.referenced.linked", "{n#} URL(s) return a client error (4xx), linked internally or listed in the sitemap; "
                                       "linked from {pages#} page(s)",
         "{n:URL returns|URLs return} a client error (4xx), linked internally or listed in the sitemap; linked from {pages:page|pages}"),
    ),
    "IDX-2": (
        ("idx2.invalid", "TLS certificate is not valid on {hosts:[^:]+}: {message}", "TLS certificate is not valid on {hosts}: {message}"),
        ("idx2.expires", "TLS certificate on {hosts} expires in {days#} day(s) ({date})", "TLS certificate on {hosts} expires in {days:day|days} ({date})"),
        # One finding for every host that is not redirected; what each host does is said in lines under it (decision 188).
        ("idx2.no_redirect.hosts", "No HTTP to HTTPS redirect on {hosts:[^()]+}", "No HTTP to HTTPS redirect on {hosts}"),
        # Reports saved before team-preview-13: one finding for each answer, said in a parenthesis (`SAVED_ONLY`).
        ("idx2.no_redirect", "No HTTP to HTTPS redirect on {hosts:[^(]+?} ({detail~:.+})", "No HTTP to HTTPS redirect on {hosts} ({detail})"),
        # Redirected, but with a 302/303/307 (review B12).
        ("idx2.temporary", "http:// redirects to https:// with a temporary redirect on {hosts}",
         "http:// redirects to https:// with a temporary redirect on {hosts}"),
    ),
    "IDX-3": (
        ('idx3.loop', '{n#} redirect loop(s): the URL never resolves', '{n:redirect loop|redirect loops} observed in the tested native client'),
        ('idx3.loop', '{n#} redirect loop(s) observed in the tested native client', '{n:redirect loop|redirect loops} observed in the tested native client'),
        ('idx3.cookie', '{n#} URL(s) loop for visitors without cookies (crawlers); with the cookie the site sets, the page loads', "{n:URL loops|URLs loop} in Maya's cookie-less checks; with the cookie the site sets, the page loads"),
        ('idx3.cookie', "{n#} URL(s) loop in Maya's cookie-less checks; with the cookie the site sets, the page loads", "{n:URL loops|URLs loop} in Maya's cookie-less checks; with the cookie the site sets, the page loads"),
        ("idx3.intermittent", "{n#} URL(s) intermittently redirect to themselves; the page loads on another try",
         "{n:URL intermittently redirects to itself|URLs intermittently redirect to themselves}; the page loads on another try"),
        ('idx3.self_once', '{n#} URL(s) redirected to themselves once; this could not be re-checked', '{n:URL has|URLs have} observed redirect cycles; verification is incomplete'),
        ('idx3.self_once', '{n#} URL(s) have observed redirect cycles; verification is incomplete', '{n:URL has|URLs have} observed redirect cycles; verification is incomplete'),
        ("idx3.chain", "{n#} redirect chain(s) of 2 or more hops", "{n:redirect chain|redirect chains} of 2 or more hops"),
        ("idx3.to_http", "{n#} page(s) redirect from https:// to an http:// address, which this audit did not follow",
         "{n:page redirects|pages redirect} from https:// to an http:// address, which this audit did not follow"),
        ("idx3.other_host", "{n#} page(s) redirect to another host, which this audit did not follow",
         "{n:page redirects|pages redirect} to another host, which this audit did not follow"),
    ),
    "IDX-4": (
        ("idx4.broken", "{n#} page(s) declare a canonical that is broken, noindexed, or an error",
         "{n:page declares|pages declare} a canonical that is broken, noindexed, or an error"),
        ("idx4.redirect_loop", "{n#} page(s) declare a canonical that redirects back to the page itself",
         "{n:page declares|pages declare} a canonical that redirects back to the page itself"),
        ("idx4.redirecting", "{n#} page(s) declare a canonical that redirects to another address",
         "{n:page declares|pages declare} a canonical that redirects to another address"),
        # Stage 8a (DECISIONS 315): a canonical of a canonical.
        ("idx4.chain", "{n#} page(s) declare a canonical to a page whose own canonical is another address",
         "{n:page declares|pages declare} a canonical to a page whose own canonical is another address"),
        ("idx4.conflict", "{n#} page(s) declare conflicting canonicals", "{n:page declares|pages declare} conflicting canonicals"),
        ("idx4.different", "{n#} page(s) are canonicalized to a URL with different content", "{n:page is|pages are} canonicalized to a URL with different content"),
        ("idx4.same", "{n#} page(s) are canonicalized to a URL with the same content", "{n:page is|pages are} canonicalized to a URL with the same content"),
        ("idx4.other_site", "{n#} page(s) declare a canonical on another site", "{n:page declares|pages declare} a canonical on another site"),
        # Review B02 / B03.
        ("idx4.variant", "{n#} page(s) declare a canonical on the http:// or www variant of this site",
         "{n:page declares|pages declare} a canonical on the http:// or www variant of this site"),
        ("idx4.mixed", "{n#} page(s) are noindex and declare a canonical to another URL",
         "{n:page is|pages are} noindex and [n:declares|declare] a canonical to another URL"),
    ),
    "IDX-5": (
        # The checklist's quick checks (DECISIONS 304).
        ("idx5.no_image_sitemap", "The sitemap lists no images although the pages read show {n#} different images",
         "The sitemap lists no images although the pages read show {n} different images"),
        ("idx5.no_video_sitemap", "The sitemap lists no videos although {n#} pages read show a video",
         "The sitemap lists no videos although {n:page read shows|pages read show} a video"),
        ("idx5.bad_share", "{bad#} of {assessed#} checked sitemap URLs ({share%}) are non-200 or noindex",
         "{bad} of {assessed} checked sitemap URLs ({share}) are non-200 or noindex"),
        ("idx5.identical", "All {n#} sitemap <lastmod> values are identical ({date})", "All {n} sitemap <lastmod> values are identical ({date})"),
        ("idx5.stamped", "{n#} sitemap document(s) give (nearly) every URL the same <lastmod>",
         "{n:sitemap document gives|sitemap documents give} (nearly) every URL the same <lastmod>"),
        ("idx5.future", "{n#} sitemap <lastmod> value(s) are in the future", "{n:sitemap <lastmod> value is|sitemap <lastmod> values are} in the future"),
        ("idx5.none", "No usable XML sitemap on a site with {pages:\\d+\\+?} discovered URLs", "No usable XML sitemap on a site with {pages} discovered URLs"),
        # Every sitemap URL, the crawl's and the sitemap check's (DECISIONS 206); `idx5.bad_share` is for saved reports.
        # The same, with IDX-1's empty or failing pages taken out of the finding's pages (DECISIONS 215).
        ("idx5.not_live.idx1", "{bad#} of {n#} sitemap URL(s) ({share%}) are not live, indexable pages; {same#} of them are the empty or failing "
                               "pages reported under IDX-1",
         "{bad} of {n:sitemap URL|sitemap URLs} ({share}) are not live, indexable pages; {same} of them are the empty or failing pages reported under IDX-1"),
        ("idx5.not_live.sampled.idx1", "{bad#} of {checked#} sitemap URL(s) checked ({share%}) are not live, indexable pages; the sitemap lists {n#}; "
                                       "{same#} of them are the empty or failing pages reported under IDX-1",
         "{bad} of {checked:sitemap URL|sitemap URLs} checked ({share}) are not live, indexable pages; the sitemap lists {n}; {same} of them are the "
         "empty or failing pages reported under IDX-1"),
        ("idx5.not_live", "{bad#} of {n#} sitemap URL(s) ({share%}) are not live, indexable pages",
         "{bad} of {n:sitemap URL|sitemap URLs} ({share}) are not live, indexable pages"),
        ("idx5.not_live.sampled", "{bad#} of {checked#} sitemap URL(s) checked ({share%}) are not live, indexable pages; the sitemap lists {n#}",
         "{bad} of {checked:sitemap URL|sitemap URLs} checked ({share}) are not live, indexable pages; the sitemap lists {n}"),
        # The same, the first number being the URLs left once IDX-1's are taken out (review CR-28).
        ("idx5.not_live.beside", "{rest#} of {n#} sitemap URL(s) are not live, indexable pages besides the {same#} empty or failing page(s) "
                                 "reported under IDX-1 ({share%} with them)",
         "{rest} of {n:sitemap URL|sitemap URLs} are not live, indexable pages besides the {same} empty or failing "
         "[same:page|pages] reported under IDX-1 ({share} with them)"),
        ("idx5.not_live.sampled.beside", "{rest#} of {checked#} sitemap URL(s) checked are not live, indexable pages besides the {same#} "
                                         "empty or failing page(s) reported under IDX-1 ({share%} with them); the sitemap lists {n#}",
         "{rest} of {checked:sitemap URL|sitemap URLs} checked are not live, indexable pages besides the {same} empty "
         "or failing [same:page|pages] reported under IDX-1 ({share} with them); the sitemap lists {n}"),
        # Drafts and tests left published (review H13).
        ("idx5.drafts", "{n#} draft or test page(s) are indexable and listed in the sitemap",
         "{n:draft or test page is|draft or test pages are} indexable and listed in the sitemap"),
        ("idx5.failed_files", "{n#} sitemap file(s) named in the sitemap index or robots.txt could not be loaded",
         "{n:sitemap file|sitemap files} named in the sitemap index or robots.txt could not be loaded"),
        ("idx5.malformed", "{n#} sitemap URL(s) are written wrongly: a “?” or a space inside the address",
         "{n:sitemap URL is|sitemap URLs are} written wrongly: a “?” or a space inside the address"),
        ("idx5.query_unassessed", "{n#} sitemap URL(s) use word-like queries; intended paths are unassessed",
         "{n:sitemap URL uses|sitemap URLs use} word-like queries; intended paths are unassessed"),
        ("idx5.corrupt", "{n#} sitemap URL(s) contain unescaped spaces or corrupted encoding",
         "{n:sitemap URL contains|sitemap URLs contain} unescaped spaces or corrupted encoding"),
        ("idx5.not_encoded", "{n#} sitemap URL(s) have letters that are not percent-encoded",
         "{n:sitemap URL has|sitemap URLs have} letters that are not percent-encoded"),
    ),
    "IDX-6": (
        # The checklist's quick checks (DECISIONS 304).
        ("idx6.alias_links", "{links#} internal link(s) on {pages#} page(s) point to an address whose canonical is another page",
         "{links:internal link|internal links} on {pages:page|pages} [links:points|point] to an address whose canonical is another page"),
        ("idx6.external_cycle", "{n#} external destination(s) produced a GET redirect cycle for the recorded client", "{n} external destinations produced a GET redirect cycle for the recorded client"),
        ("idx6.broken", "Link target returns {status#}, linked from {n#} page(s): {target}", "Link target returns {status}, linked from {n:page|pages}: {target}"),
        # Cloudflare's e-mail obfuscation (review H09).
        ("idx6.cf_email", "Cloudflare e-mail obfuscation is on: the address is readable only with JavaScript",
         "Cloudflare e-mail obfuscation is on: the address is readable only with JavaScript"),
        # Stage 8a (DECISIONS 315): links to an address that redirects.
        ("idx6.links_to_redirect", "{links#} internal link(s) on {pages#} page(s) point to an address that redirects",
         "{links:internal link|internal links} on {pages:page|pages} [links:points|point] to an address that redirects"),
        ("idx6.tracking", "{links#} internal link(s) on {pages#} page(s) carry tracking parameters ({params})",
         "{links:internal link|internal links} on {pages:page|pages} [links:carries|carry] tracking parameters ({params})"),
        # Reports saved before team-preview-14: the other address was not requested (`SAVED_ONLY`).
        ("idx6.other_site", "{links#} link(s) on {pages#} page(s) point to another site ({hosts}) at a path that exists on this one",
         "{links:link|links} on {pages:page|pages} [links:points|point] to another site ({hosts}) at a path that exists on this one"),
        ("idx6.other_site_dead", "{links#} link(s) on {pages#} page(s) point to another site ({hosts}) at a path that exists on this one, "
                                 "and the other address returns {status#}",
         "{links:link|links} on {pages:page|pages} [links:points|point] to another site ({hosts}) at a path that exists on this one, "
         "and the other address returns {status}"),
        # Links to other sites, each asked once with a HEAD (DECISIONS 211).
        ("idx6.external_gone", "{links#} link(s) to other sites on {pages#} page(s) return 404 or 410",
         "{links:link|links} to other sites on {pages:page|pages} [links:returns|return] 404 or 410"),
        ("idx6.other_site_unchecked", "{links#} link(s) on {pages#} page(s) point to another site ({hosts}) at a path that exists on this one; "
                                      "the other address could not be checked",
         "{links:link|links} on {pages:page|pages} [links:points|point] to another site ({hosts}) at a path that exists on this one; "
         "the other address could not be checked"),
    ),
    "IDX-7": (
        # The checklist's quick checks (DECISIONS 304).
        ("idx7.pagination_unlinked", "{n#} list page(s) do not link to their next page with an <a href> link",
         "{n:list page does|list pages do} not link to [n:its|their] next page with an <a href> link"),
        ("idx7.product_no_category", "{n#} product page(s) have no breadcrumb or link to a category in their content",
         "{n:product page has|product pages have} no breadcrumb or link to a category in [n:its|their] content"),
        ("idx7.deep", "{n#} page(s) are {depth#}+ clicks from the homepage", "{n:page is|pages are} {depth}+ clicks from the homepage"),
        ("idx7.orphan", "{n#} page(s) are listed only in the sitemap, with no internal links to them",
         "{n:page is|pages are} listed only in the sitemap, with no internal links to [n:it|them]"),
    ),
    "IDX-8": (
        # One finding for every group of copies and near-copies (DECISIONS 225); the two below are for saved reports.
        ("idx8.copies", "{groups#} {unit} of indexable pages that are copies or near-copies of each other ({pages#} pages)",
         "{groups} {unit} of indexable pages that are copies or near-copies of each other ({pages} pages)"),
        # Reports saved by team-preview-16, run 2 said "N group(s) ... are copies" (`SAVED_ONLY`).
        ("idx8.merged", "{groups#} group(s) of indexable pages are copies or near-copies of each other ({pages#} pages)",
         "{groups:group|groups} of indexable pages are copies or near-copies of each other ({pages} pages)"),
        ("idx8.location_template", "{n#} pages under /{section}/ differ mostly by the place name in their address",
         "{n} pages under /{section}/ differ mostly by the place name in their address"),
        ("idx8.identical", "{n#} indexable pages have identical visible text", "{n} indexable pages have identical visible text"),
        # One page at two addresses (review H20).
        ("idx8.two_addresses", "{n#} page(s) are reachable at two addresses", "{n:page is|pages are} reachable at two addresses"),
        ("idx8.near", "{n#} indexable pages have nearly identical main content (estimate)", "{n} indexable pages have nearly identical main content (estimate)"),
        # Reports saved before team-preview-13: a shared title is STR-1's finding now (decision 187; `SAVED_ONLY`).
        ("idx8.title", "{n#} indexable pages share the title {title}", "{n} indexable pages share the title {title}"),
    ),
    "IDX-9": (
        ("idx9.noindex", "Google reports the page excluded by noindex ({n#} key page(s))", "Google reports the page excluded by noindex ({n:key page|key pages})"),
        ("idx9.state", "Google reports: {state} ({n#} key page(s))", "Google reports: {state} ({n:key page|key pages})"),
        ("idx9.robots", "Google reports the page blocked by robots.txt ({n#} key page(s))", "Google reports the page blocked by robots.txt ({n:key page|key pages})"),
        ("idx9.canonical", "Google chose a different canonical than the page declares ({n#} key page(s))",
         "Google chose a different canonical than the page declares ({n:key page|key pages})"),
        ("idx9.no_rule", "Google reports a non-indexed state that has no severity rule ({n#} key page(s))",
         "Google reports a non-indexed state that has no severity rule ({n:key page|key pages})"),
    ),
    "IDX-10": (
        ("idx10.bing_error", "Bing's last crawl of {n#} key page(s) got an HTTP error", "Bing's last crawl of {n:key page|key pages} got an HTTP error"),
        ("idx10.indexnow", "IndexNow key file not found or not matching at {location}", "IndexNow key file not found or not matching at {location}"),
    ),
    "PRF-1": (
        ("prf1.slow", "{n#} page(s) take more than {limit#} s (median) to return their HTML",
         "{n:page takes|pages take} more than {limit} s (median) to return [n:its|their] HTML"),
        ("prf1.home_ttfb", "The homepage takes {ms#} ms (median of {n#} requests) to start answering",
         "The homepage takes {ms} ms (median of {n} requests) to start answering"),
        ("prf1.timeouts", "{n#} URL(s) time out on some attempts but not others", "{n:URL times|URLs time} out on some attempts but not others"),
        # How the HTML is delivered (H28, H32).
        ("prf1.not_cached", "The HTML of {n#} page(s) is not cached at the CDN ({statuses})",
         "The HTML of {n:page is|pages is} not cached at the CDN ({statuses})"),
        ("prf1.security_headers", "The homepage answers without {n#} baseline security header(s)",
         "The homepage answers without {n:baseline security header|baseline security headers}"),
        ("prf1.no_hsts", "The https homepage sends no Strict-Transport-Security header",
         "The https homepage sends no Strict-Transport-Security header"),
    ),
    "PRF-2": (
        ("prf2.some", "{n#} URL(s) failed on some attempts and worked on others", "{n:URL|URLs} failed on some attempts and worked on others"),
        ("prf2.rate", "{rate%} of fetches failed across the audit (threshold {threshold%})", "{rate} of fetches failed across the audit (threshold {threshold})"),
    ),
    "PRF-3": (
        ("prf3.poor", "{n#} URL(s) have real-user {metric} in Google's 'poor' range[[origin: (whole-origin data for some)]]",
         "{n:URL has|URLs have} real-user {metric} in Google's 'poor' range{origin}"),
    ),
    "RND-1": (
        ("rnd1.missing", "Main content is missing from the raw HTML of {n#} page(s): it appears only after JavaScript runs",
         "Main content is missing from the raw HTML of {n:page|pages}: it appears only after JavaScript runs"),
        ("rnd1.partial", "Part of the content ({low%}–{high%} present) is missing from the raw HTML of {n#} page(s)",
         "Part of the content ({low}–{high} present) is missing from the raw HTML of {n:page|pages}"),
        ("rnd1.maybe", "{n#} page(s) that were not rendered may be client-rendered (raw-HTML heuristics)",
         "{n:page that was|pages that were} not rendered may be client-rendered (raw-HTML heuristics)"),
    ),
    "RND-2": (
        ("rnd2.not_found", "{n#} declared critical fact(s) were not found on their page at all",
         "{n:declared critical fact was|declared critical facts were} not found on [n:its|their] page at all"),
        ("rnd2.candidates", "{n#} rendered page(s) have headings or prices that appear only after JavaScript (automatic candidates)",
         "{n:rendered page has|rendered pages have} headings or prices that appear only after JavaScript (automatic candidates)"),
        ("rnd2.after_js", "{n#} declared critical fact(s) appear only after JavaScript runs",
         "{n:declared critical fact appears|declared critical facts appear} only after JavaScript runs"),
        ("rnd2.markup_only", "{n#} declared critical fact(s) exist only inside markup (script data or attributes), not as visible text",
         "{n:declared critical fact exists|declared critical facts exist} only inside markup (script data or attributes), not as visible text"),
    ),
    "RND-3": (
        ("rnd3.revealed", "{n#} page(s) show more content only after a click or scroll", "{n:page shows|pages show} more content only after a click or scroll"),
        ("rnd3.maybe", "{n#} page(s) that were not rendered may hide content behind interaction (raw-HTML heuristics)",
         "{n:page that was|pages that were} not rendered may hide content behind interaction (raw-HTML heuristics)"),
    ),
    "RND-4": (
        ("rnd4.layout_canvas", "The same <canvas> is on {n#} of {total#} page(s): part of the site's layout, with no text equivalent",
         "The same <canvas> is on {n} of {total:page|pages}: part of the site's layout, with no text equivalent"),
        ("rnd4.iframe", "{n#} page(s) embed content in an iframe; essential content and accessibility are not established",
         "{n:page embeds|pages embed} content in an iframe; essential content and accessibility are not established"),
        ("rnd4.canvas", "{n#} page(s) draw content on a <canvas> with no text equivalent", "{n:page draws|pages draw} content on a <canvas> with no text equivalent"),
        ("rnd4.banner", "{n#} page(s) show banner-shaped images with no alt text in main content (may contain text)",
         "{n:page shows|pages show} banner-shaped images with no alt text in main content (may contain text)"),
    ),
    "RND-5": (
        ("rnd5.redirect", "{n#} page(s) redirect a cookie-less visitor to a login, consent, age, or country page",
         "{n:page redirects|pages redirect} a cookie-less visitor to a login, consent, age, or country page"),
        # An account, cart or checkout page that asks for a sign-in: a note (DECISIONS 173).
        ("rnd5.account_login", "{n#} account, cart or checkout page(s) send a signed-out visitor to the login page (expected)",
         "{n:account, cart or checkout page sends|account, cart or checkout pages send} a signed-out visitor to the login page (expected)"),
        ("rnd5.in_place", "{n#} page(s) serve a short page that looks like a consent, login, age, or geo wall instead of the content",
         "{n:page serves|pages serve} a short page that looks like a consent, login, age, or geo wall instead of the content"),
        ("rnd5.paywall", "{n#} page(s) look paywalled but have no isAccessibleForFree structured data",
         "{n:page looks paywalled but has|pages look paywalled but have} no isAccessibleForFree structured data"),
    ),
    "RND-6": (
        # Measured on Firecrawl's rendered copies (DECISIONS 299): said in the title.
        ("rnd6.large_fc", "{n#} page(s) have HTML larger than {kb#} KB (rendered HTML via Firecrawl, not comparable with raw size)",
         "{n:page has|pages have} HTML larger than {kb} KB (rendered HTML via Firecrawl, not comparable with raw size)"),
        ("rnd6.home_large_fc", "The homepage's HTML is {kb#} KB, above {limit#} KB (rendered HTML via Firecrawl, not comparable with raw size)",
         "The homepage's HTML is {kb} KB, above {limit} KB (rendered HTML via Firecrawl, not comparable with raw size)"),
        ("rnd6.late_fc", "{n#} page(s) start their main content more than {kb#} KB into the HTML (rendered HTML via Firecrawl, not comparable with raw size)",
         "{n:page starts its|pages start their} main content more than {kb} KB into the HTML (rendered HTML via Firecrawl, not comparable with raw size)"),
        ("rnd6.large", "{n#} page(s) have HTML larger than {kb#} KB", "{n:page has|pages have} HTML larger than {kb} KB"),
        ("rnd6.home_large", "The homepage's HTML is {kb#} KB, above {limit#} KB", "The homepage's HTML is {kb} KB, above {limit} KB"),
        ("rnd6.late", "{n#} page(s) start their main content more than {kb#} KB into the HTML",
         "{n:page starts its|pages start their} main content more than {kb} KB into the HTML"),
    ),
    "RND-7": (
        ("rnd7.share", "{n#} page(s) have less than {share%} of their text in the main content",
         "{n:page has|pages have} less than {share} of [n:its|their] text in the main content"),
        ("rnd7.no_region", "{n#} page(s) have no <main> or <article> element", "{n:page has|pages have} no <main> or <article> element"),
    ),
    "STR-1": (
        ("str1.no_title", "{n#} page(s) have no <title>", "{n:page has|pages have} no <title>"),
        ("str1.shared", "{titles#} title(s) are shared by {pages#} different indexable pages", "{titles:title is|titles are} shared by {pages} different indexable pages"),
        ("str1.same_start", "{n#} page title(s) begin with the same {chars#} characters as another page's, so they look alike where a title is cut short",
         "{n:page title begins|page titles begin} with the same {chars} characters as another page's, so they look alike where a title is cut short"),
        ("str1.generic", "{n#} page(s) have a generic title", "{n:page has|pages have} a generic title"),
    ),
    "STR-2": (
        ("str2.home_no_h1", "The homepage has no <h1>", "The homepage has no <h1>"),
        ("str2.home_hidden_h1", "The homepage's only <h1> is hidden", "The homepage's only <h1> is hidden"),
        ("str2.home_outline", "The homepage has {n#} visible section heading(s) for {words#} words",
         "The homepage has {n:visible section heading|visible section headings} for {words} words"),
        ("str2.hidden_h1", "{n#} page(s) have only a hidden <h1>", "{n:page has|pages have} only a hidden <h1>"),
        ("str2.no_h1", "{n#} page(s) have no <h1>", "{n:page has|pages have} no <h1>"),
        ("str2.empty_h1", "{n#} page(s) have an empty <h1>", "{n:page has|pages have} an empty <h1>"),
        ("str2.no_subheadings", "{n#} long page(s) (>{words#} words) have no subheadings", "{n:long page|long pages} (>{words} words) [n:has|have] no subheadings"),
        ("str2.many_h1", "{n#} page(s) have more than one <h1>", "{n:page has|pages have} more than one <h1>"),
    ),
    "STR-3": (
        # The checklist's quick checks (DECISIONS 304).
        ("str3.article_no_author", "{n#} article page(s) name no author (no byline or author markup)",
         "{n:article page names|article pages name} no author (no byline or author markup)"),
        ("str3.product_no_identifier", "{n#} product page(s) have Product markup without a GTIN or MPN",
         "{n:product page has|product pages have} Product markup without a GTIN or MPN"),
        ("str3.unparsed", "{n#} page(s) have JSON-LD that does not parse", "{n:page has|pages have} JSON-LD that does not parse"),
        ("str3.no_organization", "The homepage has no Organization structured data", "The homepage has no Organization structured data"),
        ("str3.organization_broken", "The homepage's Organization block does not parse",
         "The homepage's Organization block does not parse"),
        ("str3.organization_gaps", "The homepage's Organization structured data has no {what}",
         "The homepage's Organization structured data has no {what}"),
        ("str3.invalid_values", "{n#} page(s) have structured data values in a form Google cannot read",
         "{n:page has|pages have} structured data values in a form Google cannot read"),
        ("str3.required", "{n#} page(s) have structured data missing Google-required properties",
         "{n:page has|pages have} structured data missing Google-required properties"),
        ("str3.video_default", "{n#} page(s) have a VideoObject that looks like an unfilled default",
         "{n:page has|pages have} a VideoObject that looks like an unfilled default"),
        ("str3.expected_type", "{n#} page(s) lack the structured data type expected for their page kind",
         "{n:page lacks|pages lack} the structured data type expected for [n:its|their] page kind"),
        # P2: what the pages show, not their address.
        ("str3.qa_no_faqpage", "{n#} page(s) show questions and answers but have no FAQPage structured data",
         "{n:page shows|pages show} questions and answers but [n:has|have] no FAQPage structured data"),
        ("str3.crumb_no_list", "{n#} page(s) show a breadcrumb trail but have no BreadcrumbList structured data",
         "{n:page shows|pages show} a breadcrumb trail but [n:has|have] no BreadcrumbList structured data"),
        ("str3.maybe_product", "{n#} page(s) show one price and no buy button: they may be product pages, check",
         "{n:page shows|pages show} one price and no buy button: [n:it may be a product page|they may be product pages], check"),
        ("str3.url_error", "{n#} page(s) name a URL in their structured data that returns an error",
         "{n:page names|pages name} a URL in [n:its|their] structured data that returns an error"),
        ("str3.url_differs", "{n#} page(s) name a different URL in their structured data than their canonical",
         "{n:page names|pages name} a different URL in [n:its|their] structured data than [n:its|their] canonical"),
        ("str3.dangling_id", "{n#} page(s) reference an @id that no crawled page defines", "{n:page references|pages reference} an @id that no crawled page defines"),
        ("str3.type_clash", "{n#} @id(s) are given different types in different places", "{n:@id is|@ids are} given different types in different places"),
    ),
    "STR-4": (
        ("str4.differs", "{n#} page(s): structured-data {field~:.+?} differs from the {same~:.+?} shown on the page",
         "{n:page|pages}: structured-data {field} differs from the {same} shown on the page"),
        ("str4.not_shown", "{n#} page(s): structured-data {field~:.+?} is not shown on the page", "{n:page|pages}: structured-data {field} is not shown on the page"),
        ("str4.other_state", "{n#} page(s): the markup lists {prices#} price(s) the page did not show when it was read",
         "{n:page|pages}: the markup lists {prices:price|prices} the page did not show when it was read"),
        # No price of the page's own, or several: a person looks (DECISIONS 175).
        ("str4.price_unclear", "{n#} page(s): the markup price is not shown on the page, or the page's own price could not be told apart",
         "{n:page|pages}: the markup price is not shown on the page, or the page's own price could not be told apart"),
    ),
    "STR-5": (
        ("str5.id_names", "{n#} brand @id(s) carry a different name on different pages", "{n:brand @id carries|brand @ids carry} a different name on different pages"),
        ("str5.names", "The brand is named {n#} different ways", "The brand is named {n} different ways"),
        ("str5.og_site_name", "og:site_name holds the page title on {n#} page(s)", "og:site_name holds the page title on {n:page|pages}"),
        ("str5.same_as", "{n#} sameAs profile link(s) return 404/410", "{n:sameAs profile link returns|sameAs profile links return} 404/410"),
    ),
    "STR-6": (
        ("str6.stamped", "{kind~:.+?} looks auto-stamped: {count#} of {carrying#} pages carry {how~:.+}",
         "{kind} looks auto-stamped: {count} of {carrying} pages carry {how}"),
        ("str6.future", "{n#} page(s) carry a future date", "{n:page carries|pages carry} a future date"),
        ("str6.apart", "{n#} page(s) have date signals more than {limit#} days apart", "{n:page has|pages have} date signals more than {limit} days apart"),
        ("str6.no_date", "{n#} article-type page(s) show no published or updated date", "{n:article-type page shows|article-type pages show} no published or updated date"),
    ),
    "STR-7": (
        ("str7.broken", "{broken#} of {fetched#} sampled image file(s) do not load", "{broken} of {fetched:sampled image file|sampled image files} [broken:does|do] not load"),
        ("str7.formats", "{share%} of {images#} content image(s) are offered in WebP or AVIF", "{share} of {images:content image|content images} are offered in WebP or AVIF"),
        # The title until 2026-10-11 (kept for saved reports), and the one that says the two cases apart (DECISIONS 178).
        ("str7.alt_missing", "{images#} likely meaningful image(s) on {pages#} page(s) have missing or empty alt text",
         "{images:likely meaningful image|likely meaningful images} on {pages:page|pages} [images:has|have] missing or empty alt text"),
        ("str7.alt_split", "{images#} likely meaningful image(s) on {pages#} page(s): {missing#} with no alt text, {empty#} with an empty alt",
         "{images:likely meaningful image|likely meaningful images} on {pages:page|pages}: {missing} with no alt text, {empty} with an empty alt"),
        ("str7.no_alt", "{images#} other image(s) on {pages#} page(s) have no alt attribute",
         "{images:other image|other images} on {pages:page|pages} [images:has|have] no alt attribute"),
        # H29: heavy and mislabelled media files.
        ("str7.heavy", "{n#} sampled image file(s) are over 500 KB", "{n:sampled image file is|sampled image files are} over 500 KB"),
        # Stage 8a (DECISIONS 315).
        ("str7.over_100kb", "{n#} sampled image file(s) are between 100 and 500 KB",
         "{n:sampled image file is|sampled image files are} between 100 and 500 KB"),
        ("str7.mime", "{n#} sampled image file(s) are served in a format their file name does not say",
         "{n:sampled image file is|sampled image files are} served in a format [n:its|their] file name does not say"),
        # H30: loading behaviour read from the markup.
        ("str7.unsized", "{n#} image(s) on {pages#} page(s) have no width and height (layout shift risk)",
         "{n:image|images} on {pages:page|pages} [n:has|have] no width and height (layout shift risk)"),
        ("str7.preload_type", "{n#} image preload(s) declare type=\"image/jpg\", which is not a media type",
         "{n:image preload declares|image preloads declare} type=\"image/jpg\", which is not a media type"),
        ("str7.video", "{n#} video file(s) the pages play are over 5 MB", "{n:video file|video files} the pages play [n:is|are] over 5 MB"),
        # One image most pages carry, reported once for the whole site (maya_audit.shared_elements).
        ("shared.image_no_alt", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: image {src} has no alt text (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: image {src} has no alt text (on {n:page|pages}{section})"),
    ),
    "STR-8": (
        ("str8.pricing", "{n#} page(s) lay out pricing or spec comparisons as <div> grids instead of <table>",
         "{n:page lays|pages lay} out pricing or spec comparisons as <div> grids instead of <table>"),
        ("str8.other", "{n#} page(s) have other table-like <div> grids", "{n:page has|pages have} other table-like <div> grids"),
        ("str8.headers", "{tables#} data table(s) on {n#} page(s) lack supported header associations", "Data tables lacking supported header associations: {tables}; affected pages: {n}"),
        ("str8.empty_table", "{n#} page(s) contain an empty <table> element", "{n:page contains|pages contain} an empty <table> element"),
    ),
    "STR-9": (
        ("str9.status", "{n#} page(s) have hreflang links to URLs that do not return 200", "{n:page has|pages have} hreflang links to URLs that do not return 200"),
        ("str9.no_return", "{n#} page(s) have hreflang links that are not returned", "{n:page has|pages have} hreflang links that are not returned"),
        ("str9.lang_mismatch", "{n#} page(s) declare a <html lang> that does not match the content language",
         "{n:page declares|pages declare} a <html lang> that does not match the content language"),
        ("str9.no_lang", "{n#} page(s) have no <html lang>", "{n:page has|pages have} no <html lang>"),
        ("str9.bad_lang", "{n#} page(s) have a malformed <html lang> value", "{n:page has|pages have} a malformed <html lang> value"),
        ("str9.bad_codes", "{n#} page(s) have malformed hreflang codes", "{n:page has|pages have} malformed hreflang codes"),
        ("str9.relative", "{n#} page(s) use relative hreflang URLs", "{n:page uses|pages use} relative hreflang URLs"),
        ("str9.same_code", "{n#} page(s) give the same hreflang code to two or more URLs",
         "{n:page gives|pages give} the same hreflang code to two or more URLs"),
        ("str9.target_page", "{n#} hreflang target page(s) are not indexable or have an empty title or description",
         "{n:hreflang target page is|hreflang target pages are} not indexable or have an empty title or description"),
        ("str9.cluster", "{n#} page(s) with hreflang links lack x-default or a link to themselves",
         "{n:page with hreflang links lacks|pages with hreflang links lack} x-default or a link to themselves"),
        # Stage 8a (DECISIONS 315).
        ("str9.wrong_language", "{n#} page(s) have hreflang links whose target page declares another language",
         "{n:page has|pages have} hreflang links whose target page declares another language"),
    ),
    "STR-10": (
        ("str10.no_twitter", "{n#} page(s) have Open Graph tags but no Twitter card", "{n:page has|pages have} Open Graph tags but no Twitter card"),
        ("str10.og_image_dead", "{n#} page(s) have an og:image that returns 404/410", "{n:page has|pages have} an og:image that returns 404/410"),
        # The site icon, or an image under 200 × 200, as share image (DECISIONS 209).
        ("str10.icon", "{n#} page(s) use the site icon as share image (og:image is a .ico file)",
         "{n:page uses|pages use} the site icon as share image (og:image is a .ico file)"),
        ("str10.small", "{n#} page(s) have a share image smaller than 200 × 200 pixels",
         "{n:page has|pages have} a share image smaller than 200 × 200 pixels"),
        ("str10.thumb", "{n#} page(s) have a share image smaller than 600 × 315 pixels (shown as a small thumbnail)",
         "{n:page has|pages have} a share image smaller than 600 × 315 pixels (shown as a small thumbnail)"),
        ("str10.no_description", "{n#} page(s) have no meta description", "{n:page has|pages have} no meta description"),
        ("str10.no_tag", "{n#} page(s) have no {tag:(?:og|twitter):[\\w:]+}", "{n:page has|pages have} no {tag}"),
        ("str10.empty_tag", "{n#} page(s) have an empty {tag:(?:og|twitter):[\\w:]+}", "{n:page has|pages have} an empty {tag}"),
    ),
    "STR-11": (
        ("str11.two_values", "{n#} page(s) describe the same entity twice in structured data with a different {field}",
         "{n:page describes|pages describe} the same entity twice in structured data with a different {field}"),
    ),
    "STR-12": (
        ("str12.language", "{n#} page(s) are mostly in another language than they declare ({label~:.+})",
         "{n:page is|pages are} mostly in another language than [n:it declares|they declare] ({label})"),
        ("str12.headings", "{n#} page(s) have section headings in another language than they declare ({label~:.+})",
         "{n:page has|pages have} section headings in another language than [n:it declares|they declare] ({label})"),
        ("str12.placeholder", "{n#} page(s) contain placeholder or template text", "{n:page contains|pages contain} placeholder or template text"),
    ),
    "STR-13": (
        ("str13.markers", "{n#} page(s) have unfilled template markers in {where~:JSON-LD|meta tag|the title|link or image URL|visible text}: {markers}{more~:(?: and \\d+ more)?}",
         "{n:page has|pages have} unfilled template markers in {where}: {markers}{more}"),
        # Zero-width spaces, soft hyphens and the like in the main text (DECISIONS 210).
        ("str13.invisible", "{n#} page(s) have invisible characters in the main text ({count#} in all)",
         "{n:page has|pages have} invisible characters in the main text ({count} in all)"),
        ("str13.raw_only", "{n#} page(s) have template markers in the raw HTML only (filled in by the browser): {markers}{more~:(?: and \\d+ more)?}",
         "{n:page has|pages have} template markers in the raw HTML only (filled in by the browser): {markers}{more}"),
    ),
    "STR-14": (
        ("str14.generic", "{links#} link(s) on {pages#} page(s) name their target only with generic text: {top}",
         "{links:link|links} on {pages:page|pages} [links:names its|name their] target only with generic text: {top}"),
        ("str14.no_text", "{links#} link(s) on {pages#} page(s) have no text at all", "{links:link|links} on {pages:page|pages} [links:has|have] no text at all"),
        # One nameless link most pages carry (an icon in the header), reported once for the whole site.
        ("shared.link_no_text", "{label~:Shared header/footer|Repeated block}: link to {href} has no text (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: link to {href} has no text (on {n:page|pages}{section})"),
        # Nameless links in one block the markup names ("div.post-related"), counted (DECISIONS 198).
        ("shared.block_links_no_text", "“{block:[^”]+}” block: {links#} link(s) have no text (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "“{block}” block: {links:link has|links have} no text (on {n:page|pages}{section})"),
        # One generic link most pages carry (a cookie notice's "tıklayınız"), by its text and its address.
        ("shared.link_generic", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: link “{text}” to {href} has only generic text (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: link “{text}” to {href} has only generic text (on {n:page|pages}{section})"),
        # One template element whose address differs on every page (each product page's link to its own photo).
        ("shared.link_no_text_pattern", "Shared template: links to {pattern} have no text (on {n#} page(s){section~:(?: of /[^/ ]+/)?}), for example {href}",
         "Shared template: links to {pattern} have no text (on {n:page|pages}{section}), for example {href}"),
    ),
    "STR-15": (
        # The checklist's quick checks (DECISIONS 304).
        ("str15.empty_collections", "{n#} indexable collection or category page(s) list no product or almost none",
         "{n:indexable collection or category page lists|indexable collection or category pages list} no product or almost none"),
        ("str15.thin", "{n#} content page(s) have fewer than {words#} words of their own text",
         "{n:content page has|content pages have} fewer than {words} words of [n:its|their] own text"),
    ),
    "STR-16": (
        ("str16.shared", "{groups#} meta description(s) are shared by {pages#} different indexable pages",
         "{groups:meta description is|meta descriptions are} shared by {pages} different indexable pages"),
    ),
    "STR-17": (
        ("str17.dead_end", "{n#} page(s) have no link to any other page of this site", "{n:page has|pages have} no link to any other page of this site"),
    ),
    "STR-18": (
        ("str18.no_brand", "The homepage title does not name the brand ({title})", "The homepage title does not name the brand ({title})"),
    ),
    "STR-19": (
        ("str19.no_target", "{n#} link(s) have no address a crawler can follow (they may still work for visitors through JavaScript)",
         "{n:link has|links have} no address a crawler can follow ([n:it|they] may still work for visitors through JavaScript)"),
        ("str19.footer", "{links#} link(s) on {pages#} page(s) in the footer look like links but have no address",
         "{links:link|links} on {pages:page|pages} in the footer [links:looks like a link but has|look like links but have] no address"),
        # Reports saved before team-preview-8 said it this way (`SAVED_ONLY`: no engine source writes it any more).
        ("str19.lead_nowhere", "{links#} link(s) on {pages#} page(s) lead nowhere (href=\"#\" or a javascript: address)",
         "{links:link|links} on {pages:page|pages} [links:leads|lead] nowhere (href=\"#\" or a javascript: address)"),
        ("str19.controls", "{n#} control(s) are coded as links (href=\"#\"); use <button> for screen readers.",
         "{n:control is|controls are} coded as links (href=\"#\"); use <button> for screen readers."),
        ("str19.control_review", "{n#} control group(s) use anchors; interaction and accessibility require review",
         "{n:control group uses|control groups use} anchors; interaction and accessibility require review"),
        # One link without an address most pages carry (a footer's "cookie settings"), reported once for the whole site.
        ("shared.link_no_address", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: link “{text}” has no address (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: link “{text}” has no address (on {n:page|pages}{section})"),
        # The entries of one menu: links without an address that sit on exactly the same pages, listed together.
        ("shared.links_no_address", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: {links#} links have no address ({texts:“.+?”}{more~:(?: and \\d+ more)?}) (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: {links} links have no address ({texts}{more}) (on {n:page|pages}{section})"),
    ),
    "STR-20": (
        ("str20.media", "{n#} page(s) carry their message in video or animation, with fewer than {words#} words of text",
         "{n:page carries its|pages carry their} message in video or animation, with fewer than {words} words of text"),
    ),
    "STR-21": (
        ("str21.missing", "No {missing~:.+?} page was found among the {n#} page(s) of the site", "No {missing} page was found among the {n:page|pages} of the site"),
    ),
    "STR-22": (
        ("str22.link_lists", "{n#} news or press page(s) consist of links to other sites, with little text of their own",
         "{n:news or press page consists|news or press pages consist} of links to other sites, with little text of [n:its|their] own"),
    ),
    "STR-23": (
        ("str23.listed", "{pages#} careers page(s) list {jobs#} job opening(s) on the page itself, with no JobPosting structured data",
         "{pages:careers page lists|careers pages list} {jobs:job opening|job openings} on the page itself, with no JobPosting structured data"),
        ("str23.pages", "{n#} job page(s) have no JobPosting structured data", "{n:job page has|job pages have} no JobPosting structured data"),
    ),
    # The answer-engine panel (shown apart from the site findings; its rows open in the evidence drawer).
    "ANS-1": (
        ("ans1.fails", "Cited URL fails a site check ({failures}): {url}", "Cited URL fails a site check ({failures}): {url}"),
    ),
    "ANS-2": (
        ("ans2.contradicts", "{n#} answer(s) state {what~:a price or plan|a fact} that the cited page contradicts",
         "{n:answer states|answers state} {what} that the cited page contradicts"),
        ("ans2.not_shown", "{n#} answer claim(s) state something the cited page does not show", "{n:answer claim states|answer claims state} something the cited page does not show"),
    ),
    "ANS-4": (
        ("ans4.none_from_site", "{engine} cited {mentions#} domain-mentions on this topic and none from this site",
         "{engine} cited {mentions} domain-mentions on this topic and none from this site"),
    ),
    "TSEO-1": (
        # The checklist's quick checks (DECISIONS 304).
        ("tseo1.url_decomposed", "{n#} address(es) contain a decomposed character (a letter followed by a combining mark)",
         "{n:address contains|addresses contain} a decomposed character (a letter followed by a combining mark)"),
        ("tseo1.url_slug_unclear", "{n#} page address(es) have an unclear slug (an id only, over 100 characters, or spaces and symbols)",
         "{n:page address has|page addresses have} an unclear slug (an id only, over 100 characters, or spaces and symbols)"),
        # H30, H32 (maya_audit.checks.page_markup).
        ("tseo1.no_viewport", "{n#} page(s) have no viewport meta tag", "{n:page has|pages have} no viewport meta tag"),
        # DECISIONS 260: a body element inside <head> ends it early.
        ("tseo1.head_closed_lost", "{n#} page(s) end <head> early: canonical, robots or hreflang tags after it are read as body",
         "{n:page ends|pages end} <head> early: canonical, robots or hreflang tags after it are read as body"),
        ("tseo1.head_closed_later", "{n#} page(s) end <head> early: meta or Open Graph tags after it are read as body",
         "{n:page ends|pages end} <head> early: meta or Open Graph tags after it are read as body"),
        ("tseo1.no_zoom", "{n#} page(s) stop readers from zooming (user-scalable=no or maximum-scale=1)",
         "{n:page stops|pages stop} readers from zooming (user-scalable=no or maximum-scale=1)"),
        ("tseo1.analytics_twice", "{n#} page(s) load the same analytics tag more than once (possible double counting)",
         "{n:page loads|pages load} the same analytics tag more than once (possible double counting)"),
        ("tseo1.mixed", "{n#} https page(s) load resources over plain http:// (mixed content)",
         "{n:https page loads|https pages load} resources over plain http:// (mixed content)"),
        ("tseo1.blocking_scripts", "{pages#} page(s) load {n#} script(s) in <head> without defer or async",
         "{pages:page loads|pages load} {n:script|scripts} in <head> without defer or async"),
        ("tseo1.title_short", "{n#} page title(s) below the {limit#}-character guidance band", "{n:page title|page titles} below the {limit}-character guidance band"),
        ("tseo1.title_long", "{n#} page title(s) above the {limit#}-character guidance band", "{n:page title|page titles} above the {limit}-character guidance band"),
        ("tseo1.description_short", "{n#} meta description(s) below the {limit#}-character guidance band",
         "{n:meta description|meta descriptions} below the {limit}-character guidance band"),
        ("tseo1.description_long", "{n#} meta description(s) above the {limit#}-character guidance band",
         "{n:meta description|meta descriptions} above the {limit}-character guidance band"),
        ("tseo1.heading_jumps", "{n#} heading level jump(s) in the page structure", "{n:heading level jump|heading level jumps} in the page structure"),
        # A jump onto one heading most pages carry (a footer's column title), reported once for the whole site.
        ("shared.heading_jump", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: heading “{text}” (H{to#}) comes after an H{before#}, skipping a level (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: heading “{text}” (H{to}) comes after an H{before}, skipping a level (on {n:page|pages}{section})"),
        ("shared.heading_jump_varied", "{label~:Shared header/footer|Repeated block|“[^”]+” block}: heading “{text}” (H{to#}) comes after a higher-level heading, skipping levels (on {n#} page(s){section~:(?: of /[^/ ]+/)?})",
         "{label}: heading “{text}” (H{to}) comes after a higher-level heading, skipping levels (on {n:page|pages}{section})"),
    ),
}
# Title keys kept for reports saved by an earlier engine: nothing in today's source writes them.
SAVED_ONLY = frozenset({"str19.lead_nowhere", "str7.alt_missing", "idx2.no_redirect", "idx8.title", "idx6.other_site", "idx5.bad_share",
                        "idx8.merged", "idx5.malformed", "str19.controls", "str7.formats", "str7.format_unassessed",
                        # Before review CR-28 the share's first number counted IDX-1's pages too.
                        "idx5.not_live.idx1", "idx5.not_live.sampled.idx1",
                        # Since review G13 a missing twitter:card is an STR-10 observation, not a finding.
                        "str10.no_twitter"})
# Shared report qualification is part of the engine's output vocabulary.
for _cid, _rows in {
 'IDX-6': [('judgment.external.mixed','{n#} external destination(s) have mixed HEAD/GET evidence; review request context','{n:external destination has|external destinations have} mixed HEAD/GET evidence; review request context'),('judgment.head','{n#} external destination(s) have HEAD errors; GET navigation is unverified','HEAD errors at {n:external destination|external destinations}; GET navigation is unverified')],
 'IDX-1': [('judgment.empty.repeated','{n#} URL(s) returned repeated empty GET responses in the tested client','{n:URL|URLs} returned repeated empty GET responses in the tested client'),('judgment.empty.single','{n#} URL(s) returned an empty response; persistence is unconfirmed','{n:URL|URLs} returned an empty response; persistence is unconfirmed')],
 'IDX-5': [('judgment.sitemap.overlap','{n#} sitemap URL observation(s) require differentiated review ({checked#} checked); {same#} already have IDX-1 retrieval evidence','{n:sitemap URL observation requires|sitemap URL observations require} differentiated review ({checked} checked); {same} already have IDX-1 retrieval evidence'),('judgment.sitemap','{n#} sitemap URL observation(s) require differentiated review ({checked} checked)','{n:sitemap URL observation requires|sitemap URL observations require} differentiated review ({checked} checked)')],
 'STR-14': [('judgment.generic.identity','{n#} generic-text link occurrence(s) recorded; purpose requires contextual review — {identity}','{n:generic-text link occurrence|generic-text link occurrences} recorded; purpose requires contextual review — {identity}'),('judgment.generic','{n#} generic-text link occurrence(s) recorded; purpose requires contextual review','{n:generic-text link occurrence|generic-text link occurrences} recorded; purpose requires contextual review')],
 'STR-7': [('str7.format_unassessed','Image-format markup observations; WebP or AVIF delivery is unassessed','Image-format markup observations; WebP or AVIF delivery is unassessed'),('str7.format_references','{modern#} of {images#} image occurrence(s) reference WebP or AVIF in markup; delivery assessed separately','{modern} of {images:image occurrence|image occurrences} reference WebP or AVIF in markup; delivery assessed separately'),('str7.placeholder','{n#} image(s) on {pages#} page(s) have likely placeholder alt text','{n:Image|Images} with likely placeholder alt text: {n}; affected pages: {pages}')],
 'RND-4': [('rnd4.unnamed','{n#} iframe(s) lack an accessible name on {pages#} page(s)','{n:iframe lacks|iframes lack} an accessible name on {pages:page|pages}')],
 'STR-2': [('judgment.heading.home','The homepage has no meaningful <h1> text','The homepage has no meaningful <h1> text'),('judgment.heading.pages','{n#} page(s) have no meaningful <h1> text','{n:page has|pages have} no meaningful <h1> text')],
}.items():
    _TITLES[_cid] = (*_TITLES.get(_cid,()), *_rows)

TITLES: dict[str, tuple[tuple[str, str], ...]] = {check: tuple((key, Frame(key, frame).regex.pattern) for key, frame, _ in rows)
                                                 for check, rows in _TITLES.items()}
ENGLISH: dict[str, str] = {key: english for rows in _TITLES.values() for key, _, english in rows}
_TITLE_FRAMES = {check: _frames(rows) for check, rows in _TITLES.items()}

# -- fixes, expected results and notes the engine builds at run time (a fixed sentence needs only its JSON entry) ------
FIX_PATTERNS = _frames((
    ("acc2.search", "If {engines} should be able to find and cite these pages, remove or narrow the rule on line {line#} for these user agents. "
                    "If blocking them is deliberate, mark it as intended."),
    ("acc2.live", "Live fetchers may not follow robots.txt at all (see ACC-4 for what they actually receive). If you want users' AI assistants "
                  "to read these pages, remove the rule on line {line#}."),
    ("acc2.training", "These user agents serve: {engines}. If blocking them matches your policy, record it in the declared bot policy; "
                      "otherwise change line {line#}."),
    # Reports saved before the fix took its words from the registry (B14).
    ("acc2.training_saved", "This affects model training, not live AI answers. If it matches your policy, record it in the declared bot policy; "
                            "otherwise change line {line#}."),
    ("acc2.mismatch", "Add Disallow rules for these user agents, or change the declared {role~}-bot policy."),
    ("acc2.precedence", "Under RFC 9309 a bot obeys only its most specific group. If line {line#} should also apply to {tokens}, repeat it inside their group."),
    ("acc9.allow", "If you own this site: allow the user agent \"{agent}\" in the firewall or bot-protection rules and run the audit again; verify "
                   "ownership so ACC-4 can test what AI crawlers receive; or try again later if this was a rate limit. Then check the same rules "
                   "for the AI crawlers you want to reach you (OAI-SearchBot, ClaudeBot, PerplexityBot and others)."),
    ("acc9.allow_rate_429", "Check the bot and rate-limit rules in {who~:.+?} that answer page requests with 429: allow the user agent "
                            "\"{agent}\" and run the audit again. AI crawlers may get the same treatment: check the same rules for "
                            "OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you."),
    ("acc9.allow_429", "Check the bot and rate-limit rules in {who~:.+?} that answer page requests with 429 while robots.txt and the sitemap "
                       "are served: allow the user agent \"{agent}\" and run the audit again. AI crawlers may get the same treatment: check "
                       "the same rules for OAI-SearchBot, ClaudeBot, PerplexityBot and the others you want to reach you."),
    ("str6.set", "Set {kind~:.+?} from the content's real last edit."),
    ("str6.set", "Verify {kind~:.+?} against actual edit records; change date generation only if inaccurate."),
    ("str10.add_description", "Add meta description."),
    ("str10.add", "Add {tag:(?:og|twitter):[\\w:]+}."),
    ("str10.give", "Give {tag:(?:og|twitter):[\\w:]+} a value."),
    ("str18.example", "Put the brand name in the homepage <title>, for example “{name} | what you do”."),
))
EXPECTED_PATTERNS = _frames((
    ("acc2.declared", "robots.txt blocks {role~} bots, as declared"),
    ("acc7.below", "Crawl-delay below {seconds#}s for bots you want refreshing your pages"),
    ("idx2.validity", "more than {days#} days of validity left"),
    ("prf1.under", "HTML returned in under {seconds#} s"),
    ("prf2.under", "under {share%} of fetches fail"),
    ("str4.matches", "the structured-data {field~:.+?} matches what the page shows"),
    ("str10.present_description", "meta description present"),
    ("str10.present", "{tag:(?:og|twitter):[\\w:]+} present"),
    ("str10.has_value", "{tag:(?:og|twitter):[\\w:]+} has a value"),
    ("str11.same", "every description of one entity gives the same {field}"),
    ("tseo1.title", "A page-specific title around {low#}–{high#} characters, where that fits the page."),
    ("tseo1.title_concise", "A concise, page-specific title around {low#}–{high#} characters, where that fits."),
    ("tseo1.description", "A useful page summary around {low#}–{high#} characters, where practical."),
    ("tseo1.description_concise", "A concise page summary around {low#}–{high#} characters, where practical."),
))
NOTE_PATTERNS = _frames((
    ("source.firecrawl", "Source: Firecrawl"),
    ("source.firecrawl.dot", "Source: Firecrawl."),
    ("source.firecrawl.blocked", "Source: Firecrawl (Maya's crawler was blocked)"),
    ("source.firecrawl.blocked.dot", "Source: Firecrawl (Maya's crawler was blocked)."),
    ("source.firecrawl.render", "Source: Firecrawl rendered these pages (the local browser could not start)"),
    ("source.firecrawl.render.dot", "Source: Firecrawl rendered these pages (the local browser could not start)."),
    ("acc1.exclusions", "{n#} key page(s) match an intent-marking pattern but are not covered: pattern markings never cover key pages (spec §2.5)."),
    ("acc2.private", "Reported as Info: the blocked path is a private or technical one ({matched}), which sites normally keep bots out of, and none "
                     "of the blocked URLs is the homepage, a key page or listed in the sitemap."),
    ("acc4.unconfirmed", "Not confirmed: the probe cap was reached before this difference could be retried ({retries#} retries configured). The response "
                         "itself is Verified; that it is a lasting block rather than a transient one is Estimated. Re-run with a larger probe cap "
                         "(CrawlConfig.max_probe_requests) to confirm."),
    ("acc5.window", "Only IP-verified requests count; window {start} to {end}."),
    ("acc6.also_blocked", "{token} is also blocked. That is reported once, as an ACC-2 finding, not repeated here."),
    ("acc7.effect", "Estimated effect: at most about {fetches#} fetches per day per bot, assuming the bot honors Crawl-delay (it is non-standard; not all do)."),
    ("idx1.timeout_basis", "Inferred: assumes answer engines give up within {seconds#} s. Vendors do not document their fetch timeouts."),
    ("idx1.soft404.not_followed", "One request was made, to a random address generated for this audit. the redirect was recorded, not followed (one request only)"),
    ("idx1.soft404.one", "One request was made, to a random address generated for this audit. "),
    ("idx3.not_followed", "The redirect and its target are Verified. The target was not fetched: the audit stays on {origin}, so nothing is known "
                          "about the page a visitor ends on."),
    ("idx3.rechecked", "Verified: the URL looped in the crawl and on each of {n#} further request(s) made after it."),
    ("idx6.requested", "Verified: the link's path is the path of a page found on this site, and the other address was requested once and "
                       "returned {status#}. Inferred: that the link was meant to be internal."),
    ("idx5.estimate", "{n#} listed URL(s) were not fetched (page cap or blocked), so the share is an estimate from the URLs that were."),
    ("idx5.sample", "The sitemap lists {n#} URLs; {checked#} were checked ({crawled#} read by the crawl, {light#} with one light request each, "
                    "a sample spread over the site's sections). The share is of the URLs checked and is an estimate for the whole sitemap."),
    ("idx5.sample.files", "The sitemap lists {n#} URLs; {checked#} were checked ({crawled#} read by the crawl, {light#} with one light request "
                          "each, a sample spread evenly over {files#} sitemap file(s)). The share is of the URLs checked and is an "
                          "estimate for the whole sitemap."),
    ("idx5.not_checked", "{n#} listed URL(s) were not checked ({why~:.+?}), so the share is an estimate from the URLs that were."),
    ("idx5.guess", "“{fragment}” is probably “{word}”; the sitemap is probably not written in UTF-8."),
    ("acc8.first_line", "First line: “{line}”."),
    ("prf1.samples", "Estimated: 'slow' generalizes from {samples#}+ samples; each sample is Verified. With 3 samples the p90 is the slowest sample."),
    ("prf1.threshold", "The {seconds#} s threshold is policy (spec default: 1.5 s)."),
    ("rnd1.delta", "This text was absent from the initial HTML response and appeared only after client-side rendering. Each page's content_delta quotes that text."),
    ("str1.same_start", "The titles are different in full; that their first {chars#} characters are the same is Verified. Search results and source "
                        "cards show about 50 to 60 characters of a title."),
    ("str6.thresholds", "Thresholds ({pages#} pages, {share%}) are uncalibrated guesses."),
    ("str12.language", "Estimated: each passage of main content is assigned a language from stopword counts; the page is reported when at least "
                       "{share%} of the assigned words are not in the declared language."),
    ("str12.headings", "Estimated: a heading is assigned a language from stopwords, and a page is reported at {headings#} or more headings in one "
                       "other language. Its body text is mostly in the declared language, or it would be in the finding above."),
    ("str13.rendered", "On {n#} of these page(s) the marker is still there after the page was rendered in a browser: a reader sees it."),
    # ACC-9, when the pages were then read through Firecrawl (maya_audit.firecrawl.reader.note_the_challenge)
    ("acc9.reader.measured.counted", "Measured: {who~:.+?} answered Maya's own requests on {hit#} of {asked#} request(s). Firecrawl then read {read#} page(s); "
                                     "that shows the content is readable through that reader, not that any crawler is let in."),
    ("acc9.reader.measured", "Measured: {who~:.+?} answered Maya's own requests. Firecrawl then read {read#} page(s); "
                             "that shows the content is readable through that reader, not that any crawler is let in."),
    # A finding that rests on an archived copy names the copies (maya_audit.archives)
    ("archive.copy", "Source: {name:Wayback Machine|Common Crawl}; archived/indexed copy, date {date}; the live site may differ"),
))

# -- the outcome sentence (maya_audit.report.run_outcome), by its frames ----------------------------------------------
_CHALLENGED = "Maya's direct crawler was challenged. Genuine AI-crawler access was not measured."
_NO_ANSWER = ("Maya's own requests got no answer on this computer, so direct access was not measured. Genuine AI-crawler access was not measured.")
OUTCOMES = _frames((
    ("outcome.complete", "The audit completed: every discovered page was crawled and every check ran."),
    # CR-07: a complete audit claims "every check ran" only when it did (maya_audit.report.COMPLETE*).
    ("outcome.complete.crawled", "The audit completed: every discovered page was crawled."),
    ("outcome.complete.not_run", "The audit completed: every discovered page was crawled; {n#} check{cs:s?} could not run (see Coverage and checks)."),
    ("outcome.single", "Single-page audit: the page was read and every check that applies to one page ran. Other pages of the site "
                       "were not checked."),
    ("outcome.single.reader.challenged", "Single-page audit: the page was read through Firecrawl. " + _CHALLENGED + " Other pages of the site "
                                         "were not checked; some direct-request checks could not be completed."),
    ("outcome.single.reader.no_answer", "Single-page audit: the page was read through Firecrawl. " + _NO_ANSWER + " Other pages of the site "
                                        "were not checked; some direct-request checks could not be completed."),
    ("outcome.incomplete", "The audit finished but is incomplete ({why~:.+}). Findings cover only what was fetched."),
    ("outcome.partial_page_cap", "Partial audit: {read#} of {total#} known pages were read (the page limit of {cap#}). Findings cover only the pages read."),
    ("outcome.not_reached", "The audit could not reach the site from this computer: {detail~:.+}. Nothing is reported against the site. "
                            "Run the audit again when the connection works."),
    ("outcome.degraded", "The audit could not read the site properly: {why~:.+}."),
    # DECISIONS 295: Maya's crawler stopped by 429s, pages read through Firecrawl.
    ("outcome.blocked_429.read.gaps", "Maya's crawler was blocked (429 on pages); {n#} page(s) were read through Firecrawl; {gaps~:.+}. "
                                      "Genuine AI-crawler access was not measured. Findings cover only the pages read."),
    ("outcome.blocked_429.read", "Maya's crawler was blocked (429 on pages); {n#} page(s) were read through Firecrawl. "
                                 "Genuine AI-crawler access was not measured. Findings cover only the pages read."),
    ("outcome.reader.partial.challenged", "The audit finished with partial coverage: {n#} page(s) were read through Firecrawl; {gaps~:.+}. "
                                          + _CHALLENGED + " Findings cover only the pages read."),
    ("outcome.reader.partial.no_answer", "The audit finished with partial coverage: {n#} page(s) were read through Firecrawl; {gaps~:.+}. "
                                         + _NO_ANSWER + " Findings cover only the pages read."),
    ("outcome.reader.complete.challenged", "We read {n#} page(s) through Firecrawl: every address found from the homepage and those pages. "
                                           + _CHALLENGED + " The report covers these {m#} page(s); some direct-request checks could not be completed."),
    ("outcome.reader.complete.no_answer", "We read {n#} page(s) through Firecrawl: every address found from the homepage and those pages. "
                                          + _NO_ANSWER + " The report covers these {m#} page(s); some direct-request checks could not be completed."),
))

# -- pieces of a sentence that are themselves sentences or words: why a run stopped, why coverage is partial, labels ----
# Tried in order after the exact `terms` of the language file. A list ("a; b", "a / b", "a, b") is translated piece by
# piece. These are also the frames of `audit_status.content_coverage.reasons` (maya_audit.report.reader_gaps).
TERM_PATTERNS = _frames((
    # labels inside titles
    # what a shared element is called, and the section its pages are in (maya_audit.shared_elements, DECISIONS 198)
    ("shared.block", "“{block:[^”]+}” block"),
    ("shared.section", "of /{section:[^/ ]+}/"),
    ("blocker.named", "{name:[^()]+} ({kind~})"),
    ("blocker.firewall", "the site or its firewall (HTTP {status:\\w+}, access denied)"),
    ("acc6.partly", "partly blocked ({blocked#}/{total#} sampled URLs)"),
    ("idx2.http_answer", "http:// answered {status:\\w+} without redirecting to https://"),
    ("idx2.http_elsewhere", "http:// redirects to {location:\\S+}, not to https://"),
    ("str6.identical_date", "one identical date ({date})"),
    ("str12.written", "declared {declared~}, written mostly in {language~}"),
    ("str12.headings", "declared {declared~}, headings in {language~}"),
    ("str13.more", "and {more#} more"),
    # why the crawl stopped (crawl.stop_reason: crawl.stop_detail)
    ("stop.coded", "{stop~:page_cap|time_limit|rate_limit|error|robots_disallowed|network_problem|stopped|exhausted}: {detail~:.+}"),
    ("stop.page_cap", "page cap of {cap#} reached"),
    ("fc.request_allowance", "the Firecrawl request allowance of {total#} for this audit is used ({pages#} plus one bootstrap reserve). No request was sent."),
    ("stop.fetch_budget", "fetch budget of {requests#} requests (pages plus redirects) reached"),
    ("stop.time_limit", "time limit of {seconds#}s reached"),
    ("stop.time_share", "the crawl used its share ({share%}) of the {seconds#}s time limit; the rest is kept for the checks that run after it"),
    ("stop.cooldown", "spent {waited#}s waiting out rate limits, over the {allowed#}s allowed; stopped requesting pages"),
    ("stop.blocked_429", "blocked for Maya's crawler (429 on pages): {detail~:.+}"),
    ("stop.retry_after", "{url:https?://\\S+} asked Maya to wait {wait#}s (Retry-After), longer than the {allowed#}s allowed; stopped requesting pages"),
    ("stop.consecutive", "{count#} consecutive rate-limited responses"),
    ("stop.start_failed", "start URL could not be fetched: {error}"),
    ("stop.robots_status", "robots.txt returned {status#}; RFC 9309: assume complete disallow"),
    ("stop.robots_unexpected", "robots.txt returned unexpected status {status#} after redirects; treated as unreachable"),
    ("stop.robots_local", "robots.txt was not checked: network problem on this computer ({error}). This says nothing about the site; "
                          "Maya's own crawler requested no page"),
    ("stop.robots_no_host", "robots.txt was not checked: the address does not exist ({error}); no page was requested"),
    ("stop.robots_refused", "robots.txt was not requested: the address is not a public one ({error}); no page was requested"),
    ("stop.robots_no_answer", "robots.txt was not checked: no answer reached this computer ({error}). Whether the site or the connection "
                              "failed is not known; Maya's own crawler requested no page"),
    # why the audit is degraded
    ("why.gates", "{gates:[A-Z]+-\\d+(?:, [A-Z]+-\\d+)*} reported degradation, blocking, or an integrity violation"),
    ("why.stopped_early", "the crawl stopped early ({stop~:\\w+}: {detail~:.+})"),
    ("why.collectors", "{count#} data collector(s) failed"),
    ("why.not_read", "{count#} discovered URL(s) were not read"),
    ("why.not_fetched", "{count#} discovered URL(s) were not fetched"),
    # why coverage is partial
    ("gap.crawl_stopped", "Maya's crawl stopped: {stop~:\\w+} ({detail~:.+})"),
    ("gap.reading_stopped", "reading stopped early ({why~:.+})"),
    # H19: a provider's error said by its status (maya_audit.report.provider_reason); its own text stays in the evidence.
    ("gap.reader_http", "{reason~:the page reader timed out|the page reader's own rate limit was reached|the page reader's account has no credit|"
                        "the page reader refused the request|the page reader could not load the page|the page reader returned no document} (HTTP {status#})"),
    ("gap.last_unreadable", "the last {count#} pages asked for came back unreadable, so no more were requested"),
    ("gap.first_unreadable", "the first {count#} pages asked for came back unreadable, so no more were requested"),
    # One sentence for a reading that used its request allowance (maya_audit.report.allowance_sentence), and the
    # addresses left out of the "not read" figure. The engine writes "1 page" or "43 pages" itself.
    ("gap.allowance", "the page reader used all {n#} page requests this audit allows and read {m#} page{ps:s?}; {k#} request{rs:s?} led to pages already read or to missing pages"),
    ("gap.allowance.none", "the page reader used all {n#} page requests this audit allows and read {m#} page{ps:s?}"),
    ("gap.left_out", "+{n#} address{es:(?:es)?} left out: disallowed by robots.txt or not a page"),
    ("gap.remaining.cap", "{count#} more discovered URL(s) remain unchecked (the page cap of {cap#} was reached)"),
    ("gap.remaining.because", "{count#} more discovered URL(s) remain unchecked ({because~:the time limit was reached|the audit was stopped|the reader kept getting unreadable answers|a credit or request limit was reached})"),
    ("gap.remaining", "{count#} more discovered URL(s) remain unchecked"),
    # DECISIONS 294: the pages the time limit left to the reader, and its measured pace.
    ("gap.time.measured", "{count#} page(s) were not read for lack of time (the page reader measured {seconds#} s a page)"),
    ("gap.time", "{count#} page(s) were not read for lack of time"),
    ("gap.no_document.why", "{count#} requested URL(s) gave no readable document ({why~:.+})"),
    ("gap.no_document", "{count#} requested URL(s) gave no readable document"),
    ("gap.cause", "{count#} {cause~:reader challenged|redirect to another site|redirect within the site|empty document|error status|provider could not load|timeout or no answer|credit or request limit|provider refused}"),
    ("gap.key_pages", "{count#} key page(s) were not read"),
    # DECISIONS 295: pages whose Firecrawl call timed out, asked for once more, then skipped.
    ("gap.timeouts", "Firecrawl: {read#} page(s) read, {retried#} retried after a timeout, {skipped#} skipped"),
)) + _frames(_TERM_ROWS)  # and the pieces of the sentences in sentences.py
_SEPARATORS = ("; ", " / ", ", ")


def _load() -> dict[str, dict[str, dict[str, str]]]:
    """locales/findings/<language>.json: one section per kind of sentence, each a table of key or English text ->
    translation. An entry beginning with "_" (the review mark) is not a sentence."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    folder = strings.LOCALES / "findings"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(table, dict):
            out[path.stem] = {section: {key: value for key, value in rows.items() if isinstance(value, str)}
                              for section, rows in table.items() if isinstance(rows, dict)}
    return out


TABLES = _load()
SECTIONS = ("titles", "fixes", "fix_patterns", "expected", "expected_patterns", "notes", "note_patterns", "outcomes", "terms", "term_patterns",
            "labels", "label_patterns", "lines", "line_patterns", "examples")


def _language(language: str | None) -> str:
    return language or strings.current_language()


def _table(language: str, section: str) -> dict[str, str]:
    return (TABLES.get(language) or {}).get(section) or {}


def _percent(value: str, language: str) -> str:
    return "%" + value[:-1] if language == "tr" and value.endswith("%") else value  # Turkish writes %27


def _translated(frame: Frame, values: dict[str, Any], template: str | None, language: str) -> str | None:
    """`template` filled with a frame's values, each put into `language`: None when a piece has no translation."""
    if template is None:
        return None
    out = dict(values)
    for name, kind in frame.kinds.items():
        value = values[name]
        if kind in ("~", "?") and value != "":
            found = term(value, language, name)
            if found is None and len(value.split()) > 3:  # a piece that is itself a sentence (a gate's summary inside a reason)
                found = _line(value.strip(), language)
            if found is None:
                return None
            value = found
        elif kind == "%":
            value = _percent(value, language)
        out[name] = value
    try:
        return fill(template, out)
    except (KeyError, IndexError, ValueError):
        return None


def _whole_term(core: str, language: str, hole: str | None = None) -> str | None:
    # A word may need another form in another place ("blocked": what happened to a request, or the state of a token):
    # an entry "<hole>:<word>" is for that hole only.
    exact = _table(language, "terms").get(f"{hole}:{core}") if hole else None
    if exact is None:
        exact = _table(language, "terms").get(core)
    if exact is not None:
        return exact
    if _CODE.fullmatch(core):
        return core
    for frame in TERM_PATTERNS:
        values = frame.values(core)
        if values is not None:
            found = _translated(frame, values, _table(language, "term_patterns").get(frame.key), language)
            if found is not None:
                return found
    return None


def term(value: str, language: str | None = None, hole: str | None = None) -> str | None:
    """A word, a phrase or a list of them inside a sentence, in `language`; None when any piece has no translation.
    `hole` is the name of the hole it fills, for a word that is translated differently there."""
    language = _language(language)
    lead = value[:len(value) - len(value.lstrip())]
    core = value.strip()
    if not core:
        return value
    whole = _whole_term(core, language, hole)
    if whole is not None:
        return lead + whole
    for separator in _SEPARATORS:
        parts = core.split(separator)
        if len(parts) < 2:
            continue
        out, at = [], 0
        while at < len(parts):
            # The longest run of pieces that is one sentence: a piece may hold the separator itself.
            for end in range(len(parts), at, -1):
                if at == 0 and end == len(parts):
                    continue  # the whole was tried above
                piece = separator.join(parts[at:end])
                found = term(piece, language, hole) if end - at == 1 else _whole_term(piece, language, hole)
                if found is not None:
                    out.append(found)
                    at = end
                    break
            else:
                break
        if at == len(parts):
            return lead + separator.join(out)
    return None


def _by_pattern(frames: tuple[Frame, ...], section: str, text: str, language: str) -> str | None:
    for frame in frames:
        values = frame.values(text)
        if values is not None:
            found = _translated(frame, values, _table(language, section).get(frame.key), language)
            if found is not None:
                return found
    return None


def _capital(text: str, language: str) -> str:
    """`text` with a capital first letter. Turkish capitalises i as İ and ı as I."""
    first = text[:1]
    if not first.islower():
        return text
    return ({"i": "İ", "ı": "I"}.get(first, first.upper()) if language == "tr" else first.upper()) + text[1:]


def _marked(text: str, language: str) -> str:
    return text + MARKS.get(language, "")



def title_key(check_id: str, text: str) -> list[str]:
    """The keys of this check's title frames that match `text` (for the coverage test: exactly one)."""
    return [frame.key for frame in _TITLE_FRAMES.get(check_id, ()) if frame.values(text) is not None]


def title(check_id: str, text: str, language: str | None = None) -> tuple[str, bool]:
    """A finding's title as it is shown, and whether it was put into the reader's language.

    English: through the English display template ("1 page is ..."), or unchanged when no frame matches.
    Another language: the translation, or the engine's English followed by the mark."""
    language = _language(language)
    if text == 'Source conclusion unassessed: evidence unavailable':
        return ('Kaynak yargısı değerlendirilemedi: kanıt mevcut değil' if language=='tr' else text), True
    for frame in _TITLE_FRAMES.get(check_id, ()):

        values = frame.values(text or "")
        if values is None:
            continue
        if language == strings.DEFAULT_LANGUAGE:
            try:
                return fill(ENGLISH[frame.key], values), True
            except (KeyError, IndexError, ValueError):
                return text, True
        template = _table(language, "titles").get(frame.key)
        found = _translated(frame, values, template, language)
        if found is not None:
            # A title that begins with a translated label ("arama botlarının ...") begins with a capital. One that
            # begins with a value put back unchanged ("llms.txt") keeps it as it is.
            first = re.match(r"\{(\w+)\}", template)
            return (_capital(found, language) if first and frame.kinds.get(first.group(1)) in ("~", "?") else found), True
    if language == strings.DEFAULT_LANGUAGE or not text:
        return english(text), True
    return _marked(text, language), False


def _sentence(text: str, section: str, patterns: str, frames: tuple[Frame, ...], language: str | None) -> tuple[str, bool]:
    language = _language(language)
    if language == strings.DEFAULT_LANGUAGE or not (text or "").strip():
        return english(text), True  # as the engine wrote it, with "1 page(s)" said as "1 page"
    found = _table(language, section).get(text) or _table(language, section).get(text.strip())
    if found is None:
        found = _by_pattern(frames, patterns, text, language)
    return (found, True) if found is not None else (_marked(text, language), False)


# Display corrections for historical saved advice; observations and severities stay intact.
SAVED_ADVICE = {
    ('Make the address answer without a cookie: the redirect sets a cookie and sends the visitor back to '
     'the same address, and crawlers keep no cookies, so they go round for ever.'): ('Compare the logged cookie-less and cookie-enabled requests. If public access is intended, '
         'investigate why their responses differ before changing server configuration.'),
    ('Search and AI crawlers do not keep cookies. An address that only loads once a cookie is set never '
     'loads for them.'): ("Maya observed different outcomes with and without the site's cookie. Other clients and real search "
         'or AI crawlers were not tested.'),
    ('Fix the redirect rules so each chain ends at a real 200 page.'): ('Inspect the server request logs for these times and client, identify the cause of the observed '
         'cycle, then retest with and without cookies.'),
    ('Remove the rule that redirects a URL to itself. The page loads, but crawlers waste requests.'): ('Compare the successful and cyclic requests at the recorded times. Identify the cause before changing'
         ' configuration; then repeat the same client checks.'),
    ('Request these URLs again by hand. If one still redirects to itself, fix the redirect rules so it '
     'ends at a real 200 page.'): ('Complete the missing native and cookie-enabled checks. Compare request logs before selecting a '
         'remedy; the available observations do not establish persistence.'),
    ('Use the page\'s topic as the link text ("Şizofreni tedavisi" instead of "Devamı"), or add the topic '
     'to the link with a visually hidden label.'): ("Use the linked page's actual topic as the link text, or add that topic with a visually hidden label."
         ' Check the destination before writing it.'),
    ('Remove the invisible characters (zero-width spaces, soft hyphens), usually pasted in from a word '
     'processor or a design tool. Inside a word they make a search engine read it as two words.'): ('Review the quoted invisible characters in context. Remove accidental characters, preserving '
         'intentional language and formatting. Their presence alone does not establish how a search engine '
         'tokenizes or ranks the page.'),
    ("Mark the page's own content with one <main> element, so the menu, footer and sidebars sit outside "
     'it. This is page structure: no JavaScript change is needed.'): ('Inspect the measured content region and repeated navigation. A low text ratio does not establish '
         'that main is missing. Adjust existing boundaries or content only where the saved page supports it.'),
    ('A Last-Modified header set minutes to hours before each request (for example when a CDN or page '
     "cache refreshes) is a cache time, not the content's change date."): ('Same-day Last-Modified headers do not establish incorrect edit dates or a cache cause. Compare with '
         'publication records before changing date generation.'),
    ('Verified: the one response the crawl has for each URL redirects in a loop. Inferred: that it does so'
     ' every time. One response does not show that, so this is not reported as a blocker.'): ('The native crawl observed a cycle. Persistence is unknown because the required repeated and '
         'cookie-enabled verification did not complete. This is not reported as a blocker.'),
}


def fix(text: str, language: str | None = None) -> tuple[str, bool]:
    """A finding's "What to do", or a review item's suggested action."""
    text = SAVED_ADVICE.get(text, text)
    match = re.fullmatch(r"(?:Set (.+?) from the content's real last edit\.|Verify (.+?) against actual edit records; change date generation only if inaccurate\.)", text)
    if match:
        kind = match.group(1) or match.group(2)
        return ((f"{kind} değerini gerçek düzenleme kayıtlarıyla doğrulayın; tarih üretimini yalnızca yanlışsa değiştirin."
                 if _language(language) == "tr" else
                 f"Verify {kind} against actual edit records; change date generation only if inaccurate."), True)
    return _sentence(text, "fixes", "fix_patterns", FIX_PATTERNS, language)


def expected(text: str, language: str | None = None) -> tuple[str, bool]:
    """A finding's expected result, or a review item's "why look"."""
    return _sentence(text, "expected", "expected_patterns", EXPECTED_PATTERNS, language)


def note(text: str, language: str | None = None) -> tuple[str, bool]:
    """A finding's note. A note that is one of the engine's other sentences (a gate's caveat, what a probe saw) is
    worded as that sentence."""
    text = SAVED_ADVICE.get(text, text)
    shown, ok = _sentence(text, "notes", "note_patterns", NOTE_PATTERNS, language)
    if not ok:
        found = _line(text.strip(), _language(language))
        if found is not None:
            return found, True
    return shown, ok


def outcome(text: str | None, language: str | None = None) -> tuple[str | None, bool]:
    """The run's outcome sentence (stored with the audit). English: as the engine wrote it, with "3 page(s)" said as "3 pages"."""
    language = _language(language)
    if language == strings.DEFAULT_LANGUAGE or not (text or "").strip():
        return english(text), True
    found = _by_pattern(OUTCOMES, "outcomes", text, language)
    return (found, True) if found is not None else (_marked(text, language), False)


def reason(text: str, language: str | None = None) -> tuple[str, bool]:
    """One reason coverage is partial (`audit_status.content_coverage.reasons`), or one stop detail."""
    language = _language(language)
    if language == strings.DEFAULT_LANGUAGE or not (text or "").strip():
        return english(text), True
    found = term(text, language)
    return (found, True) if found is not None else (_marked(text, language), False)


def first_sentence(text: str) -> str:
    found = re.match(r"(.+?[.!?])(\s|$)", (text or "").strip(), re.DOTALL)
    return (found.group(1) if found else (text or "").strip())[:300]


# -- "1 page(s)" as English says it ---------------------------------------------------------------------------------------
_VERBS = {"were": "was", "are": "is", "have": "has", "do": "does", "use": "uses", "carry": "carries", "rank": "ranks", "remain": "remains",
          "link": "links", "exceed": "exceeds", "consist": "consists"}
_COUNTED = re.compile(r"(?P<noun>[A-Za-z@:<>-]+)\((?P<end>s|es|ies)\)(?:(?P<between>(?: [a-z-]+){0,3}?) (?P<verb>" + "|".join(_VERBS) + r")\b)?")
_NUMBER_BEFORE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\+?(?:[^\d.;:()]| of | to )*$")
_SECOND_OF_TWO = re.compile(r"\) and \d[\d,.]* (?:[A-Za-z-]+ ){0,3}$")


def english(text: str) -> str:
    """The engine's English with every "(s)" resolved: "1 page(s) were read" is "1 page was read", "3 URL(s)" is
    "3 URLs", and a noun with no number before it in its clause ("the missing page(s)") is said as a plural."""
    if not text or "(" not in text:
        return text

    def said(found: re.Match) -> str:
        noun, end = found.group("noun"), found.group("end")
        if noun in ("http", "https"):
            return found.group(0)  # "http(s)://" is an address, not a count
        before = _NUMBER_BEFORE.search(text[max(0, found.start() - 80):found.start()])
        one = bool(before) and before.group(1) == "1"
        said_noun = noun if one else noun[:-1] + "ies" if end == "ies" else noun + end
        if found.group("verb") is None:
            return said_noun
        verb = found.group("verb")
        if one and not _SECOND_OF_TWO.search(text[max(0, found.start() - 60):found.start()]):
            verb = _VERBS[verb]  # "3 templates and 1 key page were": two things, so the verb stays plural
        return f"{said_noun}{found.group('between')} {verb}"

    return _COUNTED.sub(said, text)


# -- labels and lines: check titles and summaries, coverage parts and reasons, gates, the data and reader panels ---------
LABEL_PATTERNS = _frames(_LABEL_ROWS)
LINE_PATTERNS = _frames(_LINE_ROWS)
LINE_PATTERNS = (*LINE_PATTERNS, Frame('evidence.host.incomplete', 'Incomplete host assessments: {reasons}.'))
LINE_PATTERNS = (*LINE_PATTERNS, Frame('evidence.image.scope', 'Retained image-format scope: {occ#} occurrences, {resources#} resources; {assessed#} resources with recorded response MIME, {unassessed#} without it. Unobserved delivery alternatives remain unassessed.'), Frame('evidence.image.mime', 'Recorded response MIME observations: {formats}. Byte sizes, quality and negotiation may be unavailable.'))
LINE_PATTERNS = (*LINE_PATTERNS, Frame('evidence.sitemap.scope', 'Sitemap assessment: {checked#} URL(s) checked; {unassessed#} not assessed. Includes native responses and lightweight probes; content reads are separate.'))
LINE_PATTERNS = (*LINE_PATTERNS, Frame('judgment.image.coverage', '{records#} saved role records represent {instances#} distinct page/element/source/time instances; {images#} source image URLs. Purpose, displayed CSS/pixels and equivalent text require review; neither a pass nor a confirmed missing description.'))
_SENTENCE_END = re.compile(r"(?<=[.!?]) +")
_JOINED = (" | ", ", ")


def _held(frame: Frame, values: dict[str, Any], template: str | None, language: str, check_id: str | None) -> str | None:
    """A label or line frame's values put into `language`. A "~" hole may hold a word (`term`), a label, a sentence
    or, under the name `finding`, the title of one of this check's findings."""
    if template is None:
        return None
    out = dict(values)
    for name, kind in frame.kinds.items():
        value = values[name]
        if kind in ("~", "?") and value != "":
            lead = value[:len(value) - len(value.lstrip())]
            if name.startswith("finding"):
                shown, ok = title(check_id or "", value.strip(), language)
                found = shown if ok and check_id else None
            else:
                found = term(value.strip(), language, name)
                if found is None:
                    found = _label(value.strip(), language, check_id)
                if found is None:
                    found = _line(value.strip(), language, check_id)
            if found is None:
                return None
            value = lead + found
        elif kind == "%":
            value = _percent(value, language)
        out[name] = value
    try:
        return fill(template, out)
    except (KeyError, IndexError, ValueError):
        return None


@lru_cache(maxsize=4096)
def _label(text: str, language: str, check_id: str | None = None) -> str | None:
    exact = _table(language, "labels").get(text)
    if exact is not None:
        return exact
    for frame in LABEL_PATTERNS:
        values = frame.values(text)
        if values is not None:
            found = _held(frame, values, _table(language, "label_patterns").get(frame.key), language, check_id)
            if found is not None:
                return found
    return None


def _sentence_in(text: str, language: str, check_id: str | None) -> str | None:
    """One sentence: fixed, or by its frame."""
    exact = _table(language, "lines").get(text)
    if exact is not None:
        return exact
    for frame in LINE_PATTERNS:
        values = frame.values(text)
        if values is not None:
            found = _held(frame, values, _table(language, "line_patterns").get(frame.key), language, check_id)
            if found is not None:
                return found
    return None


@lru_cache(maxsize=4096)
def _line(text: str, language: str, check_id: str | None = None) -> str | None:
    whole = _sentence_in(text, language, check_id)
    if whole is not None:
        return whole
    pieces = _SENTENCE_END.split(text)
    if len(pieces) > 1:
        # The longest run of pieces that is one sentence, then the rest: a sentence may hold "e.g. " itself.
        def rest(at: int) -> list[str] | None:
            if at == len(pieces):
                return []
            for end in range(len(pieces), at, -1):
                if at == 0 and end == len(pieces):
                    continue
                found = _sentence_in(" ".join(pieces[at:end]), language, check_id)
                if found is not None:
                    after = rest(end)
                    if after is not None:
                        return [found, *after]
            return None

        said = rest(0)
        if said is not None:
            return " ".join(said)
    phrase_only = term(text, language)  # a reason that is a phrase (or a list of them) rather than a sentence
    if phrase_only is not None:
        return phrase_only
    if check_id:  # a summary that is the check's own finding titles, one after another
        for separator in _JOINED:
            parts = [title(check_id, part, language) for part in text.split(separator)]
            if all(ok and _TITLE_FRAMES.get(check_id) and title_key(check_id, part) for (_, ok), part in zip(parts, text.split(separator))):
                return separator.join(shown for shown, _ in parts)
    return None


def label(text: str | None, language: str | None = None, check_id: str | None = None) -> tuple[str | None, bool]:
    """A short name as it is shown: a check's title, a part that was not assessed, a column, a panel's title."""
    language = _language(language)
    if not (text or "").strip():
        return text, True
    if language == strings.DEFAULT_LANGUAGE:
        return english(text), True
    found = _label(text.strip(), language, check_id)
    return (found, True) if found is not None else (_marked(text, language), False)


def line(text: str | None, language: str | None = None, check_id: str | None = None, capital: bool = False) -> tuple[str | None, bool]:
    """A sentence, or a run of sentences, as it is shown: a check's summary, the reason a part was not assessed, a
    line of a data panel. `capital` begins it with a capital letter (a reason shown on a line of its own)."""
    language = _language(language)
    if not (text or "").strip():
        return text, True
    if language == strings.DEFAULT_LANGUAGE:
        return english(text), True
    found = _line(text.strip(), language, check_id)
    if found is None:
        return _marked(text, language), False
    return (_capital(found, language) if capital and not re.match(r"\S*[.:/]\S", found) else found), True
