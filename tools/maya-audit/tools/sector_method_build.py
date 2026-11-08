"""Build `maya_audit/sector_method.json` from the team's sector audit workbook (DECISIONS 324).

Source: `docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm` (İlginay, from Efsa's sector list). It is read with
openpyxl in data-only mode, so no macro ever runs (the file holds none). openpyxl is not a project dependency: run
this with any Python that has it, e.g. `python3 tools/sector_method_build.py`. The product reads only the JSON.

The JSON keeps the team's columns and texts as they are, and adds Maya's mapping per check: status (A automatic,
K partly, G Search Console, P a person, M-S/M-M/M-L missing but automatable), the rule ids that decide it, the report
checks that must have run for "Uygun", what Maya covers and what is missing. It also holds the draft Havayolu and
Restoran / kafe rows (owner, 2026-11-08: "taslak — İlginay/Efsa onayı bekliyor").
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/business-types/Sektor_Bazli_SEO_Audit_Onceligi.xlsm"
OUT = ROOT / "maya_audit/sector_method.json"
DRAFT = "taslak — İlginay/Efsa onayı bekliyor"

SECTOR_PROFILE = {
    "E-ticaret / perakende": "eticaret", "Bankacılık": "bankacilik", "Yatırım hizmetleri": "yatirim",
    "Kart ve sadakat programları": "kart", "Sağlık / klinikler": "saglik", "Otomotiv": "otomotiv", "B2B SaaS": "saas",
    "Su arıtma hizmetleri": "su_aritma", "Güvenlik hizmetleri": "guvenlik", "Ev hizmetleri": "ev_hizmetleri",
    "Gıda üreticisi": "gida", "Seyahat / rezervasyon": "seyahat",
}

# id: (status, rule refs, report checks needed for "Uygun", what Maya covers, what is missing)
CORE = {
    "CORE-001": ("A", ["ACC-1", "ACC-2"], ["ACC-1", "ACC-2"], "robots.txt durumu, boyutu, HTML dönmesi; bot başına kurallar; engellenen kilit sayfalar (ACC-1, ACC-2)", ""),
    "CORE-002": ("A", ["IDX-5", "acc3.sitemap_noindex", "acc3.noindex_listed"], ["IDX-5"], "sitemap bulunuyor; yönlenen/404/noindex/taslak adresler (örneklem), lastmod (IDX-5, ACC-3)", "sitemap adresinin canonical'ı başka sayfayı gösteriyorsa raporlanmıyor (S)"),
    "CORE-003": ("G", ["IDX-9"], ["IDX-9"], "GSC anahtarı verilirse en çok 20 kilit sayfa için URL Inspection (IDX-9)", "GSC Sayfalar raporu (sayfa türüne göre nedenler) GSC bağlantısı ister"),
    "CORE-004": ("A", ["acc3.noindex", "acc3.robots_noindex", "acc3.robots_outside_head", "acc3.sitemap_noindex"], ["ACC-3"], "her yanıtta meta robots ve X-Robots-Tag (ACC-3)", ""),
    "CORE-005": ("A", ["IDX-1"], ["IDX-1"], "okunan her sayfanın durumu, 5xx, soft 404, boş şablonlar (IDX-1)", "GSC soft-404 raporu (isteğe bağlı)"),
    "CORE-006": ("K", ["IDX-4", "idx9.canonical"], ["IDX-4"], "varlık, hedef durumu, çakışmalar, kendine/başka sayfaya (IDX-4)", "Google'ın seçtiği canonical GSC ister (IDX-9, 20 sayfa)"),
    "CORE-007": ("A", ["IDX-3", "idx6.links_to_redirect", "idx4.chain"], ["IDX-3"], "zincirler, döngüler, geçici yönlendirmeler, yönlenen adrese bağlantılar (IDX-3, Stage 8a)", ""),
    "CORE-008": ("K", ["IDX-2"], ["IDX-2"], "http→https ve www/www'suz tek host'ta bitiyor (IDX-2)", "sondaki eğik çizgi ve büyük harf varyantları denenmiyor (S)"),
    "CORE-009": ("K", ["RND-1", "RND-2", "RND-3"], ["RND-1", "RND-2"], "işlenmemiş ve işlenmiş HTML'de metin ve bağlantılar, işleme örneklemi (RND-1/2/3)", "işlemedeki konsol/API hataları (M); Google'ın kendi görünümü GSC canlı testi ister"),
    "CORE-010": ("A", ["idx7.deep", "idx7.orphan", "idx5.sitemap"], ["IDX-7"], "sayfa başına tıklama derinliği, yalnız sitemap'te olan sayfalar (IDX-7, sayfa gruplama)", "GSC adres envanteri (isteğe bağlı)"),
    "CORE-011": ("M-M", ["idx6.tracking", "IDX-8"], [], "yalnız izleme parametreli bağlantılar ve kopyalar (IDX-6, IDX-8)", "şablon başına parametre/filtre kombinasyonları (Stage 7); hangi filtrenin dizine girmesi gerektiği kişinin kararı"),
    "CORE-012": ("A", ["STR-9"], ["STR-9"], "hreflang söz dizimi, karşılıklı bağlantı, hedefler, dil (STR-9); tek dilli sitede uygulanamaz", ""),
    "CORE-013": ("K", ["PRF-3"], ["PRF-3"], "ücretsiz anahtarla CrUX saha verisi: alan adı ve en çok 5 adres (PRF-3)", "sayfa türü başına örneklem (S); GSC CWV raporu"),
    "CORE-014": ("K", ["tseo1.blocking_scripts", "RND-6"], ["TSEO-1"], "<head> içinde engelleyen script'ler, HTML ağırlığı, geç başlayan içerik (TSEO-1, RND-6)", "render'ı engelleyen CSS ve üçüncü taraf script bütçesi (M)"),
    "CORE-015": ("K", ["tseo1.no_viewport", "tseo1.no_zoom", "RND-4"], ["TSEO-1"], "viewport, yakınlaştırma, canvas/iframe içerik (TSEO-1, RND-4)", "dokunma hedefleri, yazı boyutu, mobil menü: mobil işleme (M) ya da kişi"),
    "CORE-016": ("K", ["STR-7"], ["STR-7"], "100 KB üstü görseller, boyutsuz görseller, biçimler, preload türü (STR-7)", "gerçek LCP öğesi ve onun lazy-load'u (M)"),
    "CORE-017": ("K", ["tseo1.url_slug_unclear", "tseo1.url_decomposed"], ["TSEO-1"], "adres düzenine göre şablonlar, anlaşılmaz adres parçaları (sayfa gruplama, TSEO-1)", "hiyerarşinin doğru olup olmadığı kişinin kararı"),
    "CORE-018": ("K", ["idx7.orphan"], ["IDX-7"], "tam taramada iç bağlantısı olmayan sitemap sayfaları (IDX-7)", "GSC/GA4'teki yetim sayfalar GSC ister"),
    "CORE-019": ("K", ["str3.crumb_no_list", "idx7.product_no_category"], ["STR-3"], "BreadcrumbList'siz iz, kategoriye bağlantısı olmayan ürün (STR-3, IDX-7)", "iz ile adres ağacının eşleşmesi (S)"),
    "CORE-020": ("K", ["STR-14"], ["STR-14"], "boş ve genel bağlantı metinleri, sayfa başına bağlantı puanı (STR-14, sayfa gruplama)", "bağlantı metninin bağlama uygunluğu: AI/kişi"),
    "CORE-021": ("K", ["idx7.pagination_unlinked", "RND-3"], ["IDX-7"], "<a href> olmayan sayfalama, kaydırma/tıklama arkasındaki içerik (IDX-7, RND-3)", "sonsuz kaydırma için taranabilir yedek (M)"),
    "CORE-022": ("A", ["idx6.broken", "idx1.4xx.referenced"], ["IDX-6"], "kaynak sayfalarıyla kırık iç bağlantılar (IDX-6, IDX-1)", ""),
    "CORE-023": ("K", ["STR-1", "tseo1.title_short", "tseo1.title_long"], ["STR-1"], "eksik, ortak, genel title'lar, uzunluk bantları (STR-1, TSEO-1)", "niyet uyumu GSC sorguları ister"),
    "CORE-024": ("A", ["STR-2", "tseo1.heading_jump"], ["STR-2"], "eksik/boş/gizli/birden çok H1, atlanan düzeyler, ham ve işlenmiş (STR-2, TSEO-1)", ""),
    "CORE-025": ("K", ["STR-16", "tseo1.description_short", "tseo1.description_long"], ["STR-16"], "ortak açıklamalar, uzunluk bantları (STR-16, TSEO-1)", "doğru ve yanıltıcı olmaması: kişi"),
    "CORE-026": ("K", ["str7.alt_missing", "str7.no_alt", "str7.image_no_alt", "str7.placeholder", "str7.alt_split"], ["STR-7"], "eksik ve yer tutucu alt metinler (STR-7)", "açıklayıcılık, anahtar kelime doldurma: AI/kişi"),
    "CORE-027": ("A", ["STR-12", "str9.lang_mismatch", "str9.no_lang", "str9.bad_lang"], ["STR-12"], "bildirilen ve gerçek dil, başka dildeki bölgeler (STR-9, STR-12)", ""),
    "CORE-028": ("G", [], [], "", "GSC sorguları ve SERP örnekleri ister"),
    "CORE-029": ("G", [], [], "", "GSC sorgu+sayfa verisi ister"),
    "CORE-030": ("A", ["IDX-8", "STR-15", "RND-7"], ["IDX-8"], "birebir ve yakın kopyalar, konum şablonları, ince sayfalar, ortak blok payı (IDX-8, STR-15, RND-7)", ""),
    "CORE-031": ("K", ["STR-6", "idx5.stamped"], ["STR-6"], "eksik/gelecek/üretilmiş tarihler (STR-6, IDX-5)", "iddiaların doğruluğu: kişi"),
    "CORE-032": ("P", ["STR-21"], [], "temel sayfalar var mı (STR-21)", "sayfanın kullanıcı sorularını karşılaması: kişi/AI"),
    "CORE-033": ("P", [], [], "", "özgün, doğrulanabilir fayda: kişi"),
    "CORE-034": ("A", ["str3.required", "str3.invalid_values", "str3.unparsed", "str3.url_error", "str3.dangling_id", "str3.type_clash", "STR-11"], ["STR-3"], "ayrıştırma hataları, zorunlu alanlar, geçersiz değerler, çelişkiler (STR-3, STR-11)", "önerilen ('uyarı') alanlar (S)"),
    "CORE-035": ("K", ["str3.expected_type", "str3.maybe_product", "STR-4"], ["STR-3"], "ürün sayfalarında Product, fiyat/stok ile sayfa (STR-3, STR-4)", "liste sayfasında tek ürün gibi Product işaretlemesi: kural yok (S)"),
    "CORE-036": ("K", ["str3.no_organization", "str3.organization_broken", "str3.organization_gaps", "STR-5"], ["STR-3"], "Organization var, eksiksiz, adlar tutarlı (STR-3, STR-5)", "gerçek şirkete uygunluk: kişi"),
    "CORE-037": ("K", ["STR-4", "STR-11"], ["STR-4"], "işaretleme değerleri ile sayfa, çelişen değerler (STR-4, STR-11)", "sahte veri: kişi"),
    "CORE-038": ("K", ["STR-21", "STR-5"], ["STR-21"], "hakkımızda/iletişim sayfaları bulundu, adlar tutarlı (STR-21, STR-5)", "gerçek kimlik: kişi"),
    "CORE-039": ("K", ["str3.article_no_author"], ["STR-3"], "yazarı olmayan yazılar (STR-3)", "gerçek uzman, kaynaklar: kişi"),
    "CORE-040": ("K", ["STR-21", "STR-8", "str4.price_unclear"], ["STR-21"], "koşul/politika sayfaları, fiyat tabloları, belirsiz fiyatlar (STR-21, STR-8, STR-4)", "kolay ulaşılır ve açık olması: kişi"),
    "CORE-041": ("A", ["idx2.expires", "idx2.invalid", "tseo1.mixed", "RND-5"], ["IDX-2"], "sertifika, karışık içerik, giriş/ödeme duvarları (IDX-2, TSEO-1, RND-5)", ""),
    "CORE-042": ("P", [], [], "", "iddiaların kanıtlanabilirliği: uzman/hukuk"),
    "CORE-043": ("G", [], [], "", "sayfa türüne göre GSC performansı"),
    "CORE-044": ("K", ["ACC-5", "ACC-4", "ACC-9"], ["ACC-4"], "kullanıcı aracısına göre bot erişimi, hız sınırları, verilirse loglar (ACC-4, ACC-5, ACC-9)", "taşıma kayıpları GSC geçmişi ister"),
}
GENERIC = {
    "On-Page & Arama Niyeti": ("K", ["STR-1", "STR-2", "STR-16", "tseo1.title_short", "tseo1.title_long", "tseo1.description_short",
                                     "tseo1.description_long", "IDX-8", "STR-15"], ["STR-1", "STR-2"],
                               "bu türün sayfalarında title, H1, açıklama, kopya ve ince sayfa (STR-1/2/16, TSEO-1, IDX-8, STR-15)",
                               "sorgu niyeti ile sayfanın uyumu GSC sorguları ve SERP örneği ister"),
    "İndeksleme & İç Link": ("A", ["IDX-1", "acc3.noindex", "acc3.robots_noindex", "acc2.blocks", "IDX-4", "IDX-7", "idx1.4xx"],
                             ["IDX-1", "ACC-3", "IDX-4"],
                             "bu türün sayfalarında durum, noindex, robots, canonical, iç bağlantı ve tıklama derinliği (IDX-1, ACC-3, ACC-2, IDX-4, IDX-7)",
                             "GSC'deki en iyi performanslı sayfa örneklemi (isteğe bağlı)"),
}
SEC_SPECIFIC = {
    "SEC-001": ("M-M", ["idx6.tracking", "IDX-8"], [], "izleme parametreleri, kopyalar", "şablon başına filtre/parametre kombinasyonları (Stage 7); hangi filtrenin dizine gireceği: kişi"),
    "SEC-004": ("K", ["STR-4", "str3.product_no_identifier", "IDX-4"], ["STR-4"], "fiyat/stok işaretlemesi ile sayfa, GTIN/MPN, varyant canonical'ları (STR-4, STR-3, IDX-4)", "ProductGroup/hasVariant (S); gerçek stok: Merchant Center/kişi"),
    "SEC-007": ("K", ["idx7.deep"], ["IDX-7"], "kategori sayfalarının ana sayfadan derinliği", "ana sayfadan bağlantısı olmayan 1. sıra türü kuralı (S); marka niyeti: kişi"),
    "SEC-010": ("K", ["idx8.location_template", "str3.required", "STR-5"], ["IDX-8"], "konum şablonu kopyaları, LocalBusiness alanları (IDX-8, STR-3)", "mağazalar arasında adres/saat tutarlılığı (M)"),
    "SEC-013": ("M-M", ["acc3.unavailable_passed"], [], "unavailable_after tarihi geçmiş (ACC-3)", "bitiş tarihi geçmiş ama 200 dönen ve bağlantı alan kampanya sayfaları (M)"),
    "SEC-016": ("K", ["STR-21"], ["STR-21"], "iade/kargo/iletişim sayfaları bulundu ve erişilebilir (STR-21, IDX-1)", "güncellik: kişi"),
    "SEC-019": ("K", ["idx7.deep"], ["IDX-7"], "ürün/destek sayfalarının tıklama derinliği (sayfa gruplama)", "sayfa türü başına derinlik eşiği kuralı (S)"),
    "SEC-022": ("G", ["IDX-3", "idx6.broken"], [], "destek sayfalarında kırık bağlantı/yönlendirme", "konuların gerçek aramalarla eşleşmesi GSC ister"),
    "SEC-025": ("P", ["STR-6"], [], "tarihler (STR-6)", "faiz/uygunluk koşullarının doğruluğu: iş birimi"),
    "SEC-028": ("K", ["STR-8", "RND-1", "RND-2"], ["STR-8"], "ücret tabloları, yalnız JS sonrası gelen içerik (STR-8, RND-1/2)", "yalnız işlenmiş HTML'de olan form (S)"),
    "SEC-031": ("K", ["RND-1", "RND-2", "STR-15"], ["RND-1"], "yalnız JS sonrası metin, ince sayfa (RND-1/2, STR-15)", "varsayımların açıklanması: kişi"),
    "SEC-034": ("P", ["STR-6"], [], "belge tarihleri (STR-6)", "risk ve kapsam metni: uyum ekibi"),
    "SEC-037": ("K", ["STR-8", "STR-6", "idx7.deep"], ["STR-8"], "ücret tabloları, tarihler, derinlik (STR-8, STR-6)", "mobilde okunurluk: kişi"),
    "SEC-040": ("K", ["acc3.noindex", "IDX-1", "RND-5"], ["ACC-3"], "indeksleme, giriş duvarları (ACC-3, IDX-1, RND-5)", "adımlar ve ön koşullar: kişi"),
    "SEC-043": ("K", ["STR-21", "STR-5"], ["STR-21"], "hakkımızda/iletişim/destek sayfaları, tutarlı adlar (STR-21, STR-5)", "lisans bilgisi: kişi"),
    "SEC-046": ("A", ["RND-1", "RND-2", "acc3.noindex", "IDX-1"], ["RND-1"], "platform sayfalarının metni HTML'de, indeksleme (RND-1/2, ACC-3)", ""),
    "SEC-049": ("K", ["IDX-8"], ["IDX-8"], "birbirine çok benzeyen kart sayfaları (IDX-8)", "avantaj/ücret farkları: kişi"),
    "SEC-052": ("M-M", ["acc3.unavailable_passed"], [], "unavailable_after tarihi geçmiş (ACC-3)", "biten kampanya sayfaları (M), SEC-013 gibi"),
    "SEC-055": ("P", ["RND-3"], [], "sekmelerin arkasındaki metin (RND-3)", "kazanım/kullanım/geçerlilik kuralları: kişi"),
    "SEC-058": ("P", [], [], "", "uygunluk, belgeler: kişi"),
    "SEC-061": ("G", [], [], "", "aranabilir çözümler ile sorgular GSC ister"),
    "SEC-064": ("K", ["str3.article_no_author", "STR-6"], ["STR-3"], "yazar ve tarihler (STR-3, STR-6)", "inceleyen/lastReviewed işaretlemesi ya da görünür 'inceleyen' (S); tıbbi doğruluk: hekim"),
    "SEC-067": ("K", ["IDX-8", "str3.expected_type"], ["IDX-8"], "birbirine çok benzeyen biyografiler (IDX-8)", "doktor sayfalarında Physician/Person işaretlemesi (S); özgeçmiş doğruluğu: kişi"),
    "SEC-070": ("K", ["idx8.location_template", "str3.required", "STR-5"], ["IDX-8"], "konum kopyaları, LocalBusiness alanları (IDX-8, STR-3)", "sayfalar arasında NAP tutarlılığı (M)"),
    "SEC-073": ("K", ["idx7.deep", "STR-21"], ["IDX-7"], "tedavi sayfalarının derinliği, hakkımızda/iletişim (sayfa gruplama, STR-21)", "acil/yasal iletişimin görünürlüğü: kişi; ana sayfadan bağlantısı olmayan 1. sıra türü (S)"),
    "SEC-076": ("K", ["RND-1", "RND-2"], ["RND-1"], "yalnız JS sonrası gelen içerik (RND-1/2)", "ham HTML'de tel: bağlantısı ve form (S); mobil akış: kişi"),
    "SEC-079": ("P", [], [], "", "anlaşmalı kurum listesinin güncelliği: kişi"),
    "SEC-082": ("K", ["IDX-4", "IDX-8", "RND-3"], ["IDX-4"], "varyant canonical'ları, kopyalar, sekme içeriği (IDX-4, IDX-8, RND-3)", "teknik verilerin doğruluğu: kişi"),
    "SEC-085": ("K", ["STR-6"], ["STR-6"], "tarihler (STR-6)", "PDF fiyat listeleri: okunur, bağlantılı, dizinlenebilir (M)"),
    "SEC-088": ("A", ["STR-19", "idx7.pagination_unlinked", "str15.empty_collections", "IDX-8"], ["STR-19", "IDX-7"], "href'siz kartlar, sayfalama, boş listeler, kopyalar (STR-19, IDX-7, STR-15, IDX-8)", ""),
    "SEC-091": ("K", ["idx8.location_template", "str3.required", "STR-5"], ["IDX-8"], "konum kopyaları, LocalBusiness (IDX-8, STR-3)", "saat/NAP tutarlılığı (M)"),
    "SEC-094": ("K", ["RND-1", "RND-2", "RND-3"], ["RND-1"], "yalnız JS sonrası gelen konfigüratör içeriği (RND-1/2/3)", "seçilen donanım bağlantıları: kişi"),
    "SEC-097": ("M-S", [], [], "bağlantı grafiği var", "rehberlerin 1. sıra model sayfalarına bağlantısı (S)"),
    "SEC-100": ("K", ["STR-8", "RND-1", "RND-2"], ["STR-8"], "fiyat tabloları, yalnız JS sonrası tablo (STR-8, RND-1/2)", "aylık/yıllık, limitlerin açıklığı: kişi"),
    "SEC-103": ("K", ["IDX-8", "STR-1"], ["IDX-8"], "özellik başına ayrı adres (sayfa türü), kopyalar, title'lar", "sayfa başına hedef sorgu GSC ister"),
    "SEC-106": ("K", ["STR-1", "RND-1", "acc3.utility_indexable"], ["STR-1"], "title'lar, yalnız JS sonrası içerik (STR-1, RND-1)", "ham HTML'de form (S); teşekkür sayfasının dizinlenebilir olması (S)"),
    "SEC-109": ("A", ["ACC-3", "ACC-2", "acc3.utility_indexable", "STR-9"], ["ACC-3", "ACC-2"], "doküman index/noindex, robots, dizinlenebilir site içi arama, hreflang (ACC-3, ACC-2, STR-9)", "dokümanlardan özellik sayfalarına bağlantılar (S)"),
    "SEC-112": ("P", [], [], "", "referanslarda ölçülebilir sonuç: kişi"),
    "SEC-115": ("K", ["str3.expected_type"], ["STR-3"], "beklenen Product/Service işaretlemesi (STR-3)", "kapasite/bakım bilgisi: kişi"),
    "SEC-118": ("K", ["STR-21", "STR-5"], ["STR-21"], "iletişim sayfası, adlar (STR-21, STR-5)", "hizmet bölgesi, form akışı: kişi"),
    "SEC-121": ("P", [], [], "", "koşulların güncelliği: kişi"),
    "SEC-124": ("K", ["IDX-8", "STR-1"], ["IDX-8"], "birbirine çok benzeyen çözüm sayfaları, ortak title'lar (IDX-8, STR-1)", "niyet/anahtar kelime örtüşmesi GSC ister"),
    "SEC-127": ("P", ["STR-8", "STR-4"], [], "fiyat tabloları (STR-8)", "kapsam ve fiyat koşulları: kişi"),
    "SEC-130": ("K", ["RND-1", "RND-2"], ["RND-1"], "yalnız JS sonrası CTA/form (RND-1/2)", "mobil test: kişi"),
    "SEC-133": ("P", [], [], "", "sözleşme ve iddialar: hukuk"),
    "SEC-136": ("K", ["idx8.location_template", "IDX-8"], ["IDX-8"], "şehir/ilçe şablon kopyaları (IDX-8)", "gerçek hizmet kapsamı: kişi"),
    "SEC-139": ("K", ["STR-5"], ["STR-21"], "iletişim sayfası, adlar (STR-21, STR-5)", "HTML'de/işaretlemede tel: bağlantısı ve çalışma saatleri (S); mobil CTA: kişi"),
    "SEC-142": ("K", ["RND-1", "RND-2"], ["RND-1"], "yalnız JS sonrası gelen içerik (RND-1/2)", "ücret/iptal metni: kişi"),
    "SEC-145": ("K", ["idx7.deep"], ["IDX-7"], "hizmet sayfalarının tıklama derinliği (sayfa gruplama)", "ana sayfadan bağlantısı olmayan 1. sıra türü (S)"),
    "SEC-148": ("G", [], [], "", "karar soruları ile sorgu niyeti GSC ister"),
    "SEC-151": ("K", ["idx7.deep"], ["IDX-7"], "marka/aile sayfalarının adres düzeni ve derinliği", "sorgu niyeti ile kategori farkı GSC ister"),
    "SEC-154": ("K", ["STR-7", "IDX-8", "str3.expected_type"], ["STR-7"], "alt metin, yakın kopyalar, Product işaretlemesi (STR-7, IDX-8, STR-3)", "besin değerleri: kişi"),
    "SEC-157": ("P", [], [], "", "alerjen doğruluğu: gıda mühendisi"),
    "SEC-160": ("P", [], [], "", "sertifika geçerliliği: kişi"),
    "SEC-163": ("M-M", ["idx7.pagination_unlinked", "IDX-4"], [], "sayfalama, canonical'lar (IDX-7, IDX-4)", "şablon başına tarih/kişi/fiyat parametre kombinasyonları (M)"),
    "SEC-166": ("K", ["IDX-8", "STR-4"], ["IDX-8"], "kopyalar, fiyat işaretlemesi ile sayfa (IDX-8, STR-4)", "uygunluk tarihleri: kişi"),
    "SEC-169": ("K", ["STR-21"], ["STR-21"], "koşul/destek sayfaları bulundu ve bağlantılı (STR-21)", "koşulların açıklığı: kişi"),
    "SEC-172": ("M-M", ["acc3.unavailable_passed"], [], "unavailable_after tarihi geçmiş (ACC-3)", "biten teklifler (M), SEC-013 gibi"),
}

# Draft sector rows for the two profiles the team's file does not have (owner, 2026-11-08). Per page type (in the
# profile's order): the sector-specific check (check, how, criterion, tool, impact, action, mapping) and the two generic
# rows built from the team's own generic wording.
DRAFTS = [
    ("Havayolu (taslak)", "havayolu", [
        ("Destinasyonlar ve uçuş rotaları", ("Rota ve destinasyon sayfalarının tekilliği",
         "Şehir/rota sayfalarında şablon kopyalarını, kalkış-varış bilgisini, iç bağlantıları ve canonical'ı karşılaştır.",
         "Her rota/destinasyon sayfası kendine özgü bilgi taşır; kopya şablon yok; rota sayfaları HTML bağlantılarıyla bulunur.",
         "Crawler + GSC", 5, "Kopya rota şablonlarını özgün bilgiyle ayrıştır, iç bağlantıları güçlendir.",
         ("K", ["idx8.location_template", "IDX-8", "IDX-4"], ["IDX-8"], "rota sayfası kopyaları, canonical (IDX-8, IDX-4)", "rota bilgisinin doğruluğu: kişi"))),
        ("Uçuş arama ve uçuş takvimi", ("Uçuş arama ve takvim adreslerinin indekslenmesi",
         "Tarih/yolcu/sınıf parametreli arama sonuçlarının noindex, canonical ve robots davranışını ve takvim sayfalarının erişimini örnekle.",
         "Arama sonucu kombinasyonları dizine çoğalmaz; takvim/uçuş durumu sayfaları gerekiyorsa taranabilir.",
         "Crawler + GSC", 5, "Arama sonucu adreslerini noindex/canonical ile yönet; değerli takvim sayfalarını aç.",
         ("M-M", ["idx6.tracking", "IDX-8", "acc3.utility_indexable"], [], "izleme parametreleri, kopyalar, dizinlenebilir arama sayfası", "şablon başına parametre kombinasyonları (M)"))),
        ("Bilet fiyatları ve kampanyalar", ("Fiyat ve kampanya güncelliği",
         "Biten kampanyaların durumunu, fiyat bilgisinin tarihini ve listeden erişimi test et.",
         "Biten kampanyalar yönlendirilir ya da arşivlenir; fiyat iddiaları güncel ve tarihli.",
         "Crawler + manuel", 4, "Biten kampanyaları yönlendir ya da arşivle; fiyatlara tarih ekle.",
         ("M-M", ["acc3.unavailable_passed"], [], "unavailable_after tarihi geçmiş (ACC-3)", "biten kampanya sayfaları (M)"))),
        ("Bagaj", ("Bagaj kurallarının açıklığı",
         "Bilet sınıfına göre bagaj haklarını, ek ücretleri ve güncelleme tarihini sayfa içinde kontrol et.",
         "Bagaj hakları sınıf ve rotaya göre açık, HTML'de okunur ve güncel.",
         "Crawler + manuel", 4, "Bagaj haklarını sınıf ve rotaya göre HTML tabloda ve tarihli ver.",
         ("P", ["RND-1", "STR-6"], [], "yalnız JS sonrası içerik, tarih (RND-1, STR-6)", "kuralların doğruluğu ve açıklığı: kişi"))),
        ("Check-in ve online işlemler", ("Online işlem sayfalarının erişimi",
         "Check-in, rezervasyon yönetimi ve uçuş durumu sayfalarının bilgi içeriğinin giriş gerektirmeden ve JS olmadan erişimini test et.",
         "İşlem sayfalarının açıklayıcı içeriği giriş duvarı arkasında değil; form öncesi bilgi HTML'de.",
         "Crawler + JS render", 4, "Açıklayıcı içeriği giriş duvarının önüne ve sunucu HTML'ine taşı.",
         ("K", ["RND-5", "RND-1", "RND-2"], ["RND-1"], "giriş duvarları, yalnız JS sonrası içerik (RND-5, RND-1/2)", "işlem akışı: kişi"))),
        ("Rezervasyon yardımı ve koşullar", ("Değişiklik, iade ve koşul içeriği",
         "Değişiklik/iade/iptal koşullarını, ücretleri ve destek bağlantılarını kontrol et.",
         "Koşullar kolay bulunur, açık ve güncel; destek sayfalarına bağlantı var.",
         "Crawler + manuel", 4, "Koşulları tek, güncel sayfada topla; destek sayfalarından bağlantı ver.",
         ("K", ["STR-21"], ["STR-21"], "koşul/destek sayfaları bulundu (STR-21)", "koşulların açıklığı: kişi"))),
    ]),
    ("Restoran / kafe (taslak)", "restoran", [
        ("Menü", ("Menünün HTML'de okunması",
         "Menünün metin olarak mı yoksa yalnız görsel/PDF olarak mı sunulduğunu, fiyatları ve Menu işaretlemesini kontrol et.",
         "Menü öğeleri ve fiyatlar HTML metni olarak okunur; yalnız görsel ya da PDF değildir.",
         "Crawler + JS render", 5, "Menüyü HTML metin olarak yayınla; görsel/PDF yalnız ek olsun.",
         ("K", ["RND-1", "RND-2", "STR-15", "STR-7"], ["RND-1"], "yalnız JS sonrası içerik, ince sayfa, görseller (RND-1/2, STR-15, STR-7)", "menünün yalnız görsel/PDF olması kuralı (S)"))),
        ("Şube ve konum", ("Şube sayfaları ve NAP",
         "Her şubenin ayrı adresini, adres/telefon/çalışma saatini ve Restaurant/LocalBusiness işaretlemesini denetle.",
         "Her şube tekil sayfada; adres ve saatler sayfada ve işaretlemede tutarlı.",
         "Crawler + Rich Results Test", 5, "Her şubeye ayrı sayfa ve tutarlı LocalBusiness bilgisi ver.",
         ("K", ["idx8.location_template", "str3.required", "STR-5"], ["IDX-8"], "konum kopyaları, LocalBusiness alanları (IDX-8, STR-3)", "şubeler arası NAP tutarlılığı (M)"))),
        ("Rezervasyon / sipariş", ("Rezervasyon ve sipariş yolu",
         "Rezervasyon/sipariş CTA'larını, üçüncü taraf bağlantılarını ve JS formunun mobil erişimini test et.",
         "Rezervasyon/sipariş yolu çalışır; form öncesi gerekli bilgi HTML'de.",
         "Crawler + manuel mobil", 4, "Rezervasyon/sipariş yolunu sunucu HTML'inde ve mobilde çalışır tut.",
         ("K", ["RND-1", "RND-2", "RND-5"], ["RND-1"], "yalnız JS sonrası içerik, duvarlar (RND-1/2, RND-5)", "akışın çalışması: kişi"))),
        ("Ana sayfa", ("Menü ve şubelere erişim",
         "Ana sayfadan menü, şube ve rezervasyon sayfalarına HTML bağlantılarını ve derinliği kontrol et.",
         "Menü, şubeler ve rezervasyon ana sayfadan tek tıkla bulunur.",
         "Crawler", 4, "Menü, şube ve rezervasyon bağlantılarını ana sayfaya HTML olarak ekle.",
         ("K", ["idx7.deep"], ["IDX-7"], "tıklama derinliği (sayfa gruplama)", "ana sayfadan bağlantısı olmayan 1. sıra türü (S)"))),
        ("İletişim", ("İletişim ve çalışma saatleri",
         "Telefon, adres, çalışma saatleri ve harita bilgisinin görünürlüğünü kontrol et.",
         "İletişim bilgileri ve saatler açık, tıklanabilir ve güncel.",
         "Crawler + manuel", 4, "Telefonu tıklanabilir, saatleri güncel ve görünür yap.",
         ("K", ["STR-5"], ["STR-21"], "iletişim sayfası, adlar (STR-21, STR-5)", "saatlerin güncelliği: kişi"))),
    ]),
]
RANK_WEIGHTS = (1.0, 0.85, 0.7, 0.55, 0.4, 0.3)


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _rows(ws):
    it = ws.iter_rows(values_only=True)
    header = [str(x) for x in next(it)]
    return header, [dict(zip(header, r)) for r in it if r[0] is not None]


def build() -> dict:
    import openpyxl  # not a project dependency (see the module docstring)
    wb = openpyxl.load_workbook(SOURCE, data_only=True, keep_vba=False)
    meth = wb["Metodoloji"]
    methodology = [[_num(meth.cell(r, 1).value), _num(meth.cell(r, 2).value)] for r in range(1, meth.max_row + 1)]
    th, types = _rows(wb["Sektör Önceliği"])
    ch, core = _rows(wb["Ortak SEO Kontrolleri"])
    sh, sec = _rows(wb["Sektörel SEO Kontrolleri"])
    ws = wb["Audit Özeti"]
    summary_header = [ws.cell(5, c).value for c in range(1, 11)]
    summary_note = ws.cell(19, 1).value
    sys.path.insert(0, str(ROOT))
    from maya_audit import business_types as bt
    out_types, out_core, out_sec = [], [], []
    for t in types:
        pid = SECTOR_PROFILE[t["Sektör / İş Modeli"]]
        ids = {pt["label"]["tr"]: pt["id"] for pt in bt.profile(pid)["page_types"]}
        name = t["Öncelikli Sayfa Türü"]
        assert name in ids, (pid, name)
        out_types.append({"sector": t["Sektör / İş Modeli"], "rank": _num(t["Sayfa Önceliği"]), "page_type": name,
                          "weight": _num(t["Sayfa Ağırlığı"]), "note": t["Not"], "profile": pid, "type_id": ids[name], "draft": False})
    for c in core:
        st, rules, need, cov, miss = CORE[c["ID"]]
        out_core.append({"id": c["ID"], "group": c["Audit Grubu"], "check": c["SEO Kontrolü"], "how": c["Nasıl Kontrol Edilir?"],
                         "criterion": c["Başarı Kriteri"], "tool": c["Araç / Kanıt"], "impact": _num(c["Etki (1-5)"]),
                         "action": c["Önerilen Aksiyon"], "status": st, "rules": rules, "needs": need, "covered": cov, "missing": miss})
    type_id = {(t["sector"], t["page_type"]): (t["profile"], t["type_id"]) for t in out_types}
    for c in sec:
        dim = c["Audit Boyutu"]
        st, rules, need, cov, miss = SEC_SPECIFIC[c["ID"]] if dim == "Sektöre Özel" else GENERIC[dim]
        pid, tid = type_id[(c["Sektör"], c["Sayfa Türü"])]
        out_sec.append({"id": c["ID"], "sector": c["Sektör"], "rank": _num(c["Sayfa Önceliği"]), "page_type": c["Sayfa Türü"],
                        "dimension": dim, "check": c["SEO Kontrolü"], "how": c["Nasıl Kontrol Edilir?"], "criterion": c["Başarı Kriteri"],
                        "tool": c["Araç / Kanıt"], "impact": _num(c["Etki (1-5)"]), "weight": _num(c["Sayfa Ağırlığı"]),
                        "action": c["Önerilen Aksiyon"], "status": st, "rules": rules, "needs": need, "covered": cov, "missing": miss,
                        "profile": pid, "type_id": tid, "draft": False})
    # draft rows: the generic two from the team's own generic wording (SEC-002/003, "Kategori ve listeleme")
    gen = {r["dimension"]: r for r in out_sec if r["id"] in ("SEC-002", "SEC-003")}
    n = 0
    for sector, pid, rows in DRAFTS:
        ids = {pt["label"]["tr"]: pt["id"] for pt in bt.profile(pid)["page_types"]}
        for rank, (name, (check, how, crit, tool, impact, action, mapping)) in enumerate(rows, 1):
            assert name in ids, (pid, name)
            weight = RANK_WEIGHTS[rank - 1]
            out_types.append({"sector": sector, "rank": rank, "page_type": name, "weight": weight, "note": DRAFT,
                              "profile": pid, "type_id": ids[name], "draft": True})
            st, rules, need, cov, miss = mapping
            n += 1
            out_sec.append({"id": f"SEC-T{n:02d}", "sector": sector, "rank": rank, "page_type": name, "dimension": "Sektöre Özel",
                            "check": check, "how": how, "criterion": crit, "tool": tool, "impact": impact, "weight": weight,
                            "action": action, "status": st, "rules": rules, "needs": need, "covered": cov, "missing": miss,
                            "profile": pid, "type_id": ids[name], "draft": True})
            for dim in ("On-Page & Arama Niyeti", "İndeksleme & İç Link"):
                g = gen[dim]
                st, rules, need, cov, miss = GENERIC[dim]
                n += 1
                out_sec.append({"id": f"SEC-T{n:02d}", "sector": sector, "rank": rank, "page_type": name, "dimension": dim,
                                "check": g["check"].replace("Kategori ve listeleme", name), "how": g["how"].replace("Kategori ve listeleme", name),
                                "criterion": g["criterion"], "tool": g["tool"], "impact": g["impact"], "weight": weight,
                                "action": g["action"], "status": st, "rules": rules, "needs": need, "covered": cov, "missing": miss,
                                "profile": pid, "type_id": ids[name], "draft": True})
    sectors = list(dict.fromkeys(t["sector"] for t in out_types))
    return {"_about": "Built by tools/sector_method_build.py from the team's workbook (DECISIONS 324); do not edit by hand.",
            "source": str(SOURCE.relative_to(ROOT)), "draft_note": DRAFT,
            "headers": {"types": th, "core": ch, "sec": sh, "summary": summary_header},
            "methodology": methodology, "summary_note": summary_note,
            "sectors": [{"name": s, "profile": next(t["profile"] for t in out_types if t["sector"] == s),
                         "draft": any(t["draft"] for t in out_types if t["sector"] == s)} for s in sectors],
            "page_types": out_types, "core": out_core, "sec": out_sec}


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['core'])} CORE, {len(data['sec'])} SEC "
          f"({sum(1 for r in data['sec'] if r['draft'])} draft), {len(data['page_types'])} page types")
