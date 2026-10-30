"""The brand name an audit uses, and where it came from (DECISIONS 201).

The name decides which DataForSEO keywords are brand searches (`dataforseo.insights.apply_relevance`) and what the
report's cover is titled. It is taken in this order, and the report says which (`report["brand"]`):

1. the name the person typed or saved (`source` "typed", the only confirmed one);
2. the site's own name (`source` "site"): og:site_name that is not a page title, the Organization or WebSite name
   that describes this site, and the repeated part of the page titles: the same sources STR-5 reads. The name given on
   the most independent page/source channels wins, when supported on at least 3 pages or half of them;
3. the address's own label split into words (`source` "domain"), only when every piece is a word of the site's own
   titles and headings: "lezzetliyemekevi" is "Lezzetli Yemek Evi" when the site says those three words;
4. none (`name` None). Keywords are then not sorted into brand searches and other searches at all.

Before this, the web app split the label only at "-" and "_" and used the result as the brand even when nobody
confirmed it: a glued label became one word no keyword contains (docs/FALSE-ALARMS.md FA-022).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Iterable
from urllib.parse import urlsplit

from .access_data import homepage_url
from .analysis import node_types
from .checks.structure import GENERIC_TITLES, TITLE_SEPARATORS, _is_this_site, _typed_nodes, brand_key, og_site_names
from .structure_data import indexable_pages, identity_organization_nodes, text_value
from .urls import registrable_domain

TYPED, SITE, DOMAIN = "typed", "site", "domain"
SOURCES = (TYPED, SITE, DOMAIN)
# Where a name read from the site was found. Equal identity votes remain unresolved.
FOUND_IN = ("og_site_name", "organization", "website", "title", "address")
# The name given on the most pages wins when it is on at least this many pages, or on half of the pages read.
MIN_PAGES = 3
# A piece of the address's label is a word of the site when it is at least this long.
MIN_WORD = 2
KEYS = ("name", "source", "confirmed", "found_in", "pages")

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _tokens(text: str | None) -> list[str]:
    lowered = (text or "").replace("İ", "i").casefold().replace("ı", "i")
    plain = ''.join(c for c in unicodedata.normalize('NFKD', lowered) if not unicodedata.combining(c))
    return _WORD.findall(plain)


def _fold(word: str) -> str:
    return word.translate(_FOLD)


def compact(text: str | None) -> str:
    """`text` written without spaces or marks, lower case, Turkish letters folded: "Adile Sultan Ev Yemekleri" and
    "adilesultanevyemekleri" are the same name (DECISIONS 220)."""
    return _fold("".join(_tokens(text)))


def same_name(a: str | None, b: str | None) -> bool:
    """Whether two names are one name written with or without spaces, in any case (DECISIONS 220)."""
    return bool(compact(a)) and compact(a) == compact(b)


def none() -> dict[str, Any]:
    return {"name": None, "source": None, "confirmed": False, "found_in": None, "pages": None}


def typed(name: str | None) -> dict[str, Any] | None:
    name = (name or "").strip()
    return {"name": name, "source": TYPED, "confirmed": True, "found_in": None, "pages": None} if name else None


def identity_observations(result: Any, pages: list | None = None) -> dict[str, Any]:
    """Complete selected-page identity inputs, safe to retain for copied reassessment."""
    pages = indexable_pages(result) if pages is None else [p for p in pages if getattr(p, 'analysis', None)]
    home = homepage_url(result)
    records = []
    by_url = {p.url: p for p in pages}
    def add(name, source, url):
        if name and brand_key(name) not in GENERIC_TITLES:
            record = {'name': name, 'source': source, 'url': url,
                      'observed_at': getattr(by_url.get(url), 'requested_at', None)}
            if record not in records:
                records.append(record)
    named, _ = og_site_names(pages)
    for url, name in named:
        add(name, 'og_site_name', url)
    for page in pages:
        for node in identity_organization_nodes(page.analysis):
            if _is_this_site(node, page.url, home, result.origin):
                add(text_value(node.get('name')), 'organization', page.url)
        for node, nested in _typed_nodes(page.analysis):
            if not nested and 'WebSite' in node_types(node) and _is_this_site(node, page.url, home, result.origin):
                add(text_value(node.get('name')), 'website', page.url)
        parts = TITLE_SEPARATORS.split(page.analysis.get('title') or '')
        if len(parts) >= 2:
            for part in {parts[0].strip(), parts[-1].strip()}:
                if part and len(part.split()) <= 5:
                    add(part, 'title', page.url)
    return {'complete': True, 'eligible_pages': len(pages), 'observations': records}


def choose_identity(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Same consensus for live processing and explicitly retained saved inputs."""
    if evidence.get('complete') is not True:
        return None
    on_pages, spellings, where, votes = defaultdict(set), defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    for row in evidence.get('observations') or []:
        name, source, url = row['name'], row['source'], row['url']
        key = compact(brand_key(name))
        if not key:
            continue
        on_pages[key].add(url)
        votes[key].add((url, source))
        spellings[key][name] += 1
        where[key][source] += 1
    def rank(key):
        return len(votes[key]), len(on_pages[key]), len(where[key])
    ordered = sorted(on_pages, key=rank, reverse=True)
    if not ordered:
        return None
    winner = ordered[0]
    count = len(on_pages[winner])
    if count < MIN_PAGES and count * 2 < evidence['eligible_pages']:
        return None
    if len(ordered) > 1 and rank(ordered[1]) == rank(winner):
        return None
    return {'name': spellings[winner].most_common(1)[0][0], 'found_in': where[winner].most_common(1)[0][0], 'pages': count}


