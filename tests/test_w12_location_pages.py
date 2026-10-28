"""DECISIONS 264: place pages under one section whose text differs mostly by the place name (seen live: 72 branch
pages 0.89-0.95 alike). Offline fake site, the real audit and severity policy."""
from dataclasses import replace

from fakeserver import FakeServer, Response, Site
from maya_audit.audit import run_audit
from maya_audit.config import CrawlConfig
from test_deadline_hosted_hardening import QUIET
from test_review_fixes import TR, links, page

PLACES = {"kadikoy": "Kadıköy", "uskudar": "Üsküdar", "besiktas": "Beşiktaş", "atasehir": "Ataşehir",
          "maltepe": "Maltepe", "sisli": "Şişli"}
BODY = ("{p} şubemizde her gün taze ev yemekleri pişiriyoruz. {p} bölgesine paket servis yapıyoruz ve siparişlerinizi "
        "telefonla ya da internetten alıyoruz. Menümüzde çorbalar, ana yemekler, zeytinyağlılar ve tatlılar bulunur. "
        "Öğle saatlerinde yoğunluk olduğu için siparişinizi erken vermenizi öneririz. Ödeme kapıda nakit ya da kartla "
        "yapılabilir. Tüm yemeklerimiz aynı mutfak standardıyla hazırlanır ve günlük olarak değişen bir menü sunulur. ")


def idx8(bodies):
    routes = {"/robots.txt": Response(body="User-agent: *\nAllow: /\n", content_type="text/plain"),
              "/": page(f"<h1>Ana sayfa</h1><p>{TR}</p>" + links([f"/sube/{s}/" for s in PLACES] + ["/hakkimizda/"])),
              "/hakkimizda/": page(f"<h1>Hakkımızda</h1><p>{TR}</p>")}
    for slug, name in PLACES.items():
        routes[f"/sube/{slug}/"] = page(f"<h1>{name} Şubesi</h1><p>{bodies(name, slug)}</p>", title=f"{name} Şubesi")
    with FakeServer(Site(routes)) as fake:
        outcome = run_audit(fake.base_url + "/", replace(CrawlConfig(), **QUIET))
    [check] = [c for c in outcome.checks if c.check_id == "IDX-8"]
    return [f for f in check.findings if "differ mostly by the place name" in f.title]


def test_branch_pages_that_only_swap_the_place_name_are_one_medium_finding():
    [finding] = idx8(lambda name, slug: BODY.format(p=name) * 2)
    assert finding.title == "6 pages under /sube/ differ mostly by the place name in their address"
    assert finding.severity.value == "S3" and finding.evidence["section"] == "/sube/"


def test_branch_pages_with_their_own_text_are_not_reported():
    texts = {"kadikoy": "Rıhtımdaki şubemiz deniz otobüsü iskelesine iki dakika uzaklıkta ve sabah yedide açılıyor.",
             "uskudar": "Mihrimah Camii'nin karşısındaki dükkânımız 1987'den beri aynı ailenin elinde ve pazarları kapalı.",
             "besiktas": "Çarşının içindeki küçük salonumuzda öğrencilere özel öğle menüsü ve kitap köşesi var.",
             "atasehir": "Finans merkezinin yanındaki şubemiz kurumsal toplu sipariş ve toplantı ikramı hazırlıyor.",
             "maltepe": "Sahil parkına bakan bahçemizde yaz akşamları canlı fasıl ve mangal menüsü sunuyoruz.",
             "sisli": "Hastaneler bölgesindeki şubemiz gece yarısına kadar açık ve diyet menüsü hazırlıyor."}
    assert idx8(lambda name, slug: (texts[slug] + " ") * 6) == []
