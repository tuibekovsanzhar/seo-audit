"""The client brief ("Müşteri özeti", DECISIONS 319): at most five pages for a business owner, in Turkish or English.

Built from the same data as the team report (`build_data.build_from_files`: the saved audit re-evaluated with the current
engine, the card selection, the manual checks in review.json and the business type) and printed in the same design
family (`render`: fonts, colours, header, cards). No model in the loop.

1. Summary: a one-sentence verdict, site health in plain words, the most important problems, what already works.
2. Key pages of the business type's profile: why each matters for customers, Google and AI assistants, and its state.
3-4. The top problems (at most 5): measured or confirmed problem cards only, never a "Kontrol edin" item, an
   opportunity, a note or anything still waiting in "Teyit edin". What is wrong, why it matters for the business, an
   example from the site, who fixes it, the effort, and when one template fix covers many pages.
5. A 30/60/90-day plan, what the audit could not check, and a pointer to the team report.

The gate (`check`): a brief over five pages, with a finding ID, a rule or check name, an unconfirmed item, a vendor name
(other than the protection service that blocks crawlers), or a technical term without its short explanation, or built
from an audit where `client_selection.client_brief_allowed` is false, is blocked, with the reason in plain words.

CLI (the maya-audit-pro skill's `scripts/brief.py` runs this):
  python -m maya_audit_web.team_report.brief <report.json> --lang tr --pdf ozet.pdf [--html ozet.html] [--png DIR]
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
MAX_PAGES = 5
MAX_PROBLEMS = 5
PROBLEMS_PER_PAGE = 3
KEY_PAGES_SHOWN = 8
GOOD_SHOWN = 3
SEVERITIES = ("S1", "S2", "S3", "S4")
ALLOWED_CONFIDENCE = ("measured", "estimated")  # "confirmed or measured": an estimate is measured, its extent estimated
# Any of these in a brief means an ID, a rule or a check name was left in it.
ID_PATTERNS = (
    re.compile(r"\b[A-Z]{2,5}-\d{1,3}-[0-9a-f]{6,}\b"),  # finding IDs: STR-12-c792bc34
    re.compile(r"\b(?:ACC|IDX|STR|RND|PRF|ANS|TSEO|DFS|LG|RG)-\d{1,3}\b"),  # check and gate names: ACC-9, RG-15
    re.compile(r"\b(?:acc|idx|str|rnd|prf|ans|tseo)\d{1,2}\.[a-z_0-9.]+"),  # rule ids: idx6.alias_links
    re.compile(r"\b(?:judgment|shared)\.[a-z_.]+"),
    # DECISIONS 324: the team's priority codes; the brief says them in plain words (not inside base64 font data)
    re.compile(r"(?<![A-Za-z0-9+/])P[0-3](?![A-Za-z0-9+/=])"),
)
# Tools, providers and platforms: never in a brief. A bot-protection service is allowed only when a problem in the
# brief is that service blocking crawlers (its name comes from the finding's evidence).
VENDORS = ("Firecrawl", "DataForSEO", "Lighthouse", "PageSpeed", "CrUX", "Playwright", "Chromium", "Screaming Frog",
           "Ahrefs", "Semrush", "Shopify", "WordPress", "WooCommerce", "Magento", "Wix", "Squarespace", "Webflow",
           "Translate & Adapt", "Yoast", "Rank Math", "GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended",
           "OAI-SearchBot", "Googlebot", "Bingbot", "Maya Audit")
PROTECTION = ("Imperva", "Incapsula", "Cloudflare", "Akamai", "DataDome", "PerimeterX", "HUMAN Security", "Kasada",
              "Sucuri", "Fastly", "Radware", "F5", "AWS WAF", "Vercel")
BOT_RULES = ("acc9.", "acc4.outcome")
# Rules whose problem is the site's, not a page's (the certificate, robots.txt, bot protection, the sitemap): a key page
# with no problem of its own still has these (DECISIONS 319).
SITE_RULES = ("acc1.", "acc2.", "acc4.", "acc6.", "acc7.", "acc9.", "idx2.", "idx5.", "idx10.", "prf1.no_hsts",
              "prf1.security_headers", "str18.", "str3.no_organization", "str21.")


@lru_cache(maxsize=None)
def library(lang: str) -> dict:
    return json.loads((HERE / "texts" / f"brief-{lang}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _team_labels(lang: str) -> dict:
    return json.loads((HERE / "refs" / "etiketler.json").read_text(encoding="utf-8"))[lang]


def fmt(template: str, **values) -> str:
    """`{name}`, `[[optional {name}]]` (texts.fill) and `{name:singular|plural}` (texts.label's plural form)."""
    from maya_audit_web.team_report.texts import _PLURAL, fill

    def one(m):
        value = values.get(m.group(1))
        digits = re.search(r"\d[\d,.]*", str(value if value is not None else ""))
        n = int(re.sub(r"[,.]", "", digits.group(0))) if digits else None
        return f"{value} {m.group(2) if n == 1 else m.group(3)}"
    return fill(_PLURAL.sub(one, template), **values) or ""


def e(s) -> str:
    return _html.escape("" if s is None else str(s))


def numbers(nums, lang: str) -> tuple[str, str]:
    """("1, 3 ve 4", word) / ("1, 3 and 4", "Problems"): a list of problem numbers in words, and the word for them."""
    L = library(lang)["labels"]
    nums = [str(n) for n in nums]
    text = nums[0] if len(nums) == 1 else f"{', '.join(nums[:-1])} {L['and']} {nums[-1]}"
    return text, L["problem_word"][0 if len(nums) == 1 else 1]


def plain_scope(scope: str | None, lang: str) -> str | None:
    """The team card's scope in a client's words: "4 URLs" -> "4 addresses" (Turkish already says "adres")."""
    if not scope or lang != "en":
        return scope
    return re.sub(r"\bURLs\b", "addresses", re.sub(r"\b(1) URL\b", r"\1 address", scope))


def _invert(table: dict) -> dict:
    return {v: k for k, v in table.items()}


def entry_for(rule_id: str | None, merge_group: str | None, lang: str, finding_id: str | None = None) -> dict | None:
    """The brief's words for a card: its merge group, else its rule, else its rule family (the rule id's prefix, or the
    finding ID's check: STR-12 -> str12)."""
    lib = library(lang)
    if merge_group and merge_group in lib["groups"]:
        return lib["groups"][merge_group]
    if rule_id and rule_id in lib["rules"]:
        return lib["rules"][rule_id]
    family = (rule_id or "").split(".")[0] if rule_id else ""
    if not family and finding_id:
        m = re.match(r"([A-Z]+)-(\d+)", finding_id)
        family = f"{m.group(1).lower()}{m.group(2)}" if m else ""
    return lib["families"].get(family)


# ---------------------------------------------------------------- compose

def _findings(report: dict) -> dict:
    return {f.get("id"): f for c in report.get("checks") or [] for f in c.get("findings") or [] if f.get("id")}


def _service(findings: list[dict]) -> str | None:
    for f in findings:
        for b in (f.get("evidence") or {}).get("blocked_by") or []:
            if isinstance(b, dict) and b.get("name"):
                return str(b["name"])
    return None


def _loaded(rule: str | None, report: dict, L: dict) -> str | None:
    """DECISIONS 320: for a 429 block, the site files that loaded while pages were refused (robots.txt, the sitemap), in
    the brief's words with each term's explanation; None when neither loaded (the sentence then ends after the pages)."""
    if rule not in ("acc9.blocked_429", "acc9.rate_limited_429"):
        return None
    from maya_audit import maya_blocked
    served = maya_blocked.served_files(report.get("crawl") or {})
    words = [L["served"][k] for k, on in (("robots", served["robots"]), ("sitemap", served["sitemaps"] > 0)) if on]
    return L["served"]["and"].join(words) or None


def _expiry(rule: str | None, members: list[dict], report: dict, lang: str) -> dict:
    """DECISIONS 321 (1): {date, days} of a certificate that expires soon: its expiry date and the days left at the
    audit (from the audit's date); {} for any other problem or when the evidence has no date."""
    if rule != "idx2.expires":
        return {}
    from maya_audit_web.team_report.build_data import date_long, fmt_int, parse_dt
    tls = next((h for f in members for h in (f.get("evidence") or {}).get("hosts") or []
                if isinstance(h, dict) and h.get("not_after")), None)
    end, start = parse_dt((tls or {}).get("not_after")), parse_dt((report.get("crawl") or {}).get("started_at"))
    if not end or not start:
        return {}
    days = (end.date() - start.date()).days
    L = library(lang)["labels"]
    return {"date": date_long(end.isoformat(), _team_labels(lang)),
            "days": fmt(L["cert_days_one"] if days == 1 else L["cert_days"], n=fmt_int(days, lang))}


def worst_severity(items: list[dict], data: dict, report: dict) -> str:
    """DECISIONS 321 (1): the severity the verdict and the health line speak for: the worst of the brief's problems,
    of every card in the team report (a High card the brief leaves out is still there) and of a certificate that
    expires in 14 days or fewer (7 or fewer: Blocker; inclusive since DECISIONS 322), so "nothing is urgent" is never said beside one."""
    found = {p.get("severity") for p in items} | {c.get("severity") for c in data.get("_cards") or []
                                                   if c.get("severity") in ("S1", "S2")}
    from maya_audit.checks.index import expiry_severity
    for check in report.get("checks") or []:
        for f in check.get("findings") or [] if check.get("check_id") == "IDX-2" else []:
            if f.get("rule_id") != "idx2.expires":
                continue
            days = next((h.get("days_left") for h in (f.get("evidence") or {}).get("hosts") or []
                         if isinstance(h, dict) and isinstance(h.get("days_left"), (int, float))), None)
            if days is not None and expiry_severity(days).value in ("S1", "S2"):
                found.add(expiry_severity(days).value)
    return next((s for s in SEVERITIES if s in found), "none")


def coverage_line(report: dict, read: int, lang: str) -> str | None:
    """DECISIONS 321 (3): one plain line when fewer pages were read than the audit planned, with why: the site's
    protection service (a block or rate-limit finding of ACC-9), the time limit, a site smaller than the plan, or some
    addresses that could not be read. None when the plan was read."""
    crawl = report.get("crawl") or {}
    planned = (crawl.get("config") or {}).get("max_pages")
    if not isinstance(planned, int) or planned <= 0 or read >= planned:
        return None
    acc9 = [f for c in report.get("checks") or [] if c.get("check_id") == "ACC-9" for f in c.get("findings") or []
            if not str(f.get("rule_id") or "").startswith("acc9.reader")]
    reasons = " ".join(str(x) for x in ((report.get("audit_status") or {}).get("content_coverage") or {}).get("reasons") or [])
    stop = str(crawl.get("stop_reason") or "")
    kind = ("protection" if acc9 or stop == "rate_limit" else
            "time" if stop == "time_limit" or crawl.get("deadline_hit") or "time limit" in reasons else
            "small" if stop == "exhausted" else "other")
    words = library(lang)["labels"]["coverage"][kind]
    sep = "." if lang == "tr" else ","
    return fmt(words, read=f"{read:,}".replace(",", sep), planned=f"{planned:,}".replace(",", sep))


def _good(report: dict, lang: str, data: dict | None = None) -> list[str]:
    """What already works: a check that passed with no finding at all, and no finding of a check that would contradict
    it (ACC-2 'AI assistants may read the site' is not said when bot protection blocks crawlers)."""
    conflicts = {"ACC-9": ("ACC-9", "ACC-4"), "ACC-2": ("ACC-2", "ACC-3", "ACC-4", "ACC-6", "ACC-9"),
                 "IDX-2": ("IDX-2",), "IDX-6": ("IDX-6", "IDX-1"), "IDX-4": ("IDX-4", "IDX-3", "IDX-9"),
                 "PRF-2": ("PRF-2", "ACC-9"), "IDX-5": ("IDX-5", "ACC-3"), "IDX-7": ("IDX-7",),
                 "ACC-7": ("ACC-7", "ACC-9"), "STR-9": ("STR-9", "STR-12"), "ACC-1": ("ACC-1", "ACC-2", "ACC-7")}
    checks = {c.get("check_id"): c for c in report.get("checks") or []}
    with_findings = {c.get("check_id") for c in report.get("checks") or [] if c.get("findings")}
    lib = library(lang)["good"]
    out = []
    for cid in lib:
        if cid == "KEY_PAGES":  # every top page type of the business type was among the pages read (DECISIONS 311)
            business = (data or {}).get("_selection_business") or {}
            if business.get("id") not in (None, "diger") and (data or {}).get("key_pages") \
                    and not (data or {}).get("_selection_not_found") and not (data or {}).get("low_coverage"):
                out.append(lib[cid])
            continue
        c = checks.get(cid)
        if not c or c.get("status") != "pass" or c.get("findings"):
            continue
        if any(x in with_findings for x in conflicts.get(cid, (cid,))):
            continue
        out.append(lib[cid])
    return out[:GOOD_SHOWN]


def _not_checked(data: dict, report: dict, lang: str) -> str:
    L = library(lang)["labels"]
    speed = not data.get("lab") and not data.get("field")
    idx9 = next((c for c in report.get("checks") or [] if c.get("check_id") == "IDX-9"), None)
    gsc = idx9 is None or idx9.get("status") in ("not_assessed", "not_applicable", None)
    return L["not_checked_both"] if speed and gsc else L["not_checked_speed"] if speed else L["not_checked_gsc"] if gsc \
        else L["not_checked_none"]


def _example(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.netloc[4:] if parts.netloc.startswith("www.") else parts.netloc
    return (host + (parts.path if parts.path not in ("", "/") else "")) or url


def problems(data: dict, report: dict, lang: str) -> list[dict]:
    """The brief's problems: the team report's problem cards in its order, measured or confirmed, of type "Sorun",
    nothing waiting in "Teyit edin"; at most MAX_PROBLEMS."""
    from maya_audit.priority_levels import word as priority_word
    L, T = library(lang)["labels"], _team_labels(lang)
    owners, efforts, whens = _invert(T["owners"]), _invert(T["efforts"]), _invert(T["when"])
    cards = {c["finding_ids"][0]: c for c in data.get("_cards") or [] if c.get("finding_ids")}
    waiting = set(data.get("_confirm_ids") or [])
    confirmed = {k for k, v in (data.get("_confirmations") or {}).items() if (v or {}).get("result") == "confirmed"}
    found = _findings(report)
    out = []
    for t in data.get("todos") or []:
        ids = t.get("finding_ids") or []
        card = cards.get(ids[0]) if ids else None
        if not card or card.get("severity") not in SEVERITIES or (card.get("issue_type") or "issue") != "issue":
            continue
        if card.get("confidence") not in ALLOWED_CONFIDENCE or waiting & set(ids):
            continue
        rule = card.get("rule_id") or t.get("rule_id")
        words = entry_for(rule, card.get("merge_group"), lang, ids[0])
        if not words:
            continue  # a rule with no brief words never reaches a client (a test keeps every family covered)
        members = [found[i] for i in ids if i in found]
        service = _service(members) if rule and rule.startswith(BOT_RULES) else None
        links = t.get("links") or []
        example = _example(links[0]["href"]) if links else None
        scope = plain_scope(t.get("scope"), lang)
        # DECISIONS 321 (4): a merged card may have two owners ("Developer + SEO"); the brief says both in its words.
        keys = [owners[part] for part in str(t.get("owner") or "").split(" + ") if part in owners] or ["developer"]
        owner = keys[0]
        effort = efforts.get(t.get("effort"), "M")
        tpl = card.get("template_line") or {}
        evidence = ("confirmed" if confirmed & set(ids) or any(r in confirmed for r in [rule] if r) else card["confidence"])
        out.append({
            "n": len(out) + 1, "card": t.get("n"), "severity": card["severity"],
            "severity_label": L["severity"][card["severity"]],
            # DECISIONS 324: the team's P0-P3 in plain words only ("Acil" for P0), never the code
            "urgency": priority_word(t.get("p_level"), lang), "_urgency_level": t.get("p_level"),
            "title": words["title"], "what": fmt(words["what"], service=service, loaded=_loaded(rule, report, L),
                                                 **_expiry(rule, members, report, lang)), "why": words["why"],
            "example": example or L["sitewide"], "scope": fmt(L["example_scope"], scope=scope) if scope else None,
            "site": bool(rule and rule.startswith(SITE_RULES)),
            "who": " + ".join(L["owners"][k] for k in keys), "owner": owner, "effort": L["efforts"][effort], "effort_key": effort,
            "when": whens.get(t.get("when"), "later"),
            "evidence": L["evidence"][evidence],
            "template": fmt(L["template_line"], n=tpl["pages"]) if tpl.get("pages") else None,
            "_finding_ids": ids, "_rule": rule, "_service": service, "_confidence": card["confidence"],
            "_example_url": links[0]["href"] if links else None,
        })
        if len(out) >= MAX_PROBLEMS:
            break
    return out


def _key_pages(data: dict, items: list[dict], lang: str) -> list[dict]:
    L, lib = library(lang)["labels"], library(lang)["page_types"]
    by_card = {p["card"]: p["n"] for p in items}
    site = {p["n"] for p in items if p.get("site")}
    rows = []
    pages = data.get("key_pages") or []
    # One row per page type first (the homepage, then each type's best page), then by the list's order: eight
    # treatment pages must not push the doctors' page out (moodist). The list's order is kept.
    keep, kinds = [], set()
    for i, p in enumerate(pages):
        if (p.get("kind_id") or "other") not in kinds and len(keep) < KEY_PAGES_SHOWN:
            keep.append(i)
            kinds.add(p.get("kind_id") or "other")
    for i in range(len(pages)):
        if len(keep) >= KEY_PAGES_SHOWN:
            break
        if i not in keep:
            keep.append(i)
    for p in [pages[i] for i in sorted(keep)]:
        cards = [int(x) for x in re.findall(r"\d+", str(p.get("cards") or ""))]
        mine = sorted({by_card[c] for c in cards if c in by_card})
        others = [c for c in cards if c not in by_card]
        mine = [n for n in mine if n not in site]
        listed, word = numbers(mine, lang) if mine else ("", "")
        state = (fmt(L["state_plus_minor"], list=listed, word=word) if mine and others
                 else fmt(L["state_problems"], list=listed, word=word)
                 if mine else L["state_minor"] if others else L["state_ok"])
        kind = p.get("kind_id") or "other"
        rows.append({"path": p.get("path") or "/", "kind": p.get("type") or "", "why": lib.get(kind) or lib["other"],
                     "state": state, "tone": "problem" if mine else "minor" if others else "ok"})
    return rows


def _plan(items: list[dict], data: dict, lang: str) -> dict:
    L = library(lang)["labels"]
    d30, d60, d90 = [], [], []
    for p in items:
        line = fmt(L["plan_item"], n=p["n"], title=p["title"], who=p["who"])
        if p["severity"] in ("S1", "S2") or p["when"] == "week" or (p["when"] == "month" and p["effort_key"] == "S"):
            d30.append(line)
        elif p["when"] == "month":
            d60.append(line)
        else:
            d90.append(line)
    first =fmt(L["plan_item"], n=items[0]["n"], title=items[0]["title"], who=items[0]["who"]) if items else None
    if first and first not in d30:  # the most important problem always starts in the first 30 days
        (d60 if first in d60 else d90).remove(first)
        d30.insert(0, first)
    if not d60:
        d60.append(L["plan_60_empty"])
    in_brief = {p["card"] for p in items}
    if any(t.get("n") not in in_brief for t in data.get("todos") or []):
        d90.append(L["plan_minor"])
    d90.append(L["plan_recheck"])
    return {"d30": d30, "d60": d60, "d90": d90}


def compose(data: dict, report: dict, lang: str) -> dict:
    """The brief's content from the team report's data and the current-engine report it was built from."""
    L = library(lang)["labels"]
    lib = library(lang)
    meta = data.get("meta") or {}
    brand = meta.get("brand") or meta.get("domain") or ""
    items = problems(data, report, lang)
    worst = worst_severity(items, data, report)
    read = ((report.get("audit_status") or {}).get("content_coverage") or {}).get("pages_read")
    if not isinstance(read, int):
        from maya_audit.client_selection import pages_read
        read = len(pages_read(report))
    read_text = f"{read:,}".replace(",", "." if lang == "tr" else ",")
    # DECISIONS 321 (3): fewer pages read than planned: the line says how many and why, in place of "We checked N pages".
    health = [coverage_line(report, read, lang) or fmt(L["reach"], read=read_text), lib["health"][worst]]
    if items:
        health.append(fmt(L["in_brief"], n=str(len(items))))
    business = data.get("_selection_business") or {}
    blabel = (business.get("label") or {}).get(lang) if business and business.get("id") != "diger" else None
    def mid(label):  # English says it mid-sentence: "No clinic and location page ..."
        return label[:1].lower() + label[1:] if lang == "en" and label else label
    not_found = [fmt(L["not_found"], label=mid((n.get("label") or {}).get(lang) or n.get("type")))
                 for n in data.get("_selection_not_found") or []]
    out = {
        "lang": lang,
        "meta": {"brand": brand, "domain": meta.get("domain") or "", "date": meta.get("date") or "",
                 "read": read_text},
        "verdict": fmt(lib["verdict"][worst], brand=brand),
        "health": health,
        "top": [{"n": p["n"], "title": p["title"], "severity_label": p["severity_label"], "severity": p["severity"]}
                for p in items[:3]],
        "good": _good(report, lang, data),
        "business": fmt(L["business"], label=blabel) if blabel else None,
        "key_pages": _key_pages(data, items, lang),
        "not_found": not_found[:3],
        "sitewide_note": fmt(L["sitewide_note"], **dict(zip(("list", "word"), numbers([p["n"] for p in items if p.get("site")], lang))))
        if any(p.get("site") for p in items) else None,
        "problems": items,
        "plan": _plan(items, data, lang),
        "not_checked": _not_checked(data, report, lang),
        "full_report": L["full_report_line"],
        "_allowed_vendors": sorted({p["_service"] for p in items if p.get("_service")}),
        "_confirm_ids": list(data.get("_confirm_ids") or []),
    }
    return out


# ---------------------------------------------------------------- the gate

def _strings(x, skip=("path", "example")):
    """Every visible string of the brief; `skip` holds the fields that are the site's own addresses."""
    if isinstance(x, dict):
        for k, v in x.items():
            if not str(k).startswith("_") and k not in skip:
                yield from _strings(v, skip)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v, skip)
    elif isinstance(x, str):
        yield x


def check(brief: dict, *, pages: int | None = None, pdf_text: str | None = None) -> list[dict]:
    """[{kind, found}] of what blocks this brief: ids, unconfirmed, vendors, terms, pages. [] when it may be sent."""
    errors = []
    everything = list(_strings(brief, skip=())) + ([pdf_text] if pdf_text else [])
    ids = sorted({m.group(0) for s in everything for pat in ID_PATTERNS for m in pat.finditer(s)})
    if ids:
        errors.append({"kind": "ids", "found": ", ".join(ids[:5])})
    waiting = set(brief.get("_confirm_ids") or [])
    if any(p.get("_confidence") not in ALLOWED_CONFIDENCE or waiting & set(p.get("_finding_ids") or [])
           for p in brief.get("problems") or []):
        errors.append({"kind": "unconfirmed", "found": ""})
    text = " ".join(_strings(brief))
    allowed = set(brief.get("_allowed_vendors") or [])
    named = sorted({v for v in VENDORS + PROTECTION if v not in allowed and re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", text)})
    if named:
        errors.append({"kind": "vendors", "found": ", ".join(named)})
    missing = []
    for t in library(brief["lang"])["terms"]:
        if re.search(t["term"], text, re.I) and not re.search(t["explain"], text, re.I):
            missing.append(re.search(t["term"], text, re.I).group(0))
    if missing:
        errors.append({"kind": "terms", "found": ", ".join(sorted(set(missing)))})
    if pages is not None and pages > MAX_PAGES:
        errors.append({"kind": "pages", "found": str(pages), "pages": pages})
    return errors


# ---------------------------------------------------------------- HTML

CSS = """
.brief .body { padding-top: 20pt; }
.verdict { padding: 18pt 22pt 16pt 23pt; position: relative; height: 104pt; overflow: hidden; }
.verdict::before { content: ''; position: absolute; left: -.6pt; top: -.6pt; bottom: -.6pt; width: 3pt; background: var(--accent); border-radius: 3pt 0 0 3pt; }
.verdict h2 { font-size: 17pt; font-weight: 600; margin-top: 9pt; line-height: 1.3; max-height: 46pt; overflow: hidden; }
.b-row { display: flex; gap: 20pt; margin-top: 18pt; height: 416pt; }
.b-col { flex: 1; display: flex; flex-direction: column; gap: 18pt; }
.b-card { padding: 16pt 20pt; overflow: hidden; }
.b-card h3 { font-size: 12pt; font-weight: 600; }
.b-card p, .b-card li { font-size: 10.4pt; color: var(--ink); line-height: 1.45; }
.health { height: 150pt; }
.health p { margin-top: 8pt; color: var(--muted); }
.health p:first-of-type { color: var(--ink); font-weight: 600; }
.top3 { flex: 1; }
.top3 ol { list-style: none; margin-top: 10pt; }
.top3 li { display: flex; align-items: baseline; padding: 9pt 0; border-top: .6pt solid var(--line); }
.top3 li:first-child { border-top: 0; }
.top3 .n { color: var(--accent); font-weight: 600; width: 26pt; flex: 0 0 26pt; }
.top3 .t { flex: 1; font-weight: 600; font-size: 11pt; max-height: 30pt; overflow: hidden; }
.top3 .s { font-size: 8.6pt; padding: 3pt 7pt; border-radius: 3pt; margin-left: 10pt; white-space: nowrap; }
.s.S1, .s.S2 { background: var(--high-bg); color: var(--high); } .s.S3 { background: var(--med-bg); color: var(--med); }
.s.S4 { background: var(--soft); color: var(--muted); }
.top3 .more, .muted-line { font-size: 9pt; color: var(--faint); margin-top: 8pt; }
.goodc { height: 100%; }
.goodc ul { list-style: none; margin-top: 12pt; }
.goodc li { position: relative; padding: 10pt 0 10pt 22pt; border-top: .6pt solid var(--line); }
.goodc li:first-child { border-top: 0; }
.goodc li::before { content: '✓'; position: absolute; left: 0; top: 10pt; color: #2f7d4f; font-weight: 700; }
.kp { height: 540pt; padding: 16pt 20pt; overflow: hidden; }
.kp .note { font-size: 9pt; color: var(--faint); margin-top: 6pt; }
.kp table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 10pt; }
.kp th { text-align: left; font-size: 8.6pt; font-weight: 600; color: var(--faint); padding: 0 8pt 6pt 0; border-bottom: .6pt solid var(--line); }
.kp td { font-size: 9.3pt; padding: 6pt 8pt 5pt 0; border-bottom: .6pt solid var(--line); vertical-align: top; line-height: 1.32; }
.kp tr:last-child td { border-bottom: 0; }
.kp td.path { font-family: Consolas, 'Cascadia Mono', Menlo, monospace; font-size: 8.4pt; word-break: break-all; }
.kp td.kind { font-weight: 600; }
.kp td.why { color: var(--muted); }
.kp td.state.problem { color: var(--high); font-weight: 600; } .kp td.state.ok { color: #2f7d4f; }
.kp ul.nf { margin-top: 8pt; padding-left: 13pt; font-size: 8.6pt; color: var(--faint); line-height: 1.35; }
.probs { display: flex; flex-direction: column; gap: 16pt; height: 540pt; }
.prob { height: 169pt; padding: 13pt 20pt 12pt; overflow: hidden; display: flex; flex-direction: column; }
.prob .ph { display: flex; align-items: baseline; }
.prob .ph .n { font-size: 12pt; font-weight: 600; color: var(--accent); width: 26pt; flex: 0 0 26pt; }
.prob .ph b { flex: 1; font-size: 12.4pt; font-weight: 600; white-space: nowrap; overflow: hidden; }
.prob .ph .s { font-size: 8.6pt; padding: 3pt 7pt; border-radius: 3pt; margin-left: 12pt; white-space: nowrap; }
.prob .ph .u { font-size: 8.6pt; padding: 2.4pt 7pt; border-radius: 3pt; margin-left: 6pt; white-space: nowrap; border: .6pt solid var(--line); }
.prob .ph .u.p0 { border-color: var(--high); color: var(--high); font-weight: 600; }
.prob .pb { display: flex; gap: 22pt; margin-top: 8pt; flex: 1; min-height: 0; }
.prob .l { flex: 0 0 600pt; } .prob .r { flex: 1; border-left: .6pt solid var(--line); padding-left: 16pt; }
.prob .eyebrow { font-size: 7.8pt; }
.prob .l p { font-size: 9.6pt; line-height: 1.36; margin: 2pt 0 6pt; max-height: 39pt; overflow: hidden; }
.prob .l p.why { color: var(--muted); }
.prob .r div.v { font-size: 9.2pt; line-height: 1.3; margin: 1pt 0 5pt; }
.prob .r .ex { font-family: Consolas, 'Cascadia Mono', Menlo, monospace; font-size: 8.4pt; word-break: break-all; max-height: 22pt; overflow: hidden; }
.prob .r .tpl { color: #2f7d4f; font-size: 8.8pt; max-height: 36pt; overflow: hidden; }
.prob .pm { display: flex; gap: 18pt; }
.prob .r .sc { color: var(--muted); margin-top: -3pt; }
.plan { display: flex; gap: 18pt; height: 330pt; }
.plan .b-card { flex: 1; }
.plan .when { font-size: 18pt; font-weight: 600; color: var(--accent); margin-top: 2pt; }
.plan ul { list-style: none; margin-top: 10pt; }
.plan li { font-size: 9.8pt; line-height: 1.38; padding: 7pt 0; border-top: .6pt solid var(--line); }
.plan li:first-child { border-top: 0; }
.p5b { display: flex; gap: 18pt; margin-top: 18pt; height: 192pt; }
.p5b .b-card { flex: 1; }
.p5b p { margin-top: 10pt; color: var(--muted); }
.p5b .full { background: var(--na-bg); border-color: var(--na-line); }
.p5b .full .eyebrow { color: var(--accent); }
.brief .meta .pill { background: var(--soft); color: var(--muted); }
"""


def _header(b: dict, L: dict, idx: int, title: str, sub: str) -> str:
    import base64
    logo = base64.b64encode((HERE / "assets" / "maya_logo.png").read_bytes()).decode()
    m = b["meta"]
    tabs = "".join(f'<div class="tab{" on" if i == idx else ""}">{e(t)}</div>' for i, t in enumerate(L["tabs"]))
    return (f'<div class="top"><div class="brandbar"><div class="left"><img src="data:image/png;base64,{logo}" alt="maya">'
            f'<div class="sep"></div><span class="kind">{e(L["doc_kind"])}</span></div>'
            f'<div class="client"><b class="clip">{e(m["brand"])}</b><span>{e(m["domain"])}</span></div></div>'
            f'<div class="headrow"><div><h1>{e(title)}</h1><p>{e(sub)}</p></div>'
            f'<div class="meta"><span class="pill">{e(fmt(L["coverage_pill"], read=m["read"]))}</span>'
            f'<div class="date">{e(m["date"])}</div></div></div><div class="tabs">{tabs}</div></div>')


def _footer(b: dict, L: dict, n: int, total: int) -> str:
    m = b["meta"]
    return (f'<div class="foot"><span>{e(fmt(L["footer"], domain=m["domain"], date=m["date"]))}</span>'
            f'<span>{n:02d} / {total:02d}</span></div>')


def _page1(b: dict, L: dict) -> str:
    health = "".join(f"<p>{e(x)}</p>" for x in b["health"])
    top = "".join(f'<li><span class="n">{p["n"]:02d}</span><span class="t" data-slot="top[{i}]" data-fit="9">{e(p["title"])}</span>'
                  f'<span class="s {e(p["severity"])}">{e(p["severity_label"])}</span></li>' for i, p in enumerate(b["top"]))
    top_html = (f'<ol>{top}</ol><div class="more">{e(L["top_more"])}</div>' if top else f'<p class="muted-line">{e(L["top_none"])}</p>')
    good = "".join(f"<li>{e(x)}</li>" for x in b["good"]) or f"<li>{e(L['good_none'])}</li>"
    return (f'<div class="body"><div class="card verdict"><div class="eyebrow">{e(L["verdict"])}</div>'
            f'<h2 data-slot="verdict">{e(b["verdict"])}</h2></div>'
            f'<div class="b-row"><div class="b-col"><div class="card b-card health"><h3>{e(L["health"])}</h3>{health}</div>'
            f'<div class="card b-card top3"><h3>{e(L["top"])}</h3>{top_html}</div></div>'
            f'<div class="b-col"><div class="card b-card goodc"><h3>{e(L["good"])}</h3><ul>{good}</ul></div></div></div></div>')


def _page2(b: dict, L: dict) -> str:
    rows = "".join(f'<tr><td class="path">{e(p["path"])}</td><td class="kind">{e(p["kind"])}</td><td class="why">{e(p["why"])}</td>'
                   f'<td class="state {p["tone"]}">{e(p["state"])}</td></tr>' for p in b["key_pages"])
    table = (f'<table><colgroup><col style="width:24%"><col style="width:16%"><col style="width:42%"><col></colgroup>'
             f'<tr><th>{e(L["col_page"])}</th><th>{e(L["col_kind"])}</th><th>{e(L["col_why"])}</th><th>{e(L["col_state"])}</th></tr>'
             f'{rows}</table>') if rows else f'<p class="muted-line">{e(L["kp_none"])}</p>'
    business = f'<div class="note">{e(b["business"])}</div>' if b.get("business") else ""
    nf = "".join(f"<li>{e(x)}</li>" for x in ([b["sitewide_note"]] if b.get("sitewide_note") else []) + (b.get("not_found") or []))
    return (f'<div class="body"><div class="card kp">{business}{table}'
            + (f'<ul class="nf">{nf}</ul>' if nf else "") + '</div></div>')


def _problem(p: dict, L: dict) -> str:
    right = [f'<div class="eyebrow">{e(L["example"])}</div><div class="v ex">{e(p["example"] or "—")}</div>'
             + (f'<div class="v sc">{e(p["scope"])}</div>' if p.get("scope") else ""),
             f'<div class="pm"><div><div class="eyebrow">{e(L["who"])}</div><div class="v">{e(p["who"])}</div></div>'
             f'<div><div class="eyebrow">{e(L["effort"])}</div><div class="v">{e(p["effort"])}</div></div>'
             f'<div><div class="eyebrow">{e(L["status"])}</div><div class="v">{e(p["evidence"])}</div></div></div>']
    if p.get("template"):
        right.append(f'<div class="eyebrow">{e(L["template"])}</div><div class="v tpl">{e(p["template"])}</div>')
    return (f'<div class="card prob"><div class="ph"><span class="n">{p["n"]:02d}</span>'
            f'<b data-slot="problems[{p["n"] - 1}].title" data-fit="9.5">{e(p["title"])}</b>'
            f'<span class="s {e(p["severity"])}">{e(p["severity_label"])}</span>'
            + (f'<span class="u {e(str(p.get("_urgency_level") or "").lower())}">{e(p["urgency"])}</span>' if p.get("urgency") else "")
            + '</div>'
            f'<div class="pb"><div class="l"><div class="eyebrow">{e(L["what"])}</div>'
            f'<p data-slot="problems[{p["n"] - 1}].what">{e(p["what"])}</p>'
            f'<div class="eyebrow">{e(L["why"])}</div><p class="why" data-slot="problems[{p["n"] - 1}].why">{e(p["why"])}</p></div>'
            f'<div class="r">{"".join(right)}</div></div></div>')


def _problem_pages(b: dict, L: dict) -> list[str]:
    items = b["problems"]
    if not items:
        return [f'<div class="body"><div class="card b-card"><p>{e(L["top_none"])}</p></div></div>']
    return [f'<div class="body"><div class="probs">{"".join(_problem(p, L) for p in items[i:i + PROBLEMS_PER_PAGE])}</div></div>'
            for i in range(0, len(items), PROBLEMS_PER_PAGE)]


def _page5(b: dict, L: dict) -> str:
    cols = "".join(f'<div class="card b-card"><div class="when">{e(L[k])}</div><ul>'
                   + "".join(f"<li>{e(x)}</li>" for x in b["plan"][k]) + "</ul></div>" for k in ("d30", "d60", "d90"))
    return (f'<div class="body"><div class="plan">{cols}</div><div class="p5b">'
            f'<div class="card b-card"><h3>{e(L["not_checked"])}</h3><p>{e(b["not_checked"])}</p></div>'
            f'<div class="card b-card full"><div class="eyebrow">{e(L["full_report"].upper())}</div><p>{e(b["full_report"])}</p></div>'
            f'</div></div>')


def page_count(b: dict) -> int:
    return 3 + max(1, -(-len(b["problems"]) // PROBLEMS_PER_PAGE))


def build_html(b: dict) -> str:
    from maya_audit_web.team_report.render import CSS as BASE, font_css
    L = library(b["lang"])["labels"]
    pages = [(0, L["p1_title"], L["p1_sub"], _page1(b, L)), (1, L["p2_title"], L["p2_sub"], _page2(b, L))]
    for i, content in enumerate(_problem_pages(b, L)):
        pages.append((2, L["p3_title"] if i == 0 else L["p4_title"], L["p3_sub"], content))
    pages.append((3, L["p5_title"], L["p5_sub"], _page5(b, L)))
    total = len(pages)
    body = "".join(f'<section class="page">{_header(b, L, tab, t, s)}{content}{_footer(b, L, i + 1, total)}</section>'
                   for i, (tab, t, s, content) in enumerate(pages))
    title = f"Maya | {b['meta']['brand']} | {L['doc_kind'].title()}"
    return (f'<!doctype html><html lang="{b["lang"]}"><head><meta charset="utf-8"><title>{e(title)}</title>'
            f'<style>{font_css()}\n{BASE}\n{CSS}</style></head><body class="brief">{body}</body></html>')


# ---------------------------------------------------------------- the whole path

@dataclass
class Brief:
    lang: str
    content: dict | None = None
    pdf: bytes | None = None
    html: str | None = None
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    pages: int | None = None
    previews: list[bytes] = field(default_factory=list)


def _reason(lang: str, kind: str, **values) -> str:
    words = library(lang)["blocked"]
    return fmt(words.get(kind) or words["pdf"], **values)


def _pdf_text(pdf: Path) -> tuple[int, str]:
    try:
        import fitz  # type: ignore
        doc = fitz.open(str(pdf))
        return len(doc), "\n".join(p.get_text() for p in doc)
    except ImportError:
        from pypdf import PdfReader
        r = PdfReader(str(pdf))
        return len(r.pages), "\n".join(p.extract_text() or "" for p in r.pages)


def build(report_path: Path, lang: str, *, review_path: Path | None = None, affected_path: Path | None = None,
          audit_id: str | None = None, previews: bool = False, render_pdf: bool = True) -> Brief:
    """The client brief of one saved audit. Never raises for a brief that cannot be sent: it says why."""
    from maya_audit import client_selection, release_gate
    from maya_audit_web.team_report import build_data, validate_data
    out = Brief(lang=lang)
    try:
        data, _ = build_data.build_from_files(report_path, lang, audit_id=audit_id, review=review_path,
                                              affected_path=affected_path)
    except build_data.BuildError as exc:
        out.blocked, out.reasons, out.details = True, [_reason(lang, "team")], [str(exc)]
        return out
    report = json.loads(Path(data["_report_path"]).read_text(encoding="utf-8"))
    allowed, why = client_selection.client_brief_allowed(report)
    if not allowed:
        low = client_selection.low_coverage(report) or {}
        key = "low_coverage_planned" if low.get("planned") else "low_coverage"
        out.blocked = True
        out.reasons = [_reason(lang, key, read=str(low.get("pages_read", 0)), planned=str(low.get("planned") or ""))]
        out.details = [f"client_brief_allowed: {why}"]
        return out
    checked = validate_data.check(data)
    if checked["errors"] or data.get("_gate_decision") == release_gate.BLOCKED:
        out.blocked = True
        out.reasons = [_reason(lang, "gate" if data.get("_gate_decision") == release_gate.BLOCKED else "team")]
        out.details = [x["text"] for x in checked["errors"]][:20]
        return out
    b = compose(data, report, lang)
    out.content = b
    errors = check(b, pages=page_count(b))
    if errors:
        return _blocked(out, lang, errors)
    out.html = build_html(b)
    if not render_pdf:
        return out
    from maya_audit_web.team_report import render
    with tempfile.TemporaryDirectory(prefix="maya-client-brief-") as tmp:
        html_path = Path(tmp) / ("musteri-ozeti.html" if lang == "tr" else "client-brief.html")
        pdf_path = html_path.with_suffix(".pdf")
        html_path.write_text(out.html, encoding="utf-8")
        try:
            over = render.render(html_path, pdf_path, [])
        except Exception as exc:  # no Chromium or no Playwright on this computer
            out.blocked, out.reasons, out.details = True, [_reason(lang, "browser")], [f"{type(exc).__name__}: {exc}"]
            return out
        if over:
            out.blocked = True
            out.reasons = [_reason(lang, "overflow", found=", ".join(dict.fromkeys(over)))]
            out.details = list(dict.fromkeys(over))
            return out
        n, text = _pdf_text(pdf_path)
        out.pages = n
        errors = check(b, pages=n, pdf_text=text)
        if lang == "tr" and not any(ch in text for ch in "ğüşıöçİĞÜŞÖÇ"):
            errors.append({"kind": "pdf", "found": "no Turkish letters in the PDF text"})
        if n != page_count(b):
            errors.append({"kind": "pdf", "found": f"{n} pages, {page_count(b)} expected"})
        if errors:
            return _blocked(out, lang, errors)
        out.pdf = pdf_path.read_bytes()
        if previews:
            render.write_previews(pdf_path, Path(tmp) / "png")
            out.previews = [p.read_bytes() for p in sorted((Path(tmp) / "png").glob("*.png"),
                                                           key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))]
    return out


def _blocked(out: Brief, lang: str, errors: list[dict]) -> Brief:
    out.blocked = True
    for x in errors:
        reason = _reason(lang, x["kind"], found=x.get("found", ""), pages=str(x.get("pages", "")))
        if reason not in out.reasons:
            out.reasons.append(reason)
        out.details.append(f"{x['kind']}: {x.get('found', '')}")
    return out


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--lang", required=True, choices=("tr", "en"))
    ap.add_argument("--pdf", required=True, help="where to write the PDF")
    ap.add_argument("--html", default=None, help="also write the HTML")
    ap.add_argument("--png", default=None, help="a folder for page previews")
    ap.add_argument("--review", default=None, help="the audit's review file (default: beside report.json)")
    ap.add_argument("--audit-id", default=None)
    a = ap.parse_args(argv)
    result = build(Path(a.report), a.lang, review_path=Path(a.review) if a.review else None, audit_id=a.audit_id,
                   previews=bool(a.png))
    if result.html and a.html:
        Path(a.html).write_text(result.html, encoding="utf-8")
    if result.blocked:
        print(library(a.lang)["blocked"]["title"])
        for line in result.reasons:
            print(f"  - {line}")
        for line in result.details:
            print(f"    {line}")
        return 1
    Path(a.pdf).write_bytes(result.pdf)
    print(f"PDF: {a.pdf} ({result.pages} sayfa)" if a.lang == "tr" else f"PDF: {a.pdf} ({result.pages} pages)")
    if a.png:
        folder = Path(a.png)
        folder.mkdir(parents=True, exist_ok=True)
        for i, png in enumerate(result.previews, 1):
            (folder / f"sayfa{i}.png").write_bytes(png)
        print(f"PNG: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