def site_brand(result: Any, pages: list | None = None) -> dict[str, Any] | None:
    return choose_identity(identity_observations(result, pages))


def site_words(pages: Iterable[Any]) -> dict[str, str]:
    """The words of the pages' titles and headings: {word without Turkish letters: the word as written, lower case}."""
    out: dict[str, str] = {}
    for page in pages:
        analysis = getattr(page, "analysis", None) or {}
        texts = [str(analysis.get("title") or "")] + [str(h.get("text") or "") for h in analysis.get("headings") or [] if isinstance(h, dict)]
        for text in texts:
            for word in _tokens(text):
                if len(word) >= MIN_WORD:
                    out.setdefault(_fold(word), word)
    return out


def _split(piece: str, words: dict[str, str]) -> list[str] | None:
    """`piece` written as site words, fewest words first; None when it cannot be."""
    best: list[list[str] | None] = [[]] + [None] * len(piece)
    for end in range(1, len(piece) + 1):
        for start in range(0, end - MIN_WORD + 1):
            part = piece[start:end]
            if best[start] is not None and part in words:
                candidate = best[start] + [words[part]]
                if best[end] is None or len(candidate) < len(best[end]):
                    best[end] = candidate
    return best[len(piece)]


def label_words(host: str | None, words: dict[str, str]) -> list[str] | None:
    """The address's own label as the site's words ("lezzetliyemekevi" -> lezzetli, yemek, evi), or None when any
    piece of it is not a word of the site."""
    label = registrable_domain((host or "").lower().removeprefix("www.")).split(".")[0]
    pieces = [_fold(piece) for piece in re.split(r"[-_]+", label) if piece]
    if not pieces or not words:
        return None
    out: list[str] = []
    for piece in pieces:
        found = _split(piece, words)
        if not found:
            return None
        out += found
    return out


def _capital(word: str) -> str:
    return word[:1].upper() + word[1:]


def resolve(result: Any, typed_name: str | None = None, pages: list | None = None) -> dict[str, Any]:
    """The brand the audit uses: {"name", "source", "confirmed", "found_in", "pages"} (`KEYS`). `pages` are the pages
    read when another reader read them (Firecrawl); by default the crawl's own indexable pages."""
    chosen = typed(typed_name)
    own = indexable_pages(result) if pages is None else [p for p in pages if getattr(p, "analysis", None)]
    if chosen:
        # A typed name with no spaces that is the site's own name glued into one word takes the site's spelling and
        # stays typed (DECISIONS 220): "Adilesultanevyemekleri" is "Adile Sultan Ev Yemekleri" when the site says so.
        if " " not in chosen["name"]:
            found = site_brand(result, own)
            if found and " " in found["name"] and same_name(chosen["name"], found["name"]):
                chosen["name"] = found["name"]
        return chosen
    found = site_brand(result, own)
    if found:
        return {"name": found["name"], "source": SITE, "confirmed": False, "found_in": found["found_in"], "pages": found["pages"]}
    host = urlsplit(getattr(result, "origin", "") or "").hostname
    split = label_words(host, site_words(own))
    if split:
        return {"name": " ".join(_capital(word) for word in split), "source": DOMAIN, "confirmed": False, "found_in": "address",
                "pages": None}
    return none()


def from_texts(typed_name: str | None, domain: str | None, texts: Iterable[str]) -> dict[str, Any]:
    """The same order without a crawl record (`apply_relevance` called on its own): the typed name, else the label split
    into the words of `texts`, else none."""
    chosen = typed(typed_name)
    if chosen:
        return chosen
    words: dict[str, str] = {}
    for text in texts:
        for word in _tokens(text):
            if len(word) >= MIN_WORD:
                words.setdefault(_fold(word), word)
    split = label_words(domain, words)
    if split:
        return {"name": " ".join(_capital(word) for word in split), "source": DOMAIN, "confirmed": False, "found_in": "address",
                "pages": None}
    return none()


