# data.json sözleşmesi (contract 1)

`build_data.py` üretir, `render.py` basar (ikisi de `maya_audit_web/team_report/`, DECISIONS 307). **S** = script yazar (dokunma), **M** ve **S→M** = `_slots` listesindeki metin alanları: script motor, katalog ya da **metin kitaplığı** (`texts/tr.json`, `texts/en.json`) metniyle doldurur; model isterse cilalar. Hiçbir alan `⟪YAZ⟫` kalmaz. "M" diye işaretli alanların kitaplıktaki kaynağı: `assessment.*` ve `next_action.*` ve `followup.text` → `page1` şablonları (ilk kartların `summary` ve `explanation` alanlarıyla); `priorities[].title/text` → kartın `summary` / `explanation`; `findings[].title`, `confirm[].title` → `finding`; `todos[].title/steps/verify` → `title` / `steps` (`steps_by_platform`) / `verify`; Not kartlarının adımları → `notes`.

**Kilit:** `_locked`, `_slots` dışındaki her görünür alanın özetidir (önem, sayı, sıra, adres, puan). `validate_data.py` değişiklik görürse durur.

## Kök
| Alan | Kim | Açıklama |
|---|---|---|
| `lang` | S | `tr` / `en` |
| `meta.brand`, `meta.domain` | S | `brand.name` (yoksa alan adı), `crawl.origin` |
| `meta.date`, `meta.revision` | S | `crawl.started_at`; `--rev` |
| `meta.coverage_level/label` | S | `audit_status.content_coverage.level` → "Kısmi kapsam" vb. |
| `meta.market` | S | DFS-4 başlığındaki pazar ("Türkiye / tr"); yoksa alt başlıkta hiç geçmez |
| `meta.audit_id`, `meta.engine_version` | S | alt bilgi |

