# The Ek as the team's full client file: plan (DECISIONS 376; approved by the owner on 2026-11-20 with the changes below)

Compared on 2026-11-20 with the newest copy of Efsa's final Enpara file (30 sheets, sent to the client on 13 Nov; the
file stays in ~/Downloads and is never committed) against our Ek for the same saved audit, rebuilt with the current
engine. Enpara is only the test case: every rule below is global, and the tests use synthetic data.

Status: **have** (we already make it, same columns), **partly** (we make part of it; the rest is listed),
**missing** (we make none of it). Phase: the build phase below (P1 to P6).

## What the file is made of

| Part of Efsa's file | Sheets | Where it came from |
|---|---|---|
| Our Ek of 12 Nov, unchanged except the frame | Nasıl okunur, Özet, Kilit sayfalar, Sayfa bazında, Bulgu bazında, Bulgular, Etkilenen adresler, Şablonlar, Bağlantı yerleri, Yönlendiren bağlantılar, Kontrol listesi özeti, Kontrol listesi, Kapsam, Yöntem | Maya Audit; Efsa added the Maya band, "← Kapak", the "Kaynak" line, and Search Console columns on three sheets |
| A Search Console / AI add-on of 12 Nov, made outside our code | Search Console özeti, Trafiğe göre öncelik, SC sayfaları, SC sorgular, SC fırsatlar, AI alıntılanan sayfalar | Maya's export plus Maya dashboard screenshots plus a separate Search Console download (`…search-console-verileri-2026-11-12.xlsx`) |
| Her competitor analysis | C1 Rakip - Konu, C2 Rakip - Sayfa yapısı, Rakip yöntem notları | Maya's export plus a live download of competitor pages; we already make "Rakip - Konu" and "Rakip - Sayfa yapısı" from the export |
| Built by hand for the client | Kapak, Yönetici özeti, Aksiyon planı, Uzman teyidi, Sayfa grupları, Konum dizini, Kaynak eşlemesi | Efsa, from the sheets above, the PDF booklet and her own review |

Our Ek has four sheets her file does not: Düzeltme kaydı and Kontrol raporu (ours, for the team), and, when Maya data is
attached, Genel durum, Organik×AI - Özet, Organik×AI - Segmentler, Sayfa detay (she left them out). See decision D1.

## Frame on every sheet (P1)

| Part | Status | Source | Phase |
|---|---|---|---|
| Row 1 Maya band: "maya · <Marka> SEO analizi · <sheet>" | missing | audit (brand name, sheet) | P1 |
| Row 2: "← Kapak" link + "Kaynak: … · dönem" | missing | each sheet's own source and period (below) | P1 |
| Header on row 3, frozen, filter | partly (header is row 1 today) | – | P1 |
| Cell colours: source (white) / computed or Maya text / expert or client input; green header for Search Console columns | missing | fixed rule per column | P1 |

## Sheet by sheet

### Kapak (missing, P1)

| Block | Status | Source |
|---|---|---|
| Title line, "Hazırlama tarihi … bu tarih ölçüm tarihi değildir" | missing | build date |
| "SEO uzmanı değerlendirmesinden geçmiştir (tarih)" | missing | expert input: written only when a review record says so (D5), else left out |
| Ne kapsanıyor / Ne kapsanmıyor | partly (Kapsam has the gaps) | Kapsam lines + Maya datasets present / missing (GA4, URL inspection, device…) |
| Kaynak dosyalar (file, what was used, note) | missing | the audit + each Maya export file read (name, dataset, rows) |
| Ölçüm dönemleri table (data, period, sheet), "toplanmaz, birleştirilmez" | missing | audit crawl date; each dataset's own period from its file name or rows |
| Renk göstergesi | missing | fixed text |
| Sekme rehberi: #, sheet (link), what it holds, group | missing | the sheets this Ek actually has |

### Yönetici özeti (missing, P4)

