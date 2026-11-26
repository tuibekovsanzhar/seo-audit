"""DECISIONS 378: the SEO team's own method for each checklist item (their pass condition), in the repository.

maya_audit/checklist_method.json comes from the team's SEO_Audit_Checklist.xlsx (SEO_AUDIT Drive folder, 11 Nov);
scripts/checklist_method.py rebuilds it from that file, finding columns by header text. Offline.
"""
from __future__ import annotations

from maya_audit import checklist, xlsx
from scripts import checklist_method as builder

HEADER = ["ID", "İş grubu", "Kontrol maddesi", "NASIL KONTROL EDİLİR?", "Beklenen / geçme koşulu",
          "Hata varsa yapılacak aksiyon", "Araç / veri", "Uygulanabilirlik", "Varsayılan öncelik", "Önerilen sıklık"]


def test_every_checklist_item_has_the_teams_method():
    for it in checklist.items():
        m = checklist.method(it["id"])
        assert m is not None and m["pass"].strip(), it["id"]
        assert m["method"] in {"Manuel / işletme kararı", "Ek veri / API + analiz", "Crawl + kural motoru",
                               "Tarayıcı / JS render botu", "AI destekli + uzman"}, it["id"]
        assert builder.COMMON_PASS not in m["pass"]                        # kept once, not on every row


def test_items_for_rule():
    hits = checklist.items_for_rule("idx2.temporary", "IDX-2")
    assert {"id": "SEO-009", "item": "Tek tercih edilen host",
            "pass": "Tek nihai HTTPS host 301/308 ile kullanılıyor."} in hits
    assert [h["id"] for h in hits] == sorted(h["id"] for h in hits)
    assert checklist.items_for_rule(None, None) == []


def test_the_builder_reads_columns_by_header(tmp_path):
    shuffled = [HEADER[i] for i in (4, 0, 3, 1, 2, 5, 6, 7, 8, 9)]
    row = {"ID": "SEO-001", "İş grubu": "01", "Kontrol maddesi": "Mülkiyet",
           "NASIL KONTROL EDİLİR?": "Hesapları listele. Kontrol yöntemi: Tarayıcı / JS render botu. Ortak testi SEO-134 "
                                    "altında çalıştır; aynı bulguyu iki kez sayma.",
           "Beklenen / geçme koşulu": "Erişim doğrulanmış. " + builder.COMMON_PASS,
           "Hata varsa yapılacak aksiyon": "Erişim iste.", "Araç / veri": "GSC", "Uygulanabilirlik": "Tüm siteler",
           "Varsayılan öncelik": "P1", "Önerilen sıklık": "İlk audit"}
    path = tmp_path / "list.xlsx"
    path.write_bytes(xlsx.workbook([{"name": "Sayfa1", "header": shuffled, "rows": [[row[h] for h in shuffled]]}]))
    got = builder.build(path)["items"]["SEO-001"]
    assert got == {"pass": "Erişim doğrulanmış.", "method": "Tarayıcı / JS render botu", "shared_test": "SEO-134",
                   "how": "Hesapları listele.", "action": "Erişim iste.", "tool": "GSC", "frequency": "İlk audit"}