## Sayfa 1 — Denetim özeti
| Alan | Kim | Kaynak / kural |
|---|---|---|
| `kpis[0]` Kayıtlı sorun | S | `problem_summary.problems` + `by_severity` |
| `kpis[1]` Okunan sayfa | S | `content_coverage.pages_read`, alt satır `known_urls_not_read` |
| `kpis[2]` | S | IDX-5 paylı bulgu varsa "uygunsuz / kontrol edilen" (başlıktan); yoksa "Sayfaya özgü sorunlu sayfa / okunan" (`problem_summary.by_page`); alt satır `whole_site.problems` > 0 ise site geneli sorun sayısını söyler (ortak üst/alt bilgi bulguları by_page'e girmez) |
| `kpis[3]` Mobil lab | S | DFS-9 "Performance score"; yoksa "Ölçülmedi" (asla 0 değil) |
| `assessment.headline` (≤90) | M | raporun tek cümlelik hükmü |
| `assessment.text` (≤190) | M | sıralı yapılacaklar, tek cümle |
| `priorities[]` (≤3) | S + M | öncelik sırasındaki ilk farklı kontroller (`intent` taşıyanlar hariç); mobil lab skoru <50 ise 3. sırayı alır. `value`/`tone` S; `title` (≤40) ve `text` (≤150) M |
| `coverage.rows` | S | kontrol edilemeyen kısım, kayıtlı kopyadan okunan sayfa (`firecrawl.pages`), ek not (Info), engelleyici (S1) |

## Sayfa 2 — Öncelikli bulgular
| Alan | Kim | Kaynak / kural |
|---|---|---|
| `findings[]` (≤5) | S | `findings_in_priority_order` içindeki ilk 5 sorun (Info hariç) |
| `findings[].title` (≤70) | S→M / M | EN: motor başlığı; TR: motor çevirisi varsa o, yoksa M |
| `findings[].scope` | S | `scope.count` + birim (URL / sayfa / dosya / tüm site); IDX-5 paylı bulguda başlıktaki oran |
| `findings[].status` | S | `confidence` + "niyet doğrulanmadı" (`intent`); "kontrol canlı sitelerde henüz doğrulanmadı" yazılmaz (DECISIONS 300: öyle bir bulgu "Teyit edin"e gider; `LG-xx` `todos[].launch_gated`'da iz olarak kalır) |
| `evidence_sample` | S | 1. bulgunun kanıtı: `attempts` varsa istek/saat/HTTP/gövde; yoksa adres listesi |
| `next_action.lead` (≤60), `.text` (≤200), `.caveat` (≤170) | M | 1. bulgunun düzeltmesi (`src`) ve kanıt sınırı |

## Sayfa 3 — Arama ve performans
| Alan | Kim | Kaynak / kural |
|---|---|---|
| `search.rows` (≤3) | S | DFS-4 tablosu (Relevance süzülmüş), aranma hacmine göre; çubuk = seçimdeki en büyüğe oran |
| `search.ranking_page` | S | ilk marka dışı satırın sıralanan sayfası |
| `search.state = missing` | S | DFS-4 yok/değerlendirilmedi → "veri alınmadı, sıfır sayılmaz" |
| `lab` | S | DFS-9: skor, ölçüm tarihi, eşiği aşan metrikler (TR'de "6,1 sn") |
| `field` | S | `crux` varsa (assessed): geçti/geçmedi + LCP/INP/CLS p75 |
| `commercial`, `limits` | S | sabit, temkinli metinler; model isterse siteye özgü kısaltabilir ama yeni sayı ekleyemez |

## Sayfa 4 — Aksiyon planı
| Alan | Kim | Kaynak / kural |
|---|---|---|
| zamanlama | S | `maya_audit_web.practical.when` ile aynı: S1/S2 ya da (S3 + küçük efor) → bu hafta; S3 ya da (S4 + küçük efor) → bu ay; kalan → sonra |
| `actions[]` (≤5) | S + M | bu haftanın bulguları; `intent` taşıyanlar sona; mobil lab zayıfsa S1/S2'den sonra "diagnostic:DFS-9" aksiyonu. `owner`/`effort` S (`sahip_efor.json`), `title` (≤75) M |
| `followup` | S + M | bu ayın sayısı S; `text` (≤170) M |
| `later[]` (≤3) | S + M | sonraya kalan ilk 3 bulgu; `count` = `scope.count`; `label` (≤55, sayısız) M |
| `provenance` | S | okunan / okunmayan / kontrol edilemeyen; sitemap listelenen/kontrol edilen; motor sürümü ve denetim kimliği |

## Denetim için iç alanlar
- `_slots`: model alanlarının listesi (`path`, `hint`, `src`, `max`).
- `_facts`: metinde kullanılabilecek sayılar (report.json'dan). Başka sayı → hata.
- `_engine_wording`: motor çevirisi kullanıldı mı.

## Sayfa 5+ — Yapılacaklar (sayfa başına 4 kart, en çok 15 kart, öncelik puanı sırasıyla; DECISIONS 300)
| Alan | Kim | Kaynak / kural |
|---|---|---|
| sıra | S | bütün sorunlar (Info hariç), takvim sırasıyla (bu hafta → bu ay → sonra); kasıtlı olabilecekler (`intent`) kendi grubunun sonunda; en sonda, varsa, tek **yapısal veri kartı** (`severity: Info`, STR-3 Info bulguları + `homepage with no WebSite structured data` gözlemi; `schema_additions`), sonra tek **küçük düzeltmeler kartı** (`hygiene_items`: ACC-8 yönlenen llms linkleri, IDX-3/STR-10/IDX-6 hijyen gözlemleri), en son tek **içerik ve dil kartı** (`content_items`: STR-9 menü dili, STR-2 başlıksız sorular, STR-14 adres yazımı; sorumlu İçerik), sonra **sayfa yükleme ve etiket kartı** (`PERF_INFO`: PRF-1 CDN önbelleği, TSEO-1 defer'siz script ve çift analitik etiketi, STR-7 boyutsuz görsel, image/jpg preload, WebP/AVIF) ve **paylaşım ve şema kartı** (`SHARE_INFO`: STR-3 varsayılan VideoObject, STR-10 küçük paylaşım görseli, STR-7 biçim uyuşmazlığı) |
| `todos[].severity/when/owner/effort/id/status` | S | önem, `when` kuralı, `sahip_efor.json`, kanıt durumu |
| `todos[].links` (≤4) | S | `scope.urls`'ten tıklanabilir linkler (metin = yol; ana sayfa = alan adı) |
| `todos[].more` | S | kartta gösterilmeyen listelenmiş adresler + `problem_summary.not_listed` (rapordaki listeye girmeyen sayfalar) |
| `todos[].sitewide` | S | adres yoksa "Tüm siteyi ilgilendiriyor" |
| `todos[].finding_ids`, `todos[].verification_state`, `todos[].target_urls`, `todos[].step_rules`, `todos[].topics` | S | yayın kapısının okuduğu alanlar (DECISIONS 278): kartın bulguları, bulgunun ikinci bakış durumu, kırık bağlantının hatalı hedefleri (kaynak sayfalardan ayrı), koşullu katalog adımları ve gösterilip gösterilmedikleri, Not kartı başlığındaki konular ve dayandıkları kimlikler |
| `_report_path`, `_affected_path`, `_maya_src` | S | kapının report.json'u, tam adres listesini ve motoru bulduğu yer; basılmaz |
| `todos[].rule_id`, `todos[].fact`, `todos[].known_paths` | S | kural kimliği; kanıt satırı (`evidence.facts`'ın ilki); bulgunun kaydında geçen adresler (doğrulayıcı metindeki adresleri bunlara karşı denetler) — DECISIONS 270–271 |
| `todos[].title` (≤80) | S→M | kural kataloğunda varsa oradan (`rule_actions.json`), yoksa M: fiille başlayan iş adı |
| `todos[].steps` (≤420, 2–4 satır, satır ≤100) | S→M | katalogda varsa oradan; yoksa motorun düzeltme cümlesi kutuya sığıyorsa o; ikisi de yoksa M |
| `todos[].verify` (≤150) | S→M | motorun "beklenen" cümlesi; Not kartlarında sabit metin; yoksa M |

Sayfa sayısı = 4 + ⌈kart sayısı / 4⌉; render bunu PDF'te denetler.

## DECISIONS 300 — müşteri seçimi, son sayfa ve ek

Hepsi S (script): `maya_audit.client_selection.select` ve `build_data.py`. Model yalnız `confirm[].title` yazar.

| Alan | Kim | Kaynak |
|---|---|---|
| `todos[].priority`, `todos[].confidence_class` | S | grubun öncelik puanı (önem × güven × erişim × iş önemi) ve güven sınıfı; puan önemi değiştirmez |
| `todos[].platform_steps` | S | adımlar `rule_actions.json` `steps_by_platform`'dan geldiyse platform adı (ör. Shopify); kapı rapordaki `platform.name` ile karşılaştırır (RG-11) |
| `todos[].links` | S | önce her dilden bir örnek adres (grubun `examples`), sonra diğerleri |
| `actions[]` | S→M | öncelik puanına göre ilk 5 kart (`actions_schedule` = "Öncelik puanına göre ilk kartlar") |
| `own_limits[]` | S | Maya'nın sınırları: sayfa sınırı, süre sınırı, okuma yolu (`acc9.reader*`), değerlendirilemeyen kısım sayısı |
| `confirm[]` (≤10), `confirm_more` | S, `title` M (≤90) | "Teyit edin": önem, kapsam, neden (`confirm_reasons`); fazlası sayılır |
| `key_pages[]` | S | sayfa önemi sırasıyla ilk 10 okunan sayfa: tür, önem (0-100), kartlar, en yüksek önem, teyit sayısı |
| `quick_wins[]` | S | küçük eforlu kartların numaraları (en çok 4); aksiyon planı sayfasında "Sonraki inceleme" kutusunun yerinde |
| `appendix.finding_ids`, `appendix.counts`, `appendix.line` | S | ekin listelediği bulgular (kapı RG-17 hepsini ister) ve sayıları |
| `_confirmations` | S | `--confirm` / `--reject` ile verilen elle kontroller (kural ya da bulgu kimliği); `render.py` eki aynı seçimle yazar |