| Column | Status | Source |
|---|---|---|
| # · Bulgu | missing | picked automatically: top cards by priority, then the largest Search Console and AI findings that exist (5–7 rows; rule in P4) |
| Kanıt (sayı + birim + dönem) | missing | the number taken from the evidence row it links to, with unit and that source's period |
| Aksiyon (T-/S-/R- id) | missing | Aksiyon planı |
| Kanıt sekmesi (link to the row) | missing | internal link |
| Açık konular table (konu, neden, kim, yer) | missing | partly automatic: data gaps Maya detects (unread pages with clicks, AI-cited pages not read, counts that differ, missing datasets); "Kim" is a fixed role per gap |
| "Uzman onayı" row | missing | expert input (D5) |
| "Ölçü birimleri birleştirilmez" block | missing | fixed text, one row per unit present |

### Aksiyon planı (missing, P4) — 31 columns

| Column | Status | Source |
|---|---|---|
| Aksiyon kimliği | missing | T-nn per PDF card, S-nn per checklist item the Search Console data turns into a problem, R-nn per competitor topic |
| Grup, Konu, Sorun türü | partly | card title, issue type (Sorun / Kontrol edin / Fırsat); R-: topic name |
| Sorun veya fırsat (kaynak) | have (card text) | card / checklist evidence / topic insight |
| Önerilen işlem | have | Bulgular "Ne yapılmalı"; topic action for R- |
| İşlem metninin kaynağı | missing | fixed per kind |
| İş açısından gerekçe | partly | text library `why` per rule (exists for every rule); S-/R-: fixed text per kind |
| Kaynak önceliği, Öncelik türü | have (P0–P3) | card P0–P3; S-: the checklist item's priority; R-: gap rank (not P0–P3, said so) |
| Kaynak sorumlu, Kaynak efor | have | card owner and effort (team report); empty for R- (no source) |
| Kapsam (sayı), Kapsam birimi, Benzersiz URL | have | card counts; S-: query/page counts; R-: prompt count |
| İlk 3 URL | partly | card's affected addresses (first 3) |
| Tam liste (link) | missing | link to the first row in Etkilenen adresler / SC fırsatlar |
| Kaynak bulgu kimlikleri | have | finding ids / checklist id / topic |
| Kanıt, Ek kanıt (links) | missing | links to Bulgu bazında / SC sheet / C1, C2 rows |
| Ölçüm dönemi | missing | the source's period |
| Gösterge (n<10) | partly (C1 has it) | prompt count < 10 |
| Çapraz bağlantı / not | missing | automatic: S- and R- on the same pages or topic, T- on the same pages |
| SEO değerlendirmesi, Uzman notu, Onaylanan öncelik, Uygulama durumu, Hedef tarih | missing | expert / client input: empty, with a dropdown where the values are fixed (D5) |
| Doğrulama yöntemi | partly | text library `verify` per rule; S-/R-: fixed text per kind |
| Kitapçık sayfası (PDF), Kitapçıkta aç (HTML) | missing | the PDF page of the card, found in the printed team report (pypdf); HTML link only when a shared HTML exists (D4) |

### Uzman teyidi (missing, P4) — 14 columns

Rows: every "Kontrol edin" finding (we have them: unapproved rules, unverified checks), every checklist item whose
Search Console result differs from the crawl-only result, and differences between sources (e.g. a page cited by AI but
blocked in the audit). Columns: Tür, Kimlik, Kontrol/madde, Bulgu/kanıt, Önem, Güven sınıfı, Teyit nedeni, Araç
sonucu, SC eki önerilen sonuç, Ne yapılmalı, Kanıt (link), Kaynak satırı (link) — all from the audit and checklist;
SEO değerlendirmesi, Uzman notu — expert input, empty.

### Search Console özeti (missing, P3)

