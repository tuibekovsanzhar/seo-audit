"""cards.json -> müşteri raporu (tek dosya HTML + PDF).

Inter fontu (Türkçe karakterler dahil) HTML'e gömülür; PDF'te Türkçe metin kopyalanabilir/aranabilir kalır.
PDF önce Playwright (Chromium) ile, olmazsa yerel Chrome/Edge (headless) ile basılır.
Basımdan sonra PDF'ten metin çıkarılır ve Türkçe karakterlerin bozulmadığı denetlenir.

Kullanım:
  python render_report.py cards.json -o rapor.html [--pdf rapor.pdf] [--no-group]

Varsayılan çıktı web uygulamasının kısa (compact) müşteri raporuyla aynıdır: ana bölümde kontrol başına bir kart, ek
bölümü tablo, aynı onarımı paylaşan üç ve daha fazla bulgu tek blok (H40). `--no-group` her ek kartını tam basar.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

from .validate_cards import validate
from .reliability import verification, fully_verified
from ..report_layout import DRAFT_MARKER, DRAFT_WARNING
from .inter_b64 import INTER_FACES  # noqa: E402

E = lambda s: html.escape(str(s)) if s is not None else ""
# The exported file is opened from disk, where the app's Content-Security-Policy header does not exist (D-26): the same
# policy travels inside the page. Nothing loads from outside it; styles and the font are inline.
CSP = "default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'"


def T(s):
    """Görünür metin: HTML kaçışı + `ters tırnak` içini kod olarak göster."""
    return re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", E(s))
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(.*)", s or "")
    if not m:
        return E(s)
    return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}{E(m.group(4))}"


def font_css():
    return "\n".join(
        f"@font-face{{font-family:'Inter';font-style:normal;font-weight:{w};font-display:swap;"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2');unicode-range:{rng};}}"
        for w, rng, b64 in INTER_FACES)


def pill(sev):
    return f'<span class="pill {E(sev)}">{E(sev)}</span>'


def short_url(u, site):
    if site and u.startswith(site.rstrip("/")):
        return u[len(site.rstrip("/")):] or "/"
    return u


def where_line(c):
    w = c.get("where") or {}
    parts = []
    if w.get("count") is not None:
        s = f"{w['count']}"
        if w.get("of"):
            s += f" / {w['of']}"
        if w.get("of_label"):
            s += f" {w['of_label']}"
        parts.append(s)
    if w.get("group") and w["group"] not in (w.get("of_label") or ""):
        parts.append(E(w["group"]))
    return " · ".join(parts)


def card_html(c, n, site, by_id, also=None):
    """One card in full. `also`: the other findings of the same check, in the appendix; the main section shows one card
    per check (CR-04) and says how many more there are."""
    chips = []
    records = verification(c)
    if records:
        count = len({r['url'] for r in records})
        total = (c.get('where') or {}).get('count')
        chips.append(f'<span class="chip ok">Canlı kontrol: {count} / {E(total)} adres · {tr_date(records[0]["checked_at"])}</span>')
    if c.get("could_be_intentional"):
        chips.append('<span class="chip warn">Bilinçli bir tercih olabilir</span>')
    mx = c.get("maya") or {}
    if c.get("rule_applied") and mx.get("severity"):
        chips.append(f'<span class="chip">Maya: {E(mx["severity"])} → rapor: {E(c["severity"])} · {E(c["rule_applied"])}</span>')
    why = c.get("why") or {}
    src = f'<a href="{E(why.get("source_url"))}">{E(why.get("source_label"))}</a>' if why.get("source_url") else E(why.get("source_label"))
    ex = "".join(f'<li><a href="{E(u)}">{E(short_url(u, site))}</a></li>' for u in list(dict.fromkeys((c.get("where") or {}).get("examples", [])))[:5])
    more = (c.get("where") or {}).get("count") or 0
    if more and more > len((c.get("where") or {}).get("examples", [])):
        ex += f'<li>… ve {more - len(c["where"]["examples"])} adres daha' + (f' (tam liste: {E(c["where"]["csv"])})' if c["where"].get("csv") else "") + "</li>"
    steps = "".join(f"<li>{T(s)}</li>" for s in c.get("steps") or [])
    w = c.get("what_to_write") or {}
    if w.get("items"):
        rows = "".join(
            f"<tr><td>{E(short_url(it.get('url',''), site))}<div class=small>{E(it.get('field'))}</div></td>"
            f"<td class=small>{E(it.get('current'))}</td><td><b>{E(it.get('proposed'))}</b>"
            f"<div class=small>{len(it.get('proposed') or '')} karakter</div></td></tr>" for it in w["items"])
        extra = f"<div class='src'>{E(w['text'])}</div>" if w.get("text") else ""
        write = (f'<div class="write"><table><thead><tr><th>Sayfa</th><th>Şu an</th><th>Önerilen</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>{extra}<div class="src">Kaynak izlenebilirliği denetlendi; anlamsal doğruluk inceleyen kişinin sorumluluğundadır.</div></div>')
    elif w.get("text") or w.get("code"):
        body = (f"<div>{E(w['text'])}</div>" if w.get("text") else "") + (f"<pre>{E(w['code'])}</pre>" if w.get("code") else "")
        srcs = ", ".join(f'{E(short_url(r.get("url",""), site))} ({E(r.get("field"))})' for r in w.get("derived_from") or [])
        write = f'<div class="write">{body}<div class="src">Kaynak: {srcs}</div></div>'
    else:
        write = f'<div class="write decide">{T(w.get("decide"))}</div>'
    ev = c.get("evidence") or {}
    evid = f'<div class="lbl">Kanıt</div><pre>{E(ev.get("snippet"))}</pre>' if ev.get("snippet") else ""
    dep = c.get("depends_on")
    dep_txt = f' · Önce: “{E((by_id.get(dep) or {}).get("title", dep))}”' if dep else ""
    context = c.get('_source_context') or {}
    counts = c.get('counting')
    counting = ('<p class="small">Sayım birimleri: DOM oluşumu: ' + E(counts.get('occurrences') if counts.get('occurrences') is not None else 'belirlenemedi') +
                ' · Etkilenen sayfa: ' + E(counts.get('affected_pages')) + ' · Kaynak-hedef grubu: ' +
                E(counts.get('source_target_groups') if counts.get('source_target_groups') is not None else 'belirlenemedi') +
                ' · Şablon grubu: ' + E(counts.get('template_groups')) + '</p>') if counts else ''
    source_context = ('<div class="coverage"><b>Kayıtlı kaynak yargısı (editörden bağımsız)</b><p>' +
                      E(context.get('title')) + '</p><p>' + E(context.get('scope')) + ' · ' +
                      E(context.get('confidence')) + '</p>' +
                      ''.join('<p>' + E(note) + '</p>' for note in context.get('notes', [])) + '</div>') if context else ''
    return f"""
