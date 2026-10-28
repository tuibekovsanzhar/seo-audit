# Örnekler

Müşteri verisi bu klasöre konmaz. Skill paylaşıldığında içinde marka verisi olmamalıdır.

- `ornek_report.json`: Uydurma marka ("Örnek Firma", ornek-firma.test), şema 1.20 biçiminde, **seyrek** bir rapor: DataForSEO, Lighthouse ve Firecrawl verisi yok. Eksik veri yollarını sınamak için kullanılır; bu durumda KPI, arama ve laboratuvar kutuları "Ölçülmedi" gösterir.
  ```bash
  python scripts/build_data.py examples/ornek_report.json --lang tr -o /tmp/data.json
  ```
- **Deneme (20 Ekim 2026):** Tasarım örneği `Maya-Audit-Professional.pdf`'in sayılarıyla kurulan bir fixture'dan (r3: 18 sorun, 50 sayfa, 123/245 sitemap, mobil 38) TR ve EN raporlar üretildi. Öncelikler (boş yanıtlar → sitemap → mobil performans) ve aksiyon sırası tasarım örneğiyle birebir çıktı; 4 sayfa, taşma yok. O fixture müşteri verisi içerdiği için burada değil.
- **Denetleyici sınaması:** uydurma sayı ("87 sayfa"), TR metinde İngilizce kelime, ham `[{'` verisi ve doldurulmamış alan → hepsi hata verdi; render `⟪YAZ⟫` varken basmadı; `--lang` verilmeden build çalışmadı.

- **Yapılacaklar (20 Ekim 2026):** r3 fixture'ında 18 sorun → 18 kart, 5 yapılacaklar sayfası (toplam 9 sayfa), 26 tıklanabilir link; kart taşması ve sayfa sayısı denetimi geçti. Seyrek örnekte 3 kart, 5 sayfa.