| Row | Status | Source in Maya's export | Without it |
|---|---|---|---|
| Kaynaklar (A, B, C, D) | missing | the files read, with periods | – |
| Tık, gösterim, CTR, ort. sıra (last 28 days and whole period) | missing | gsc-daily-stats (or gsc-search-performance), summed per day; position weighted by impressions | "Veri yok: günlük Search Console verisi eklenmedi" |
| Cihaz | missing | gsc-search-performance `device` | "Veri yok: dışa aktarımda cihaz kırılımı yok" (Enpara's export) |
| Ülke | missing | gsc-search-performance `country` | same |
| Sorgu niyeti, marka payı | partly (brand share in checklist SEO-008) | gsc-query-intents `intent`, `is_brand` (only the queries it lists, n said) | "Veri yok" |
| AI Overview | missing | gsc-daily-stats `aio_*` | "Veri yok: dışa aktarımda AI Overview sütunları boş" (Enpara: empty on all 88 days) |
| İndeks sağlığı (URL denetimi) | missing | not in the export | "Veri yok: Search Console URL denetimi dışa aktarımda yok" |
| GA4 | missing | ga4-traffic (Maya lists it; not seen in any export yet) | "Veri yok" |
| Denetim × Search Console (pages read, in SC list, SC pages not read, problem pages' click share, cannibalization count, AI-cited pages and how many not read) | missing | audit + gsc-top-pages/page-scores + opportunities + citation-mentions | rows left out |
| Dikkat notes (28-day windows never summed, etc.) | partly (rule exists in maya_data) | fixed text, shown only when that dataset is present | – |

### Trafiğe göre öncelik (missing, P3) — 11 columns

Sayfa, SC tık/gösterim/CTR/ort. sıra (28 gün), AI alıntı sayısı, Önem puanı, Sorun sayısı, En yüksek önem, Sorunlar,
Kartlar. Pages read with at least one problem, sorted by SC clicks. Audit + latest 28-day snapshot per page
(gsc-top-pages or gsc-page-scores) + citation-mentions.

### SC sayfaları (missing, P3) — 13 columns

Sayfa, Tık, Gösterim, CTR, Ort. sıra (28 gün), "İlk 200de (N ölçümden)", Ölçüm haftası, Sorgu sayısı, Otorite skoru,
AI alıntı sayısı, Denetimdeki durumu (okundu, sorun var / okundu, sorunsuz / okunmadı), Sorunlar, Kartlar.
gsc-top-pages (weekly 28-day snapshots: latest per page, number of weeks present), gsc-page-scores (`query_count`,
`authority_score`), citation-mentions, audit.

### SC sorgular (missing, P3) — 9 columns

Sorgu, Tık, Gösterim, CTR, Ort. sıra (28 gün), İlk 200de (N ölçümden), Ölçüm haftası, Niyet (Maya), Marka mı?
gsc-top-queries (latest snapshot per query) + gsc-query-intents (`intent`, `is_brand`; a query it does not list:
"sınıflanmadı"). Brand by our brand names when the intent file has no row.

### SC fırsatlar (missing, P3) — 9 columns

Sorgu, Marka/marka dışı, Fırsat türü, Gösterim, Yarışan sayfa sayısı, Sayfalar, Fırsat skoru, "Bu sayfalardan
denetimde sorunlu olanlar", Dönem. gsc-query-opportunities (`query`, `page` (pages joined with " | "),
`impressions`, `opportunity_score`, `opportunity_type`, `period_start`/`period_end`) + audit. Clicks and position are
0 in cannibalization rows: not shown as values ("Veri yok" in Search Console özeti's note). Sorted: non-brand first.
Also feeds checklist SEO-069 (new Maya measure) and SEO-071.

### AI alıntılanan sayfalar (missing, P3) — 8 columns

Sayfa (utm_* and #:~:text removed; we already clean tracking parameters), AI alıntı sayısı, Alıntılayan AI, Kaç soruda,
SC tık (28 gün), Denetimdeki durumu, Sorunlar, Kartlar. citation-mentions (`url`, `model`, `prompt_id`; own domain
only) over the export's period (D2).

### Sayfa grupları (missing, P4) — group › actions › address count, then the addresses

First path segment of every affected address of the T- actions, with the actions and a link per address to its
Bulgu bazında row. Audit only.

### Konum dizini (missing, P4) — 7 columns

Aksiyon, Konu, Aksiyon planı row (link), Kanıt rows (link to the first, range written), Ek kanıt, PDF page, HTML link.
Audit + the printed team report (D4).

### Sheets we already make (P1 frame only, unless said)

| Sheet | Status | Difference |
|---|---|---|
| Nasıl okunur | have | + lines for the new sheets (P3–P4) |
| Özet | have | ours has "Bağlantılar" and "Örnek" too (newer than her copy): kept |
| Kilit sayfalar | have | + SC tık/gösterim/CTR/sıra and AI alıntı when Maya data is attached (her copy has none; the owner asked for them) (P3) |
| Sayfa bazında | partly | + 8 columns: SC tık, gösterim, CTR, ort. sıra (28 gün), İlk 200de (N ölçümden), ölçüm haftası, AI alıntı sayısı, Alıntılayan AI (P3) |
| Bulgu bazında, Bulgular, Etkilenen adresler, Şablonlar, Bağlantı yerleri, Yönlendiren bağlantılar | have | frame only |
| Kontrol listesi | partly | today the Maya result replaces the crawl result in place; her file keeps both: + "Search Console eki: önerilen sonuç" and "Search Console kanıtı" (P3). Ours has 3 more columns (Nasıl kontrol edilir, Gereken veri, Otomatikleştirme önerisi): kept |
| Kontrol listesi özeti | partly | + rows "Search Console eki sonrası" and "Önceki (araç)" (P3) |
| Kapsam, Yöntem | have | + Maya data lines (exist); stamp last row of Yöntem (done, DECISIONS 375) |
| C1 Rakip - Konu | partly | ours "Rakip - Konu": same measures from the export; her columns renamed and ordered as hers; "İçgörü" and "Önerilen aksiyon" are our generated text, not hers (P5) |
| C2 Rakip - Sayfa yapısı | partly | ours measures pages already saved or fetched by `enrich`; from saved data alone competitor pages are "ölçülmedi" (no live fetch without a request) (P5) |
| Rakip yöntem notları | partly | our method lines exist inside Yöntem; moved to their own sheet when the competitor sheets are there (P5) |
| Kaynak eşlemesi | missing | made automatically as: sheet → source (audit or dataset and file) → period → rows; her "row shift" and "change made" columns describe her manual copy and do not apply (P5) |

## Typed by hand or from dashboard screenshots: cannot be produced from the export

1. Search Console dashboard numbers for "last 28 days" with the sync time (we compute the same window from the daily
   file: the numbers can differ slightly from the dashboard).
2. Device and country splits for Enpara: from the dashboard; Enpara's export has no gsc-search-performance file.
   Other exports with that file give them automatically.
3. Query intent shares over ~900 queries ("Marka %84"): dashboard; the export's intent file lists 100 queries.
4. AI Overview: dashboard said "no data"; the export's columns are empty. Both become "Veri yok".
5. Index health (top 100 pages URL-inspected, sitemap errors 0): dashboard; no dataset → "Veri yok".
6. The separate Search Console download (`…search-console-verileri-2026-11-12.xlsx`) used for the daily totals (D3).
7. The expert's review: "SEO uzmanı değerlendirmesinden geçmiştir", "Onaylandı" in every SEO değerlendirmesi cell,
   "Uzman onayı" row, approved priorities, the approved checklist results.
8. Owner and date of every open decision ("Kim", "Hedef tarih"), and target values for success tracking.
9. Her own wording: Yönetici özeti sentences, C1 "İçgörü"/"Önerilen aksiyon", the business reasons of S-/R- rows,
   "Çapraz bağlantı" notes. We generate our own text for these; it will not match hers word for word.
10. C2's live download of competitor pages (12 Nov): needs a live fetch, done only on a request.
11. The AI-citation window of 22–24 Oct used in "AI alıntılanan sayfalar" (a subset of the export's runs) (D2).
12. Kaynak eşlemesi's row-shift and change columns, and "Kaynak notları (düzeltilmedi)": they describe her manual
    copy; the source notes become our self-checks instead.

## Self-checks added to the text check (P1, P4)

- RG-27: the same count stated differently across sheets (pages read, affected addresses of a card, finding count),
  each count from one function, compared on every sheet that states it.
- RG-28: every finding id in Bulgu bazında, Etkilenen adresler, Aksiyon planı and Uzman teyidi is in Bulgular.
- RG-29: every Yönetici özeti number equals the value in the row its link points to.
- RG-30: every internal link points to an existing sheet and a row inside it.
All hard. Without Maya data the SC/AI sheets are left out and Kapsam says so (no empty sheet).

## Phases (a commit each, with tests on synthetic data)

| Phase | What | Tests |
|---|---|---|
| P1 | Frame (band, "← Kapak", Kaynak line, header on row 3, colours) on every sheet; Kapak; RG-27, RG-28, RG-30; internal links kept working after the 2-row shift | frame on every sheet; Kapak periods never merged; link check fails on a broken link |
| P2 | Maya data: read gsc-query-opportunities, gsc-top-queries, gsc-top-pages snapshots (latest per page/query, weeks present), gsc-query-intents rows, gsc-page-scores fields, citation-mentions per own page (cleaned), aio columns; each with its period; "Veri yok" reasons | synthetic export files; snapshots never summed; empty aio → Veri yok |
| P3 | Search Console özeti, Trafiğe göre öncelik, SC sayfaları, SC sorgular, SC fırsatlar, AI alıntılanan sayfalar; SC columns in Sayfa bazında and Kilit sayfalar; checklist "önerilen sonuç" + kanıt + before/after rows; checklist SEO-069 | each sheet from synthetic data; no Maya data → sheets left out, Kapsam line |
| P4 | Aksiyon planı (31 columns), Uzman teyidi, Yönetici özeti (auto 5–7, RG-29), Sayfa grupları, Konum dizini, PDF page numbers | ids stable, links land on the right rows, expert columns empty, summary numbers equal their rows |
| P5 | Competitor sheets in her column order, Rakip yöntem notları, Kaynak eşlemesi | column order; n<10 marked |
| P6 | Rebuild the saved Enpara audit (with the export from ~/Downloads, read locally only) and compare with her file: remaining differences with reasons; rebuild the other saved audits; text check PASS on all; expert labels and benchmark still hold; fix log rows; DECISIONS, IMPLEMENTATION-STATUS | expert lock, fast suite, full suite |

## Owner's decisions (2026-11-20)

- **D1** Keep Organik×AI - Özet, Organik×AI - Segmentler, Genel durum and Sayfa detay in the client Ek, listed last in
  Kapak. Düzeltme kaydı and Kontrol raporu are internal: they leave the client Ek and go into a separate team file
  ("-ekip.xlsx", built with the Ek by the same function; the web app offers it as its own download).
- **D2, D3, D4** as proposed below.
- **D5** Expert and client columns are empty with dropdowns. Kapak says "uzman değerlendirmesinden geçmiştir" only
  when every row of Uzman teyidi has a filled expert decision; otherwise "uzman teyidi bekliyor".
- The PDF's old "Motor: Maya Audit <version> · denetim <id>" line is removed too (P1).
- Numbers Maya computes itself where the team used the dashboard (28-day totals, intent shares): Kapak and the
  sheet's source line say "Maya dışa aktarımından hesaplandı" with the period.

## Decisions as proposed

- **D1** Our sheets she left out (Genel durum, Organik×AI - Özet/Segmentler, Sayfa detay, Düzeltme kaydı, Kontrol
  raporu): proposed: keep them, listed in Kapak under "Yöntem ve izlenebilirlik", after her sheets.
- **D2** AI citations: proposed: the whole export period everywhere (stated), not a hand-picked run window.
- **D3** Read only Maya's 22-dataset export (proposed), not the separate Search Console xlsx download.
- **D4** PDF page column: proposed: filled when the Ek is built with the team report PDF (web app and skill print
  both), else "PDF oluşturulmadı"; the HTML link column only when a shared HTML link exists, else left out.
- **D5** Expert/client columns are always empty with dropdowns; "uzman değerlendirmesinden geçmiştir" never written
  by Maya (proposed).

## Result (phase 6, 2026-11-20): the saved Enpara audit rebuilt against Efsa's file

Rebuilt from saved data with the skill's own flow (team report PDF printed, then the Ek with each card's PDF page),
with the Maya export files from her folder attached to a local copy (never committed). 30 sheets in the client Ek
(Kapak, the 5 action sheets, the reader and technical sheets, 3 of the 6 Search Console / AI sheets, Kaynak eşlemesi,
Maya's 4 own sheets) and a team file (Kontrol raporu: Geçti; Düzeltme kaydı). The text check passes.

**Same as her file:** the sheet order; the Maya band, "← Kapak" and the source line on every sheet; Kapak's blocks;
T-01 to T-16 (her 15 cards and the checklist problem no card covers), with T-01/T-02/T-03 pointing at the same
"Bulgu bazında" rows; Uzman teyidi's 28 items; SC sayfaları's page list; Sayfa bazında's 176 rows with the Search
Console columns; Kilit sayfalar, Şablonlar, Yönlendiren bağlantılar and Kontrol listesi özeti row for row; the
checklist's proposal columns and before/after totals; the competitor sheets' C1/C2 columns (on audits whose export
has the competitor datasets).

**Remaining differences, with the reason:**

| Where | Ours / hers | Reason |
|---|---|---|
| SC fırsatlar | missing / 923 rows | the export in her folder has no gsc-query-opportunities file (her 12 Nov add-on had one); made when the file is attached |
| SC sorgular | 101 queries, intent only / 251 with clicks | no gsc-top-queries in the export; she used another download (D3) |
| C1, C2, Rakip yöntem notları | missing / 12, 36, 10 rows | the export has no topic-visibility-snapshots or competitor-mentions-daily; made when attached (MMI shows them) |
| Aksiyon planı | 17 / 30 actions | follows the three rows above: 1 S- (SEO-071; SEO-069 needs the opportunities file) and no R- (no competitor data) |
| Search Console özeti | computed from the export / dashboard screenshots | device, country, index health from the dashboard are "Veri yok" with the reason; the 28-day totals are computed from the daily file and marked so; intent shares count the 101 classified queries, not the dashboard's ~900 |
| AI alıntılanan sayfalar | every cited page over the export's period / 34 pages from three days of runs | D2 |
| Kitapçıkta aç (HTML) | left out / a link per action | no shared HTML link exists (D4) |
| PDF page numbers | from today's PDF / from her 12 Nov booklet | the PDF's layout changed since (cards 1-4 on page 5 now) |
| Bulgu bazında, Etkilenen adresler, Bulgular, Özet, Bağlantı yerleri, Kapsam, Yöntem | different row counts | the current engine (DECISIONS 365-375 came after her 12 Nov copy: other findings in Özet, link places, no check names as IDs, version line) |
| Sayfa grupları | address rows in their own columns with links / group and address in the same columns | layout; same content |
| Kaynak eşlemesi | source and period per sheet / her manual copy's source ranges and row shifts | a file Maya writes has no manual copy to trace |
| Expert columns, "uzman değerlendirmesinden geçmiştir", Açık konular' owners and dates | empty or "Uzman teyidi bekliyor" / filled by her | expert and brand input (D5) |
| Her own wording (Yönetici özeti sentences, business reasons, C1 advice) | Maya's text | not reproducible; ours comes from the text library and the competitor sheet |
