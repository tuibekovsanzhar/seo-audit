"""Maya Audit report.json (şema 1.x) -> cards.json TASLAĞI.

Deterministik kısım: önem kuralları, kapsam, içerik tarihleri, KPI'lar, taslak puan,
önceki denetimle fark, kart iskeleti (Maya'nın İngilizce metinleri _draft içinde).
Türkçe başlık / adımlar / "ne yazılmalı" alanlarını model doldurur (SKILL.md, adım 3).

Kullanım:
  python from_maya_report.py report.json -o cards.json [--previous eski_report.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .reliability import assessment, page_facts, compare_reports, fully_verified
from ..report import finding_counts

HERE = Path(__file__).resolve().parent
REFS = HERE / "references"
SEV_ORDER = ["S1", "S2", "S3", "S4", "Info"]


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sev_rank(s):
    return SEV_ORDER.index(s) if s in SEV_ORDER else len(SEV_ORDER)


def stronger(a, b):
    return a if sev_rank(a) <= sev_rank(b) else b


def all_findings(report):
    for chk in report.get("checks") or []:
        for f in chk.get("findings") or []:
            yield chk, f


def apply_rules(f, rules):
    """(yeni_önem, kural_etiketi, bilinçli_olabilir, puanlanır_mı)

    Bir rapor kuralı önemi yalnızca düşürebilir (H25/B01): motorun verdiğinden daha yüksek bir önem müşteri raporunda
    görünmez, böylece teknik rapor ile müşteri raporu aynı bulgu için çelişen önem göstermez. Eski bir kural dosyasındaki
    `min_severity` yok sayılır."""
    sev = f.get("severity", "Info")
    if ((f.get('check_id') == 'TSEO-1' and 'guidance band' in (f.get('title') or '')) or
            (f.get('check_id') == 'RND-7' and 'main content' in (f.get('title') or ''))):
        return 'Info', 'Editoryal gözlem; teknik hata kanıtı değildir', False, False
    title = f.get("title") or ""
    urls = ((f.get("scope") or {}).get("urls")) or []
    applied, intentional, scored = None, False, sev != "Info"
    for r in rules:
        if not r.get("enabled", True):
            continue
        m = r["match"]
        if m.get("check_ids") and f.get("check_id") not in m["check_ids"]:
            continue
        if m.get("title_regex") and not re.search(m["title_regex"], title):
            continue
        if m.get("exclude_regex") and re.search(m["exclude_regex"], title):
            continue
        if m.get("all_urls_regex") and not (urls and all(re.search(m["all_urls_regex"], u) for u in urls)):
            continue
        new = r.get("set_severity", sev)
        if sev_rank(new) < sev_rank(sev):  # daha ciddi: motorun önemini aşamaz
            new = sev
        if new != sev:
            applied = r["label"]
        sev = new
        intentional = intentional or r.get("could_be_intentional", False)
        scored = r.get("scored", scored)
        break
    return sev, applied, intentional, scored


def find_dates(obj, out):
    """content_dates için: bölümlerdeki ISO tarihleri ve 'kayıtlı kopya' işaretlerini topla."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v) and any(t in k.lower() for t in ("date", "_at", "fetched", "observed", "data_from")):
                out["dates"].add(v[:10])
            if k.lower() in ("from_cache", "cached", "served_from_cache") and v:
                out["cached"] = True
            find_dates(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_dates(v, out)


def coverage(report):
    crawl = report.get("crawl") or {}
    st = (report.get("audit_status") or {}).get("content_coverage") or {}
    pages_read = st.get("pages_read")
    cap = (crawl.get("config") or {}).get("max_pages")
    sm = crawl.get("sitemap_urls")
    sm_n = len(sm) if isinstance(sm, list) else sm
    checked = None
    for chk in report.get("checks") or []:
        if chk.get("check_id") == "IDX-5":
            ev = chk.get("evidence") or {}
            # şema 1.14: evidence.urls_listed / listed_urls_assessed (evidence sürüm güvencesi dışında: savunmacı oku)
            if isinstance(ev.get("urls_listed"), int):
                sm_n = sm_n or ev["urls_listed"]
            for key in ("listed_urls_assessed", "sitemap_checked", "urls_checked"):
                if isinstance(ev.get(key), int):
                    checked = ev[key]
                    break
            for f in chk.get("findings") or []:
                m = re.search(r"(\d+) of (\d+) sitemap URLs? checked", f.get("title") or "")
                if m:
                    checked = int(m.group(1))
    not_read = st.get("known_urls_not_read")
    if not_read is None:
        nf = crawl.get("not_fetched_urls")
        not_read = len(nf) if isinstance(nf, list) else nf
    parts = []
    if sm_n:
        parts.append(f"Sitemap'teki {sm_n} adresin {pages_read if pages_read is not None else '?'} tanesi içerik olarak okundu")
        if checked is not None:  # bilinmiyorsa durum kontrolü hakkında hiçbir şey söylenmez
            parts.append(f"{checked} tanesinin durum kodu kontrol edildi")
    else:
        parts.append(f"{pages_read if pages_read is not None else '?'} sayfa okundu")
    if not_read:
        parts.append(f"{not_read} keşfedilen adres okunmadı")
    return {"pages_read": pages_read, "pages_cap": cap, "sitemap_urls": sm_n,
            "sitemap_checked": checked, "discovered_not_read": not_read, **assessment(report),
            "line": "; ".join(parts) + "."}


def page_facts_from_report(report):
    """Native readable metadata and separate provider observations; body text is not serialized."""
    return page_facts(report)


def unverified_scored(cards):
    """Puana girecek önemde olup canlı doğrulanmamış (launch-gated) kartlar: puandan çıkarılır ve sayıları söylenir."""
    return [c for c in cards if c.get('_scored', True) and (c.get('maya') or {}).get('severity_report') != 'Info'
            and (c.get('maya') or {}).get('launch_gated') and not fully_verified(c)]


def score(cards, cov, cfg):
    """Taslak puan, kontrol başına bir kez (CR-20): kontrolün en ciddi önemi × (taban + (1 − taban) × pay); pay, kontrolün
    kartlarının TEKİL adresleri / kontrolün değerlendirdiği sayfa. Bölünmüş bulgu (kırık hedef başına bir kart) puanı
    şişirmez. Doğrulanmamış kartlar puana girmez ama puanı da boşa çıkarmaz (CR-21, Kural 8): `unverified_scored`
    sayısı kapsam cümlesinde söylenir. Puan kontrolün ilk kartında gösterilir, diğer kartlarında None."""
    w, floor, cap = cfg["weights"], cfg["share_floor"], cfg["cap_per_check"]
    for c in cards:
        c["points"] = None
    if cov.get("score_status") == "unavailable" or not cov.get("pages_read") or not cov.get("assessed_checks"):
        return None, {}
    if unverified_scored(cards):
        return None, {}  # preserve local safety: required unverified evidence cannot produce a healthy total
    excluded = {id(c) for c in unverified_scored(cards)}
    counted = [c for c in cards if c.get('_scored', True) and id(c) not in excluded
               and (c.get('maya') or {}).get('severity_report', 'Info') != 'Info']
    denominators = cov.get('check_denominators') or {}
    if any(not denominators.get((c.get('maya') or {}).get('check_id')) for c in counted):
        return None, {}  # bulgu kapsamının değerlendirme kanıtı eksik: tahmin edilen bir payda kullanılmaz
    by_check = {}
    for c in counted:
        by_check.setdefault((c.get("maya") or {}).get("check_id", c["id"]), []).append(c)
    per_check = {}
    for chk, members in by_check.items():
        base = denominators[chk]
        worst = min((m["maya"].get("severity_report", "Info") for m in members), key=sev_rank)
        if any((m.get("where") or {}).get("group") == "site geneli" for m in members):
            share = 0.5
        else:
            urls = {u for m in members for u in (m.get("where") or {}).get("affected_urls") or (m.get("where") or {}).get("examples") or []}
            # Kayıtlı liste eksikse (yalnız örnek adresler) en büyük kart kapsamı alt sınırdır; kartlar asla toplanmaz.
            affected = max([len(urls)] + [(m.get("where") or {}).get("count") or 1 for m in members])
            share = min(1.0, affected / max(base, 1))
        per_check[chk] = min(cap, w.get(worst, 0) * (floor + (1 - floor) * share))
        members[0]["points"] = round(per_check[chk], 1)
    return max(0, round(cfg["start"] - sum(per_check.values()))), per_check


def diff(cur, prev):
    return compare_reports(cur, prev)


def convert(rep, previous=None):
    from ..findings import is_hygiene
    ver = str(rep.get("schema_version", "?"))
    if not ver.startswith("1."):
        raise ValueError(f"Desteklenmeyen şema sürümü: {ver} (bu dönüştürücü 1.x okur)")
    rules_cfg = load_json(REFS / "onem_kurallari.json")
    cat = load_json(REFS / "kontrol_katalogu.json")
    labels = rules_cfg["severity_labels"]
    order = {fid: i for i, fid in enumerate(rep.get("findings_in_priority_order") or [])}
    cov = coverage(rep)
    crawl = rep.get("crawl") or {}

    cards = []
    from ..judgments import qualify, sitemap_states
    decisions = sitemap_states(crawl)
    for chk, original in all_findings(rep):
        f = qualify(original, sitemap=decisions)
        new_sev, rule, intentional, scored = apply_rules(f, rules_cfg["rules"])
        scope = f.get("scope") or {}
        cid = f.get("check_id") or chk.get("check_id")
        entry = cat["checks"].get(cid) or cat["checks"].get(cid.split("-")[0] + "-1", {})
        src = cat["G"].get(entry.get("src", "none"), cat["G"]["none"])
        raw_lg = f.get("launch_gated") or []
        # Yalnızca LG-xx kimlikleri "doğrulanmamış kontrol" demektir; serbest metinler (bot rol notları) not olarak kalır
        lg = [x for x in raw_lg if re.match(r"^LG-\d+$", str(x))]
        from ..evidence_quality import qualifications
        limits = qualifications(f)
        lg_notes = [x for x in raw_lg if x not in lg] + limits
        kind = scope.get("kind")
        content_check = cid.split("-")[0] in ("STR", "RND", "TSEO") or cid == "IDX-8"
        of = cov["sitemap_checked"] if cid == "IDX-5" else (cov["pages_read"] if content_check and kind != "sitewide" else None)
        cards.append({
            "id": f.get("id"),
            "counting": finding_counts(f),
            "judgment": f["evidence"]["judgment"],
            "action_metadata": f["evidence"]["judgment"]["action"],
            "title": None,
            "severity": labels.get(new_sev, new_sev),
            "maya": {"check_id": cid, "severity": f.get("severity"), "severity_report": new_sev,
                     "finding_ids": [f.get("id")], "source": (f.get("evidence") or {}).get("source"), "launch_gated": lg, "notes": lg_notes, "confidence": f.get("confidence"), "evidence_limits": limits,
                     # Site-wide hygiene with a fix (G25): the compact appendix lists these short and capped.
                     "hygiene": is_hygiene(f)},
            "rule_applied": rule,
            "could_be_intentional": intentional or bool(f.get("intent")),
            "where": {"count": scope.get("count"),
                      "of": of,
                      "of_label": None,
                      "examples": (scope.get("urls") or [])[:5], "affected_urls": scope.get("urls") or [],
                      "csv": None,
                      "group": "site geneli" if scope.get("kind") == "sitewide" else ("şablon" if scope.get("kind") == "template" else None)},
            "why": {"text": entry.get("why"), "source_url": src[0], "source_label": src[1]},
            "steps": [],
            "what_to_write": {"text": None, "code": None, "derived_from": [], "decide": None},
            "verify": None,
            "depends_on": None,
            "evidence": {"snippet": None, "read_at": (f.get("observed_at") or "")[:10] or None,
                         "verified_live": None, "verification": []},
            "owner": {"developer":"Geliştirici","content":"İçerik","seo":"SEO"}.get(f["evidence"]["judgment"]["action"].get("owner"), entry.get("owner", "Geliştirici")),
            "effort": {"S":"Küçük","M":"Orta","L":"Büyük"}.get(f["evidence"]["judgment"]["action"].get("effort")),
            "_scored": scored,
            "_needs_live_check": bool(lg) and new_sev != "Info",
            "_order": order.get(f.get("id"), 10**6),
            "_draft": {"title_en": f.get("title"), "how_to_fix_en": f.get("how_to_fix"),
                       "expected_en": f.get("expected"), "notes_en": list(f.get("notes") or []) + limits,
                       "evidence_raw": f.get("evidence")},
        })

    cards.sort(key=lambda c: (sev_rank(c["maya"]["severity_report"]), c["_order"]))
    sc, per_check = score(cards, cov, rules_cfg["score"])
    if sc is None and cov['score_status'] != 'unavailable':
        cov['score_status'] = 'unavailable'
        cov['score_reason'] = 'Puan hesaplanamadı: gerekli doğrulanmamış bulgular veya eksik değerlendirme kanıtı var.'
    left_out = len(unverified_scored(cards))
    if sc is not None and left_out:
        cov['score_reason'] += f' {left_out} doğrulanmamış bulgu puana dahil değil.'

    # Ana bölüm: kontrol başına en çok bir kart (CR-04); aynı kontrolün diğer kartları ektedir ve ana kart onları sayar.
    # Doğrulanmamışlar ve notlar ektedir (render öncesi validate yeniden uygular).
    main, appx, seen = [], [], set()
    for c in cards:
        lg = c["maya"]["launch_gated"]
        sev = c["maya"]["severity_report"]
        if sev == "Info" or lg or len(main) >= 10 or c["maya"]["check_id"] in seen:
            appx.append(c)
        else:
            main.append(c)
            seen.add(c["maya"]["check_id"])

    dates = {"dates": set(), "cached": False}
    find_dates(rep.get("dataforseo") or {}, dates)
    sd = sorted(dates["dates"])
    fc = {"dates": set(), "cached": False}
    find_dates(rep.get("firecrawl") or {}, fc)
    audit_date = (crawl.get("started_at") or "")[:10]
    content_dates = {"pages": (min(fc["dates"]) if fc["dates"] else audit_date) + (" (kısmen kayıtlı kopya)" if fc["cached"] else "")}
    if sd:
        content_dates["search_data"] = sd[0] + (" (kayıtlı kopya)" if dates["cached"] or sd[0] < audit_date else "")

    ps = rep.get("problem_summary") or {}
    bysev = ps.get("by_severity") or {}
    out = {
        "contract_version": 2,
        "meta": {"site": crawl.get("origin") or crawl.get("start_url"),
                 "brand": (rep.get("brand") or {}).get("name"),
                 "audit_date": audit_date, "content_dates": content_dates,
                 "source": f"maya-report.json (şema {ver})", "language": "tr"},
        "coverage": cov,
        "score": {"value": sc, "status": cov["score_status"], "scope": cov["score_reason"], "draft": True, "lost_by_check": {k: round(v, 1) for k, v in per_check.items()}},
        # Taslak puan KPI kutusunda değil, kapakta "taslak" etiketiyle durur (H25): kalibre edilmemiş bir sayı
        # raporun ilk kutusu olmamalı.
        "kpis": [
            {"label": "Önce doğrulanacak bulgu", "value": str(sum(1 for c in cards if c.get("_needs_live_check"))),
             "note": "Henüz gerçek sitelerde doğrulanmamış kontroller; elle teyit edilmeden uygulanmamalı."},
            {"label": "Kritik + yüksek sorun", "value": str(sum(1 for c in cards if c["maya"]["severity_report"] in ("S1", "S2"))), "note": "Bulgu sayısıdır; ölçülmeyen kontrollerde sıfır sorun anlamına gelmez."},
            {"label": "Okunan sayfa", "value": (str(cov['pages_read']) if cov['pages_read'] is not None else "Bilinmiyor") + (f" / {cov['sitemap_urls']}" if cov.get("sitemap_urls") else ""), "note": "sitemap adresi" if cov.get("sitemap_urls") else None},
        ],
        "summary": {"one_read": None, "bullets": []},
        "cards": main,
        "appendix_cards": appx,
        "changes_since_last": diff(rep, previous) if previous is not None else None,
        "manual_checks": [],
        "not_measured": [{"what": c.get("title"), "why": c.get("summary"), "how_to_enable": None, "_needs_tr": True}
                         for c in rep.get("checks") or [] if c.get("status") == "not_assessed"],
        "page_facts": page_facts_from_report(rep),
        "_maya_counts": {"by_severity": bysev, "problems": ps.get("problems")},
    }
    for check in rep.get('checks') or []:
        gaps = (check.get('evidence') or {}).get('unassessed_image_roles') or []
        if gaps:
            out['not_measured'].append({'what': 'Image purpose not assessed',
                'why': f'{len(gaps)} görselin rolü değerlendirilmedi. Dosya adı, figure sarmalayıcısı ve doğal boyut amaç kanıtı değildir; CSS, görüntü ve eşdeğer yazılı içerik incelemesi gereklidir.',
                'how_to_enable': 'Ek kanıt listesindeki görselleri gösterildikleri boyutta ve işlevleriyle incelemelisiniz.'})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("-o", "--out", default="cards.json")
    ap.add_argument("--previous")
    args = ap.parse_args()
    out = convert(load_json(args.report), load_json(args.previous) if args.previous else None)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"{args.out}: draft; editorial review required.")


if __name__ == "__main__":
    main()
