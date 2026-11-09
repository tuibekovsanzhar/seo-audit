"""How long an audit took, in total and step by step (DECISIONS 329), from what a report already records.

The engine writes a step timing table (`crawl.steps`, DECISIONS 219/294/328): one row per step with its seconds, the
steps that run beside others marked (`beside`, the page reader, links to other sites). The total is the audit's own
wall time (`crawl.elapsed_s`, from the first request to the end of Maya's own steps) plus what came after it: the
results worked out, the page reader's copies applied and the report written (`generation.processed_at` less
`generation.native_finished_at`). Nothing is measured again and nothing is estimated; a report without a step table
says so (None).

Used by the web app's "How the audit ran" and the team report's coverage section, in Turkish and English.
"""
from __future__ import annotations

from datetime import datetime

# Steps in the order an audit runs them; any other step keeps its own id.
LABELS = {
    "sitemap": {"tr": "site haritasını okuma", "en": "reading the sitemap"},
    "crawl": {"tr": "sayfaları okuma", "en": "reading pages"},
    "other_sites": {"tr": "başka sitelere bağlantılar", "en": "links to other sites"},
    "access": {"tr": "erişim kontrolleri", "en": "access checks"},
    "index": {"tr": "dizine eklenme kontrolleri", "en": "indexing checks"},
    "structure": {"tr": "sayfa yapısı", "en": "page structure"},
    "render": {"tr": "sayfaları tarayıcıda açma", "en": "opening pages in a browser"},
    "sitemap_check": {"tr": "site haritasındaki adresleri kontrol", "en": "checking the sitemap's addresses"},
    "sitemap_check_wait": {"tr": "yandaki adımları bekleme", "en": "waiting for the steps beside"},  # DECISIONS 330: every lane
    "performance": {"tr": "yanıt süreleri", "en": "response times"},
    "llms_links": {"tr": "llms.txt bağlantıları", "en": "llms.txt links"},
    "llms_links_other_sites": {"tr": "llms.txt'nin başka sitelere bağlantıları", "en": "llms.txt's links to other sites"},
    "robots_wait": {"tr": "robots.txt örneklerini bekleme", "en": "waiting for the robots.txt samples"},
    "other_sites_wait": {"tr": "başka site bağlantılarını bekleme", "en": "waiting for the links to other sites"},
    "page_reader": {"tr": "Firecrawl ile okuma", "en": "reading through Firecrawl"},
    "finishing": {"tr": "sonuçlar ve rapor", "en": "results and the report"},
    "finishing_reader": {"tr": "sonuçlar, Firecrawl kopyaları ve rapor", "en": "results, Firecrawl's copies and the report"},
}
# Steps that run beside the audit's own thread: their time is not added to the total.
BESIDE = frozenset({"other_sites", "sitemap_check", "page_reader"})
WORDS = {"tr": {"total": "Denetim süresi", "beside": "yanında", "min": "dk", "s": "sn"},
         "en": {"total": "Audit time", "beside": "beside them", "min": "min", "s": "s"}}


def _at(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def summary(report: dict) -> dict | None:
    """{"total_s", "steps": [{"id", "seconds", "beside"}], "basis"} or None when the report has no step table."""
    crawl = report.get("crawl") or {}
    steps = [s for s in crawl.get("steps") or [] if isinstance(s, dict) and isinstance(s.get("seconds"), (int, float))]
    if not steps:
        return None
    gen = report.get("generation") or {}
    rows = [{"id": str(s.get("step")), "seconds": round(float(s["seconds"]), 1),
             "beside": bool(s.get("beside")) or s.get("step") in BESIDE} for s in steps]
    own = crawl.get("elapsed_s")
    if not isinstance(own, (int, float)):
        own = sum(r["seconds"] for r in rows if not r["beside"])
    end, done = _at(gen.get("native_finished_at") or crawl.get("finished_at")), _at(gen.get("processed_at"))
    finishing = (done - end).total_seconds() if end and done and done >= end else None
    if finishing is not None and finishing >= 1:
        rows.append({"id": "finishing", "seconds": round(finishing, 1), "beside": False})
    total = float(own) + (finishing or 0.0)
    return {"total_s": round(total, 1), "steps": rows, "reader_used": bool((report.get("firecrawl") or {}).get("used")),
            "basis": "the report's step timing table (crawl.steps), Maya's own wall time (crawl.elapsed_s) and the time "
                     "from the end of Maya's steps to the report (generation.processed_at)"}


def duration(seconds: float, lang: str = "tr") -> str:
    """'21 dk 4 sn' / '21 min 4 s'; under a minute, seconds only."""
    w = WORDS.get(lang, WORDS["tr"])
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    if not minutes:
        return f"{secs} {w['s']}"
    return f"{minutes} {w['min']} {secs} {w['s']}" if secs else f"{minutes} {w['min']}"


def label(step: str, lang: str = "tr") -> str:
    return (LABELS.get(step) or {}).get(lang) or step


def rows(info: dict | None, lang: str = "tr") -> list[dict]:
    """The steps as display rows: {"id", "label", "seconds", "time", "beside"}."""
    reader = bool((info or {}).get("reader_used"))
    return [{"id": r["id"], "label": label("finishing_reader" if r["id"] == "finishing" and reader else r["id"], lang),
             "seconds": r["seconds"], "time": duration(r["seconds"], lang), "beside": r["beside"]}
            for r in (info or {}).get("steps") or []]


def text(info: dict | None, lang: str = "tr") -> str | None:
    """One line: 'Denetim süresi 21 dk 4 sn: site haritasını okuma 16 sn · sayfaları okuma 6 dk 34 sn · …; yanında:
    site haritasındaki adresleri kontrol 3 dk 57 sn · Firecrawl ile okuma 7 dk 28 sn.'"""
    if not info:
        return None
    w = WORDS.get(lang, WORDS["tr"])
    shown = rows(info, lang)
    main = " · ".join(f"{r['label']} {r['time']}" for r in shown if not r["beside"])
    beside = " · ".join(f"{r['label']} {r['time']}" for r in shown if r["beside"])
    line = f"{w['total']} {duration(info['total_s'], lang)}: {main}"
    return line + (f"; {w['beside']}: {beside}." if beside else ".")