def declared_aliases(pages: Iterable[Any], name: str | None, domain: str | None) -> list[dict[str, Any]]:
    """Explicit aliases of the selected own identity, not products or other entities.

    Spacing/case/diacritic forms already share compact(). A domain stem alone is
    not a new owned brand name. Shortened names require a declaration or profile.
    """
    from .structure_data import as_list
    own = (domain or '').casefold().removeprefix('www.')
    out = []
    if not name or not own:
        return out
    for page in pages:
        for node in identity_organization_nodes(getattr(page, 'analysis', None) or {}):
            address = text_value(node.get('url')) or text_value(node.get('@id'))
            resolved = urlsplit(address or '')
            host = (resolved.hostname or '').casefold().removeprefix('www.')
            if resolved.scheme not in ('http', 'https') or not (host == own or host.endswith('.'+own)):
                continue
            names = [text_value(node.get('name'))] + [v for v in as_list(node.get('alternateName')) if isinstance(v, str)]
            if not any(same_name(name, v) for v in names):
                continue
            for field in ('alternateName', 'legalName'):
                for value in as_list(node.get(field)):
                    if isinstance(value, str) and value.strip():
                        record = {'name': value.strip(), 'kind': 'declared_identity_alias',
                                  'source': 'saved own Organization.'+field, 'url': page.url,
                                  'observed_at': getattr(page, 'requested_at', None),
                                  'owner_confirmed': False, 'entity': node.get('@id') or address}
                        if record not in out:
                            out.append(record)
    return out


def reassess_report(report):
    """Explicit copy only: retained input votes, never reconstruct missing markup.

    Legacy reports without complete source channels keep their existing identity,
    with a named gap. Keyword reassessment can use retained provider rows/SERP facts
    without buying new data; old missing entity aliases remain unavailable.
    """
    check = next((c for c in report.get('checks', []) if c['check_id'] == 'STR-5'), None)
    if not check:
        return
    ev = check.setdefault('evidence', {})
    from .checks.structure import localized_name_extras
    from copy import deepcopy
    extras = localized_name_extras(ev.get('localized_name_observations') or [])
    for finding in list(check.get('findings') or []):
        match = re.fullmatch(r'The brand is named (\d+) different ways', finding.get('title', ''))
        if not match:
            continue
        details = finding.get('evidence') or {}
        variants = details.get('variants') or []
        if len(variants) != int(match.group(1)):
            ev['identity_count_reassessment_gap'] = 'Complete identity variant membership was not retained.'
            continue
        # Same rule as STR-5: a declared alias still counts when it is also used as the main Organization name.
        declared = set(details.get('declared_in_schema_not_counted') or {})
        remaining = [v for v in variants if v.get('normalized') not in extras and not (
            v.get('normalized') in declared and 'Organization name' not in (v.get('by_source') or {}))]
        if len(remaining) == len(variants):
            continue
        ev.setdefault('localized_count_reassessment', []).append({'finding': deepcopy(finding),
            'remaining_identity_groups': len(remaining), 'interpretation': 'Declared entity/alias context retained; translation meaning is not newly verified.'})
        if len(remaining) <= 2:
            check['findings'].remove(finding)
        else:
            details.setdefault('original_variants', deepcopy(variants))
            details['variants'] = remaining
            finding['title'] = f'The brand is named {len(remaining)} different ways'
    if extras:
        from .coverage import derive
        check['coverage'] = derive('STR-5', check['status'], ev, check.get('observations') or [])
        if not check.get('findings') and not check.get('review_items'):
            check['status'] = 'partial' if check['coverage']['not_assessed'] else 'observed'
    inputs = ev.get('identity_inputs') or {}
    current = report.get('brand') or none()
    if current.get('source') != TYPED:
        if inputs.get('complete') is True:
            chosen = choose_identity(inputs)
            report['brand'] = {'source': SITE, 'confirmed': False, **chosen} if chosen else none()
        else:
            ev['identity_reassessment_gap'] = 'Complete identity source channels were not retained; prior identity is not newly verified.'
    section = report.get('dataforseo')
    if not section:
        return
    from .dataforseo import insights
    from .reassess_nine import saved_pages
    crawl = report.get('crawl') or {}
    pages = saved_pages(crawl)
    if not any(((c.get('evidence') or {}).get('data') or {}).get('provider_table') for c in section.get('checks') or []):
        return
    owner_aliases, owner_organizations = set(), set()
    for panel in section.get('checks') or []:
        data = (panel.get('evidence') or {}).get('data') or {}
        for assessment in data.get('keyword_assessments') or []:
            for source in assessment.get('sources') or []:
                if source.get('source') == 'owner profile' and source.get('name'):
                    if source.get('kind') == 'brand_alias':
                        owner_aliases.add(source['name'])
                    elif source.get('kind') == 'related_organization':
                        owner_organizations.add(source['name'])
    insights.refresh_relevance(section)
    selected = report.get('brand') or current
    insights.apply_relevance(section, brand=selected.get('name'), brand_info=selected,
        domain=urlsplit(crawl.get('origin') or '').hostname, texts=insights.page_texts(pages), pages=pages,
        declared_identity_aliases=ev.get('identity_alias_inputs') or [],
        aliases=sorted(owner_aliases), related_organizations=sorted(owner_organizations))
