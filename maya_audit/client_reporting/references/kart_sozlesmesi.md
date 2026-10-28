# cards.json sözleşmesi (sürüm 2)

`render_report.py` yalnızca bu dosyayı okur. Maya'nın `report.json` dosyası önce `from_maya_report.py` ile bu biçime çevrilir. Model sonra boş alanları doldurur. Başka bir denetim aracı da aynı biçimi üretirse aynı rapor çıkar.

Anahtar adları İngilizce, müşterinin göreceği metinler **Türkçe**.

## Üst düzey

| Alan | Zorunlu | İçerik |
|---|---|---|
| `contract_version` | evet | `2` |
| `meta` | evet | Rapora ait bilgiler (aşağıda) |
| `coverage` | evet | Kapsam: ne kadarı okundu |
| `score` | hayır | Taslak puan; bkz. `onem_kurallari.json` → `score` |
| `kpis` | evet | Özet kutuları; 3–5 tane. Taslak puan KPI kutusu değildir; kapakta "taslak" etiketiyle görünür |
| `summary` | evet | `one_read`: 3–4 cümle; `bullets`: en fazla 4 madde |
| `cards` | evet | Ana kartlar; **en fazla 10**, önem sırasına göre |
| `appendix_cards` | evet | Diğer bulgular (aynı biçim, kısa gösterilir); boş liste olabilir |
| `changes_since_last` | hayır | Önceki denetimle fark: `{previous_date, fixed:[], new:[], still_open:[], unknown:[]}` (her öğe `{title, count}`) |
| `manual_checks` | evet | Müşterinin elle yapacağı kontroller: `{what, where}` |
| `not_measured` | evet | Ölçülemeyenler: `{what, why, how_to_enable}` |
| `page_facts` | hayır | `{url: {title, h1, description, text_sample}}`. Doğrulayıcı, önerilen metnin sayfadan türetildiğini bununla kontrol eder |

## `meta`

| Alan | İçerik |
|---|---|
| `site` | `https://…` |
| `brand` | Görünen marka adı (Maya `brand.name`) |
| `audit_date` | Denetimin çalıştığı gün (`YYYY-MM-DD`) |
| `content_dates` | Hangi verinin hangi güne ait olduğu: `{"pages": "2026-10-15", "search_data": "2026-10-13 (kayıtlı kopya)"}`. Kapakta gösterilir. Önbellekten gelen veri burada açıkça söylenir. |
| `source` | `maya-report.json (şema 1.14)` ya da `elle hazırlandı` |
| `language` | `tr` |

## `coverage`

`pages_read`, `pages_cap`, `sitemap_urls`, `sitemap_checked`, `discovered_not_read`, `line` (tek cümle; ör. "282 sitemap adresinin 47'si okundu, 245'inin durumu kontrol edildi.").

## Kart (`cards[]` ve `appendix_cards[]`)

| Alan | Zorunlu | Kural |
|---|---|---|
| `id` | evet | Kısa, sabit kimlik; ör. `bos-sayfalar` |
| `title` | evet | **Neyin yanlış olduğunu** söyleyen Türkçe cümle. Kontrol kodu ya da İngilizce oran yazılmaz. İyi: "66 sayfa boş açılıyor". Kötü: "IDX-1 empty response". |
| `severity` | evet | `Kritik` · `Yüksek` · `Orta` · `Düşük` · `Bilgi` |
| `maya` | hayır | Maya'nın orijinali: `{check_id, severity, finding_ids, launch_gated}`. Önem kuralla değiştiyse görünür kalır. |
| `rule_applied` | hayır | Önemi düşüren kural (ör. "Kural 10: başlık sırası ve kelime sayısı not düzeyindedir"). Bir kural önemi yükseltemez. Kartta "Maya: S4 → rapor: Bilgi" diye gösterilir. |
| `could_be_intentional` | evet | `true` / `false`. Durum bilinçli bir tercih olabilirse (noindex, sitemap dışı, robots engeli) `true` olur. |
| `where` | evet | `{count, of, of_label, examples: [≤5 URL], csv, group}`. `of_label` neyin toplamı olduğunu söyler (ör. "sitemap adresi, hepsi kontrol edildi"). `group` aynı şablondan geliyorsa açıklama yazar (ör. "/semt/* şablonu"). |
| `why` | evet | `{text, source_url, source_label}`. Google kuralı varsa onun bağlantısı verilir; yoksa `source_label: "İyi uygulama, Google kuralı değil"`. |
| `steps` | evet | 1–5 madde, uygulanabilir adımlar. CMS biliniyorsa ekran adıyla. |
| `what_to_write` | evet | Aşağıdaki iki biçimden biri |
| `verify` | evet | Düzeltmenin tuttuğu nasıl anlaşılır (hangi adres açılır, ne görülmeli) |
| `depends_on` | hayır | Önce yapılması gereken kartın `id`'si |
| `evidence` | evet | `{snippet, read_at, verification:[]}`. Yapılandırılmış kayıtlar aşağıda; eski `verified_live` tarihi tek başına kanıt değildir. |
| `owner`, `effort` | evet | `Geliştirici` / `İçerik` / `SEO`; `Küçük` / `Orta` / `Büyük` (tahmin olduğu belirtilir) |
| `points` | hayır | Kontrolün puandan düşürdüğü (taslak); kontrolün ilk kartında, diğerlerinde null |