<section class="card {E(c.get('severity'))}" id="finding-{E(c.get('id'))}">
  <p class="small">Bulgu / Finding: {E(c.get('id'))}</p>
  <div class="head"><div>{pill(c.get('severity'))} <span class="small">{where_line(c)}</span></div>
  <h3><span class="no">{n}.</span>{T(c.get('title'))}</h3>
  <div class="meta">{''.join(chips)}</div></div>
  {source_context}
  {counting}
  <div class="grid2">
    <div><div class="lbl">Neden önemli</div><div>{T(why.get('text'))}</div><div class="small">{src}</div></div>
    <div><div class="lbl">Nerede</div><ul class="urls">{ex}</ul></div>
  </div>
  <div class="lbl">Nasıl düzeltilir</div><ol>{steps}</ol>
  <div class="lbl">Ne yazılmalı / ne değişmeli</div>{write}
  <div class="lbl">Nasıl doğrularsınız</div><div>{T(c.get('verify'))}</div>
  {evid}
  {also_line(also)}
  <div class="foot">Sorumlu: {E(c.get('owner'))} · Efor: {E(c.get('effort'))} (tahmin){dep_txt}</div>
</section>"""


def also_line(also):
    if not also:
        return ""
    names = ", ".join(f'<a href="#finding-{E(x.get("id"))}">{E(x.get("id"))}</a>' for x in also[:10])
    more = f" ve {len(also) - 10} bulgu daha" if len(also) > 10 else ""
    return f'<p class="small">Aynı kontrolden {len(also)} bulgu daha ekte: {names}{more}.</p>'


def also_serious(c, same_check, named=2):
    """The other S1-S3 findings of a main card's check, under its row of "Önce bunları düzeltin" (G25): the table is one
    row per check and must not hide a second Medium-or-worse finding of that check. Count and the first two titles."""
    if (c.get("maya") or {}).get("severity_report") not in ("S1", "S2", "S3"):
        return ""
    others = [x for x in same_check.get((c.get("maya") or {}).get("check_id")) or []
              if (x.get("maya") or {}).get("severity_report") in ("S1", "S2", "S3")]
    if not others:
        return ""
    # A draft card has no Turkish title yet: its finding ID, linked to its row, stands in.
    titles = "; ".join(T(x.get("title")) if x.get("title") else f'<a href="#finding-{E(x.get("id"))}">{E(x.get("id"))}</a>'
                       for x in others[:named])
    more = f" ve {len(others) - named} bulgu daha" if len(others) > named else ""
    return f'<div class="small">Aynı kontrolden ayrıca: {titles}{more}</div>'


def _build(d, *, draft=False, group_large=False):
    if not draft:
        errors, _, _ = validate(d)
        if errors:
            raise ValueError("Final rapor reddedildi:\n" + "\n".join(errors))
    m, cov = d["meta"], d["coverage"]
    site = m.get("site") or ""
    cards, appx = d.get("cards", []), d.get("appendix_cards", [])
    by_id = {c.get("id"): c for c in cards + appx}
    cd = m.get("content_dates") or {}
    dates = [f"<span>Denetim tarihi: <b>{tr_date(m.get('audit_date'))}</b></span>"]
    if cd.get("pages"):
        dates.append(f"<span>Sayfa içeriği: <b>{tr_date(cd['pages'])}</b></span>")
    if cd.get("search_data"):
        dates.append(f"<span>Arama verisi: <b>{tr_date(cd['search_data'])}</b></span>")
    kpis = "".join(
        f'<div class="kpi{" hero" if i == 0 else ""}"><div class="eyebrow">{E(k["label"])}</div><div class="v">{E(k["value"])}</div>'
        f'<div class="n">{E(k.get("note") or "")}</div></div>' for i, k in enumerate(d.get("kpis", [])))
    bullets = "".join(f"<li>{T(b)}</li>" for b in (d.get("summary") or {}).get("bullets", []))
    maxp = max([c.get("points") or 0 for c in cards] + [1])
    def pts_cell(c):
        p = c.get("points")
        if not p:
            return ""
        return f'−{p}<span class="bar" style="width:{int(40 * p / maxp)}px"></span>'

    same_check = {}
    for c in appx:
        same_check.setdefault((c.get("maya") or {}).get("check_id"), []).append(c)
    fixfirst = "".join(
        f"<tr><td class='num'>{i}</td><td>{T(c.get('title'))}{also_serious(c, same_check)}</td><td>{pill(c.get('severity'))}</td>"
        f"<td class='num'>{E((c.get('where') or {}).get('count') or '–')}</td><td>{E(c.get('owner'))} · {E(c.get('effort'))}</td>"
        f"<td class='num'>{pts_cell(c)}</td></tr>"
        for i, c in enumerate(cards, 1))
    shown, shared = cards, []
    if group_large:
        # A qualification every card carries ("intent, client behaviour, sampling … may change the interpretation") is
        # said once above the cards, not in each (H35); a card's own notes stay in it. The saved cards are not changed.
        counts = {}
        for c in cards:
            for note in dict.fromkeys((c.get("_source_context") or {}).get("notes") or []):
                counts[note] = counts.get(note, 0) + 1
        shared = [note for note, n in counts.items() if n >= 3]
        if shared:
            shown = [{**c, "_source_context": {**c["_source_context"], "notes": [x for x in c["_source_context"].get("notes") or []
                                                                                 if x not in shared]}}
                     if c.get("_source_context") else c for c in cards]
    card_blocks = "".join(card_html(c, i, site, by_id, also=same_check.get((c.get("maya") or {}).get("check_id")))
                          for i, c in enumerate(shown, 1))
    shared_notes = ('<div class="coverage"><b>Her kart için geçerli kaynak yargısı</b>' + "".join(f"<p>{E(x)}</p>" for x in shared)
                    + '</div>') if shared else ""

    ch = d.get("changes_since_last")
    changes = ""
    if ch:
        col = lambda k, cls, h: f'<div class="col {cls}"><h4>{h} ({len(ch.get(k, []))})</h4><ul>' + "".join(
            f"<li>{E(x.get('title'))}" + (f" — {E(x.get('reason'))}" if x.get('reason') else '') + (f" <span class=small>({x['count']})</span>" if x.get("count") else "") + "</li>" for x in ch.get(k, [])) + "</ul></div>"
        changes = (f'<h2>Önceki denetimden bu yana</h2><p class="lead">{tr_date(ch.get("previous_date"))} denetimiyle karşılaştırma.</p>'
                   f'<div class="cols3">{col("fixed", "fixed", "Yeni kanıtta giderilmiş")}{col("new", "new", "İlk gözlem")}{col("still_open", "open", "Hâlâ açık")}{col("unknown", "open", "Bilinmiyor / karşılaştırılamıyor")}</div>')

    manual = "".join(f"<tr><td>{E(x.get('what'))}</td><td>{E(x.get('where'))}</td></tr>" for x in d.get("manual_checks", []))
    notm = "".join(f"<tr><td>{E(x.get('what'))}</td><td>{E(x.get('why'))}</td><td>{E(x.get('how_to_enable'))}</td></tr>" for x in d.get("not_measured", []))
    appx_rows = "".join(
        f"<tr><td>{pill(c.get('severity'))}</td><td>{T(c.get('title'))}"
        + ("<div class=small>Doğrulanmamış kontrol: elle teyit edilmeden uygulanmamalı.</div>" if any(str(x).startswith("LG-") for x in ((c.get("maya") or {}).get("launch_gated") or [])) and not fully_verified(c) else "")
        + f"</td><td class='num'>{E((c.get('where') or {}).get('count') or '–')}</td><td>{T((c.get('steps') or [''])[0])}</td></tr>"
        for c in appx)
    if group_large:
        # Compact (the web default and the CLI default): one row per finding, shared repairs said once, no full cards
        # (CR-12). Every finding ID and address stays; complete cards are in the full export and its JSON.
        from .grouped import appendix as compact_appendix
        appendix = ('<div class="pagebreak"></div><h2>Ek: diğer bulgular</h2><p class="lead">Ana bölüm dışındaki bulgular, '
                    'bulgu kimliğiyle birer satırda. Aynı onarımı paylaşan üç ve daha fazla bulgu tek blokta; tam kartlar ve '
                    'kayıtlı kanıt tam ekte ve JSON ekindedir.</p>' + compact_appendix(appx, site, by_id, len(cards) + 1)) if appx else ''
    else:
        appendix = '<div class="pagebreak"></div><h2>Ek: diğer bulgular</h2><p class="lead">Ana bölüm dışındaki tüm bulgular aşağıda ayrıntılarıyla korunmuştur. Önemli bulgular burada da bulunabilir.</p><table><thead><tr><th>Önem</th><th>Bulgu</th><th>Adres</th><th>İlk adım</th></tr></thead><tbody>'+appx_rows+'</tbody></table>'+''.join(card_html(c,i,site,by_id)for i,c in enumerate(appx,len(cards)+1))
    score = d.get("score") or {}
    # The draft score is said on the cover, labelled as a draft, and never in a KPI box (H25).
    score_line = (f"<br>Taslak puan (ağırlıklar kalibre edilmedi): {E(score['value'])}/100"
                  if isinstance(score.get("value"), (int, float)) else "")
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
{DRAFT_MARKER if draft else ''}<title>{E(m.get('brand'))} · Teknik SEO denetimi</title><style>{font_css()}\n{(HERE / 'assets' / 'rapor.css').read_text(encoding='utf-8')}</style></head>
<body><div class="wrap">
{'<div class="draft-warning">'+DRAFT_WARNING+'</div>' if draft else ''}
<header class="cover">
  <div class="eyebrow"><span class="brandtab"></span>Maya · Teknik SEO ve AI görünürlük denetimi</div>
  <h1>{E(m.get('brand'))}</h1><div class="site">{E(site)}</div>
  <div class="dates">{''.join(dates)}</div>
  <div class="coverage">{E(cov.get('line'))}<br>{E(cov.get('score_reason'))}{score_line}</div>
</header>
<div class="kpis">{kpis}</div>
<div class="eyebrow">Tek okumada</div>
<p class="oneread">{T((d.get('summary') or {}).get('one_read'))}</p>
<ul class="bullets">{bullets}</ul>
<h2>Önce bunları düzeltin</h2>
<p class="lead">Sıra, sorunun ciddiyetine ve etkilediği sayfa oranına göre. Puan sütunu her sorunun taslak puandan ne kadar düşürdüğünü gösterir.</p>
<table><thead><tr><th>#</th><th>Sorun</th><th>Önem</th><th>Adres</th><th>Sorumlu · efor</th><th>Puan</th></tr></thead><tbody>{fixfirst}</tbody></table>
<h2>Sorunlar ve çözümleri</h2>
<p class="lead">Her kart: ne yanlış, nerede, neden önemli, adım adım nasıl düzeltilir, ne yazılmalı ve düzeltmenin nasıl doğrulanacağı.</p>
{shared_notes}
{card_blocks}
{changes}
<h2>Sizin kontrol etmeniz gerekenler</h2>
<p class="lead">Bu denetimin dışarıdan göremediği, sizin panellerinizden bakılması gereken noktalar.</p>
<table><thead><tr><th>Ne</th><th>Nereden</th></tr></thead><tbody>{manual}</tbody></table>
<h2>Ölçülmeyenler</h2>
<p class="lead">Ölçülmeyen alan puana dahil edilmez; sıfır sayılmaz.</p>
<table><thead><tr><th>Ne</th><th>Neden ölçülmedi</th><th>Nasıl açılır</th></tr></thead><tbody>{notm}</tbody></table>
{appendix}
<div class="footer">Kaynak: {E(m.get('source'))}. Puan {'taslaktır; ağırlıklar henüz kalibre edilmedi' if score.get('draft') else 'kalibre'}. Otomatik denetim anlamsal doğruluğu kanıtlamaz; öneriler insan/model incelemesi gerektirir. Bulgular okunan sayfalara aittir; okunmayan sayfalar için kanıt değildir. Rapor Maya tarafından hazırlandı.</div>
</div></body></html>"""


