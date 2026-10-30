# Örnekler

Müşteri verisi bu klasöre konmaz. Skill paylaşıldığında içinde marka verisi olmamalıdır.

- **Gerçek şekil testi:** Maya demo modunun (`demo-shop.localhost`) report.json çıktısı dönüştürücüyle denendi. 21 bulgu → 9 ana kart + 12 ek kart. Kural 9 doğru uygulandı: "H1 yok" ve "meta description" bulguları Orta'ya çıktı. Doğrulanmamış RND-1 bulgusu eke taşındı.
  Kendi denemeniz için:
  ```bash
  python -m maya_audit_web --demo
  # demo audit'in report.json dosyasını alın, sonra:
  python scripts/from_maya_report.py report.json -o cards.json
  ```
- **Tam örnek (elle doldurulmuş):** Adile Sultan Ev Yemekleri, 15 Ekim 2026. Yalnızca hazırlayanın bilgisayarında durur: `Downloads/Maya_Audit_Rapor_Ornek_Adile/` (cards.json, HTML, PDF). Kaynağı Maya PDF'i ve canlı kontrollerdir, report.json değildir.