### `what_to_write` biçimleri

**A. Somut metin ya da kod:** Yalnızca kanıt varsa kullanılır.
```json
{"text": "Adile Sultan Ev Yemekleri – Besin Değerleri Tablosu",
 "code": null,
 "derived_from": [{"url": "https://…/besin-degerleri/", "field": "h1", "source": "native", "read_at": "2026-10-15T10:00:00+00:00"}],
 "review": {"status": "reviewed", "reviewer": "İnceleyen kişi/model", "reviewed_at": "2026-10-15T11:00:00+00:00", "reason": "Öneri kaynakla anlam bakımından karşılaştırıldı."}}
```
`derived_from` boş olamaz. Önerilen metindeki anlamlı kelimeler o sayfanın title, H1, description ya da görünür metninde geçmelidir (`page_facts` ile denetlenir).

**A2. Sayfa başına öneri listesi:** Birden çok sayfaya ayrı metin önerildiğinde kullanılır (title, description, H1, alt metin).
```json
{"items": [{"url": "https://…/bulten-kvkk/", "field": "title",
            "current": "KİŞİSEL VERİLERİN … | Adile Sultan Ev Yemekleri",
            "proposed": "Bülten Üyeliği Aydınlatma Metni (KVKK) | Adile Sultan"}],
 "derived_from": []}
```
Her items[] kendi derived_from ve review kaydını (A biçimindeki gibi) içermelidir; üst düzey boş derived_from kanıt yerine geçmez.
Her `proposed` yalnızca kendi `url`'sinin `page_facts` kelimelerinden türetilir; doğrulayıcı her satırı ayrı denetler. Rapor bunu "Şu an / Önerilen" tablosu olarak gösterir.

**B. Karar:** Kanıttan metin türetilemiyorsa uydurulmaz; müşterinin vereceği karar yazılır.
```json
{"text": null, "code": null, "derived_from": [],
 "decide": "Karar vermelisiniz: Bu 66 adresi düzeltmek mi, yoksa sitemap'ten çıkarıp noindex yapmak mı?"}
```

## Görünür metin kuralları (doğrulayıcı denetler)

- Yasaklı yer tutucular: "Şizofreni", "Kettles", "teapots", "brand.example", "Brand", "Lorem". Bunlar başka sektörden kalma sabit örneklerdir.
- İç kodlar görünmez: `bilesen_cihaz` gibi alt çizgili adlar, `IDX-5` gibi kontrol kodları başlıkta yer almaz. Kodlar yalnızca `maya` alanında kalır.
- Ana kart sayısı en fazla 10.
- `launch_gated` (doğrulanmamış kontrol) olan bir kart ancak `evidence.verification` tam etkilenen URL kapsamını doğruluyorsa ana bölümde kalır; doğrulanmadıysa eke taşınır.


## Sürüm 2 — güvenilirlik sözleşmesi

Audit report.json şeması değişmedi (1.14); bu sürüm yalnızca cards.json içindir.
Eski kartlar final çıktıda reddedilir; yeniden dönüştürülmeli veya `--draft` kullanılmalıdır.

- `coverage`: audit_status.content_coverage içindeki açık pages_read/level ve çalışmış kontrol
  sayıları korunur. Sıfır ile bilinmeyen farklıdır. `score_status`: unavailable, partial veya
  assessed_sample. `score_reason` puanın tam kapsamını ve taslak niteliğini açıklar.