def to_pdf(html_path: Path, pdf_path: Path) -> str:
    # One guarded PDF implementation: no shell fallback and no external requests.
    from maya_audit_web.pdf import to_pdf as render_pdf
    pdf_path.write_bytes(render_pdf(html_path.read_text(encoding="utf-8")))
    return "offline Chromium"


def check_pdf_text(pdf_path: Path, d) -> list[str]:
    """PDF metin katmanında Türkçe kelimelerin bütün kaldığını denetler.
    PyMuPDF kullanılır; pypdf bazı Türkçe harfleri ayrı karakter olarak çıkardığı için yanıltıcıdır."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ["PyMuPDF (fitz) yok: PDF metin denetimi atlandı (pypdf Türkçe harfleri yanlış bölebildiği için kullanılmıyor)"]
    text = "\n".join(pg.get_text() for pg in fitz.open(str(pdf_path)))
    probs = []
    for c in d.get("cards", [])[:5]:
        for w in re.findall(r"\w*[çğışöüÇĞİŞÖÜ]\w*", c.get("title") or "")[:2]:
            if len(w) > 3 and w not in text:
                probs.append(f"PDF metninde bulunamadı (font gömülmemiş olabilir): {w}")
    if "\x00" in text:
        probs.append("PDF metninde karşılığı olmayan simge var (ikon fontu); kopyalanınca boş görünür")
    return probs


def build(d, draft=False, *, group_large=False):
    from ..report_layout import PRINT_CSS, prepare_tables
    return prepare_tables(_build(d, draft=draft, group_large=group_large).replace('</style>', PRINT_CSS+'</style>', 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards")
    ap.add_argument("-o", "--out", default="rapor.html")
    ap.add_argument("--pdf")
    ap.add_argument("--draft", action="store_true", help="Doğrulanmamış taslak, müşteriye gönderilmez")
    ap.add_argument("--no-group", action="store_true",
                    help="Kısa düzen yerine her ek kartını tam bas (varsayılan: web uygulamasının kısa müşteri raporu)")
    a = ap.parse_args()
    try:
        d = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(f"HATA: JSON okunamadı: {exc}")
    out = Path(a.out)
    try:
        rendered = build(d, draft=a.draft, group_large=not a.no_group)
    except (ValueError, TypeError, KeyError) as exc:
        sys.exit(str(exc))
    out.write_text(rendered, encoding="utf-8", newline="\n")
    print("HTML:", out)
    if a.pdf:
        how = to_pdf(out, Path(a.pdf))
        print(f"PDF: {a.pdf} ({how})")
        for p in check_pdf_text(Path(a.pdf), d):
            print("UYARI:", p)


if __name__ == "__main__":
    main()
