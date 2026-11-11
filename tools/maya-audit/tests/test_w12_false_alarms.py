"""Known false alarms from the 27 October live comparison, each kept fixed by a test (DECISIONS 265-268)."""
from maya_audit.language import detect_language, words_of

# A Turkish product list: every card ends "Sepete Ekle Ürünü İncele 2.si %10 indirimli" (seen live on a shop).
CARD = ("Bahar Esintisi koku kartuşu 300 ml. Sepete Ekle Ürünü İncele 2.si %10 indirimli. Bu ürün sizin için "
        "evinizde ve ofisinizde uzun süre kalıcı bir koku sağlar, daha fazla bilgi için ürün sayfasına bakın. ")


def test_an_ordinal_after_a_number_is_not_a_word():
    assert words_of("Ürünü İncele 2.si %10 indirim, 3üncü kat, the 2nd day") == ["Ürünü", "İncele", "indirim", "kat", "the", "day"]


def test_a_turkish_shop_list_with_ordinal_discounts_is_not_italian():
    guess = detect_language(CARD * 20, declared="tr")
    assert guess["language"] in ("tr", None) and guess["hits"].get("it", 0) == 0


def test_a_branch_page_with_og_type_article_and_no_markup_is_not_asked_for_article():
    from test_false_alarms import CFG, html, site
    from maya_audit.checks.structure import str3_structured_data
    article = '<meta property="og:type" content="article">'
    result, pages = site({"/": html("<h1>Örnek Ev Yemekleri</h1>"),
                          "/sube/kadikoy/": html("<h1>Kadıköy Şubesi</h1><p>Adres ve telefon.</p>", head=article),
                          "/blog/yazi/": html("<h1>Bir yazı</h1><p>Uzun bir yazı.</p>", head=article)})
    rows = [r for f in str3_structured_data(result, CFG, pages, set()).findings
            if "structured data type expected" in f.title for r in f.evidence.get("pages", [])]
    kinds = {r["url"].rsplit("/", 2)[-2]: r["page_kind"] for r in rows}
    assert "kadikoy" not in kinds and kinds.get("yazi") == "article"


def test_text_after_an_element_that_ended_the_head_early_is_body_text():
    # A site's accessibility widget printed inside <head> (FA-036): browsers show its labels; the raw view must count
    # them too, or RND-1 calls them "content that appears only after JavaScript".
    from maya_audit.analysis import analyze_html
    html = ('<!doctype html><html lang="tr"><head><title>Banka</title><div id="a11y"><button>Mavi Işık Filtresi</button>'
            '<span>Daha Büyük Metin</span></div><script src="/widget.js"></script></head><body><h1>Ana</h1></body></html>')
    a = analyze_html(html, "https://bank.example.test/")
    assert "Mavi Işık Filtresi" in a["_visible_text"] and "Daha Büyük Metin" in a["_visible_text"]
    assert not any(s.get("in_head") for s in a.get("external_scripts") or [])


def test_dialogue_in_a_blog_story_is_not_a_question_and_answer_block():
    # FA-037: a story's dialogue ("Bekir, yeni ay var değil mi bu gece?") read as five Q&A pairs, FAQPage suggested.
    from test_false_alarms import CFG, html, ld, site
    from maya_audit.checks.structure import str3_structured_data
    story = "".join(f"<p>{q}</p><p>{a}</p>" for q, a in [
        ("Bekir asıl sen ne yapıyorsun burada?", "Hiç, dedi, akşamı bekliyorum işte, başka ne yapayım bu saatte."),
        ("Bekir, yeni ay var değil mi bu gece?", "Var, dedi Bekir, uzun uzun gökyüzüne bakarak ve gülümseyerek."),
        ("Senden istesem, bu akşam beni sahile götürür müsün?", "Götürürüm elbet, dedi gülerek, ama önce işimi bitirmem gerek."),
        ("Peki annen ne der buna?", "Annem bir şey demez, o da gençti bir zamanlar, bilir bu halleri.")])
    faq = "".join(f"<h3>{q}</h3><p>{a}</p>" for q, a in [
        ("Siparişim ne zaman gelir?", "Siparişleriniz aynı gün içinde, genellikle bir saat içinde kapınıza ulaştırılır."), ("Paket servis ücretli mi?", "Hayır, belirli bir tutarın üzerindeki siparişlerde paket servis ücretsizdir."),
        ("Kartla ödeme yapabilir miyim?", "Evet, kuryemize kapıda kredi kartı ya da banka kartıyla ödeme yapabilirsiniz.")])
    article = ld({"@type": "BlogPosting", "headline": "Hamalın küfesi"})
    result, pages = site({"/": html("<h1>Ana</h1>"), "/blog/oyku/": html("<h1>Hamalın küfesi</h1>" + story, head=article),
                          "/paket-servis/": html("<h1>Paket servis</h1><h2>Sık sorulan sorular</h2>" + faq)})  # DECISIONS 340
    [suggest] = [f for f in str3_structured_data(result, CFG, pages, set()).findings if "FAQPage" in f.title]
    assert [r["url"].rsplit("/", 2)[-2] for r in suggest.evidence["pages"]] == ["paket-servis"]