- `score`: `{value: null|0..100, status, scope, draft: true, lost_by_check}`. Kapsam coverage ile
  eşleşir. Eksik değerlendirme veya puanı etkileyen doğrulanmamış bulgu varsa null kullanılır.
  Doğrulanmamış kanıtı dışarıda bırakmak sağlıklı puan oluşturmaz. Puan kontrol başına bir kez,
  kontrolün tekil adresleri üzerinden hesaplanır.
  Bilinen/sitemap URL sayısı içerik puanının paydası değildir; IDX-5 kendi ölçülen paydasını kullanır.
  Severity kuralları, ağırlıklar, taban ve kontrol başına tavan korunur. Ağırlıklar kalibre değildir.
- `changes_since_last`: fixed/new/still_open yanında `unknown` listesi. Başlık tek başına kimlik
  değildir; generated id değiştiğinde semantik eşleşme varsayılmaz. fixed için aynı kontrolün tam
  pass sonucu, değişmeyen hedef/koşullar, tam eski etkilenen URL listesi ve zaman damgalı yeniden
  okuma gerekir. partial/not_assessed, eksik sağlayıcı, değişen kapsam unknown olur. Site geneli ve
  yalnızca sağlayıcı metadata kanıtlarıyla otomatik fixed üretilmez. `resolution` kontrol/URL/tarih,
  assessment ve conditions kayıtlarını taşır. Bu, yeni kanıtta sorunun görülmemesidir; kalıcı çözüm
  garantisi değildir. Elle eklenen fixed kayıtları da çözülme kanıtını taşımak zorundadır.
- `page_facts[url].observations`: source/native veya firecrawl, url, read_at ve provenance ile
  ayrı gözlemler. Native title/H1/description kendi crawl analizinden gelir. Firecrawl rapor satırları
  içerik değil metadata içerir; rawHtml varsayılmaz. Hash text_sketch asla okunabilir metin değildir.
  text_sample bu rapor sözleşmesinde null kalır; gerçek sayfa metni yoksa tahmin edilmez.
- `what_to_write.derived_from` ve her `items[]` önerisi için kaynaklar:
  `{url, source, field, read_at}`. Seçilen alanın tam gözleminde okunabilir değer bulunmalıdır.
  `source`, kartın maya.source.reader kaynağıyla eşleşir (kaynak yoksa native).
  Farklı alanların kelimeleri veya marka adı tek başına kanıt sayılmaz.
- Gerçek metin/kod önerisi ayrıca `review: {status: "reviewed", reviewer, reviewed_at, reason}`
  içerir. Tarihler timezone içeren ISO datetime olmalıdır. İnceleme yoksa `decide` kullanılmalı
  veya yalnızca taslak çıktı üretilmelidir. Otomatik kelime/sayı tutarlılığı anlamsal doğruluğu
  kanıtlamaz. Kodun JSON scalar değerleri (şema @context/@type hariç) veya direktif değerleri
  kaynakla karşılaştırılır; kodun çalışması/güvenliği ayrıca incelenir. Kısa rakamlar, yüzde,
  ücret, tarih ve miktar da karşılaştırılır. Kaynaktaki sayıların bulunması bile anlamı kanıtlamaz.
- `evidence.verification`: `{check_id, url, what_checked, checked_at, method, evidence, conclusion}`
  kayıtları. method live_http/live_browser, conclusion confirmed olmalı. Bu kayıt ancak gerçekten
  yetkilendirilmiş canlı kontrolden sonra yazılır; tarih tek başına yeterli değildir. affected_urls
  tam liste ve count ile eşleşmedikçe örnek doğrulaması tüm kartı doğrulamaz. Geçerli örnek sayısı
  etikette gösterilir; doğrulanmamış/gap içeren kartlar ekte kalır.
- Final renderer her çağrıda aynı validator'ı çalıştırır (Python build API dahil), hata halinde
  yazmadan durur, JSON'u değiştirmez. `--draft` sürekli görünür TASLAK bandı ekler; müşteriye
  gönderilemez. `validate_cards --fix` ayrı ve açık bir çalışma-kopyası düzeltmesidir, final render
  bunu kendiliğinden yapmaz. İnceleme kayıtlarının dürüstlüğü otomatik olarak doğrulanamaz.
