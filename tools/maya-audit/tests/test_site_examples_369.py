"""DECISIONS 369: a site-wide or once-measured finding is not dropped from the Özet: its example is the file or address
measured and the value (sitemap dates, response time with its limit, HTML size, blocks, missing sitemap entries...), or
else the first measured value of its rows. Only a finding with no measured value at all stays out. Fake reports only."""
from __future__ import annotations

from maya_audit import client_appendix, xlsx
from maya_audit import client_selection as cs
from maya_audit.example_rows import measured_value, site_example

from test_v03_client_report import SITE, finding, report


def _f(rule, title, evidence, check="X"):
    return {"rule_id": rule, "title": title, "check_id": check, "evidence": evidence}


def test_each_site_level_finding_says_what_was_measured_where():
    stamped = _f("idx5.stamped", "x", {"documents": [{"sitemap": SITE + "/sitemap.xml", "urls": 412, "same_lastmod": 398,
                                                       "value": "2026-11-16T14:51:13+03:00"}]})
    assert site_example(stamped) == "sitemap.xml: 412 adresin 398 tanesinde lastmod aynı (2026-11-16)"
    slow = _f("prf1.slow", "1 page(s) take more than 2 s (median) to return their HTML",
              {"pages": [{"url": SITE + "/kategori/x", "samples": [{"ttfb_ms": 4800}, {"ttfb_ms": 4700}, {"ttfb_ms": 5100}]}]})
    assert site_example(slow) == "/kategori/x: yanıt 4,8 sn (3 ölçümün ortancası), eşik 2,0 sn"
    assert site_example(slow, "en") == "/kategori/x: response 4.8 s (median of 3), limit 2 s"
    images = _f("idx5.no_image_sitemap", "x", {"images": 227, "sitemap_files": 1})
    assert site_example(images) == "site haritası (1 dosya): <image:image> yok; sayfalarda 227 farklı görsel"
    big = _f("rnd6.large", "x", {"pages": [{"url": SITE + "/", "bytes": 1_322_633}], "threshold_bytes": 1_000_000})
    assert site_example(big) == "/: HTML 1.323 KB, sınır 1.000 KB"
    limited = _f("acc9.rate_limited_429", "x", {"blocked_by": [{"name": "Cloudflare", "status": 429}], "pages_requested": 7,
                                                "pages_blocked_or_challenged": 1, "pages": [{"url": SITE + "/all", "status": 429}]})
    assert site_example(limited) == "/all: HTTP 429 (Cloudflare), 7 istekten 1 tanesi"
    names = _f("str5.names", "x", {"variants": [{"name": "Shop", "pages": 9}, {"name": "Shop Ltd.", "pages": 3}]})
    assert site_example(names) == "site geneli: marka adı 2 biçimde yazılmış: «Shop», «Shop Ltd.»"
    assert site_example(_f("idx5.no_image_sitemap", "x", {})) is None


def test_a_measured_value_is_any_value_but_the_empty_words():
    assert measured_value("ilk yanıt 3664 ms") and measured_value("HTTP 302")
    assert not measured_value("—") and not measured_value("ayrıntı kaydedilmedi (rapor yalnız örnek sayfaları saklar)")
    assert not measured_value("bu sayfada görüldü (bkz. Sorun)") and not measured_value(None)


def test_the_summary_lists_a_site_wide_finding_with_its_measured_value_and_leaves_out_one_with_none():
    sitemap = finding("S", "idx5.no_image_sitemap", "S4", urls=[SITE + "/"], check="IDX-5")
    sitemap["evidence"] = {"images": 505, "sitemap_files": 6}
    empty = finding("E", "str3.article_no_author", "S4", urls=[SITE + "/b"], check="STR-3")
    empty["evidence"] = {"articles": 4}
    book = xlsx.read(client_appendix.build(cs.select(report([sitemap, empty])), "tr",
                                           todos=[{"n": None, "appendix_only": True, "finding_ids": []}]))
    summary = book["Özet"]
    at = next(i for i, r in enumerate(summary) if str(r[1]).startswith("Diğer bulgular"))
    assert summary[at][1].endswith("; ölçülen değeri olmayan 1 bulgu yalnız «Bulgular» sayfasında")
    listed = summary[at + 1:]
    assert len(listed) == 1 and listed[0][-1] == "site haritası (6 dosya): <image:image> yok; sayfalarda 505 farklı görsel"
