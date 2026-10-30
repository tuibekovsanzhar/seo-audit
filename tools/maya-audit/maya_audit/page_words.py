"""The words that say what kind of page a page is, in English and Turkish with short German, French, Spanish and
Arabic lists beside them (review G21), and how they are compared (DECISIONS 229).

Every word is written folded: lower-cased the Turkish way and without diacritics (`fold`), so "İletişim", "ILETISIM"
and "iletisim" are one word, and so are "Ürünler" and "urunler", "Über uns" and "uber uns". STR-21's basic pages (`BASIC_PAGES`, `ADDRESS_ONLY`)
were moved here from checks/small_site.py unchanged; STR-3's page kinds (checks/structure.py `page_kind`) read the
folders, the category words and the buy-button words below.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .language import turkish_fold

# Turkish letters first; then the marked Latin letters of German, French, Spanish, Italian and Portuguese (G21), so
# "Über uns", "À propos" and "Añadir al carrito" compare like "uber uns", "a propos" and "anadir al carrito".
_PLAIN = str.maketrans({**dict(zip("çğıöşüâîûàáäãåèéêëìíïòóôõùúñ", "cgiosuaiuaaaaaeeeeiiioooouun")),
                        "œ": "oe", "æ": "ae", "ß": "ss"})


def fold(text: str | None) -> str:
    """Lower-cased the Turkish way and without diacritics, so "İletişim" and "iletisim" are the same word."""
    return turkish_fold(text or "").translate(_PLAIN)


def segments(url: str) -> list[str]:
    """The folded segments of an address's path, a file's extension left out ("/Hakkımızda.html" -> ["hakkimizda"])."""
    return [fold(s.rsplit(".", 1)[0] if "." in s else s) for s in urlsplit(url).path.split("/") if s]


def says(words: tuple[str, ...] | frozenset[str], text: str) -> bool:
    """Whether a folded text holds one of the words as a whole word ("bize-ulasin" is "bize ulasin" in a text)."""
    return any(re.search(rf"(?<![^\W_]){re.escape(w.replace('-', ' '))}(?![^\W_])", text) for w in words)


# -- STR-21: the basic pages --------------------------------------------------------------------------------------

# What a visitor and an engine expect a business site to have, and the words that mark each (English and Turkish,
# compared the Turkish way: folded, without diacritics).
BASIC_PAGES: dict[str, tuple[str, ...]] = {
    "About": ("about", "about-us", "who-we-are", "company", "our-story", "team", "hakkimizda", "hakkinda", "kurumsal", "biz-kimiz"),
    "Product or service": ("product", "products", "service", "services", "solutions", "pricing", "plans", "features", "shop",
                           "menu", "treatments", "urun", "urunler", "hizmet", "hizmetler", "hizmetlerimiz", "cozumler",
                           "fiyat", "fiyatlar", "fiyatlandirma", "tedaviler"),
    "Contact": ("contact", "contact-us", "get-in-touch", "locations", "iletisim", "bize-ulasin", "ulasim", "subeler",
                "iletisim-bilgileri", "bize-yazin"),
    "FAQ": ("faq", "faqs", "help", "support", "questions", "sss", "sikca-sorulan-sorular", "yardim", "destek",
            "sik-sorulan-sorular", "merak-edilenler"),
}
# The same kinds in German, French, Spanish, Italian and Arabic (G21), read exactly like BASIC_PAGES (merged below).
# Short on purpose: tel:/mailto: links, ContactPage/AboutPage markup and a shop's Product or cart form are read too.
BASIC_PAGES_MORE: dict[str, tuple[str, ...]] = {
    "About": ("ueber-uns", "uber-uns", "unternehmen", "a-propos", "qui-sommes-nous", "quienes-somos", "sobre-nosotros",
              "nosotros", "chi-siamo", "من-نحن"),
    "Product or service": ("produkte", "leistungen", "produits", "productos", "servicios", "tienda", "boutique",
                           "prodotti", "servizi"),
    "Contact": ("kontakt", "impressum", "contactez-nous", "contacto", "contactanos", "contatti", "standorte", "filialen",
                "sucursales", "اتصل-بنا"),
    "FAQ": ("hilfe", "haeufige-fragen", "aide", "preguntas-frecuentes", "ayuda", "domande-frequenti", "الأسئلة-الشائعة"),
}
BASIC_PAGES = {kind: words + BASIC_PAGES_MORE.get(kind, ()) for kind, words in BASIC_PAGES.items()}
# The start of a path segment that marks a kind whatever Turkish suffix follows (B09): "urunlerimiz", "menumuz",
# "subelerimiz". Compared folded, as the WHOLE segment (G24): the stem and a suffix of letters, nothing after a
# hyphen, so "/menu-settings" and "/sube-yonetimi-api" are not matched. Address segments only.
BASIC_PAGE_STEMS: dict[str, tuple[str, ...]] = {
    "Product or service": ("urun", "menu", "hizmet"),
    "Contact": ("sube", "iletisim"),
    "About": ("hakkimizda",),
}
# Words that mark a kind in a page's address and in the text of a footer link, and never in a title or a heading
# (DECISIONS 197): "hikayemiz" in an address is the About page; "hikayesi" in a title is any blog post about a story.
ADDRESS_ONLY: dict[str, tuple[str, ...]] = {
    "About": ("hikayemiz", "bizim-hikayemiz", "tarihce", "tarihcemiz", "bizi-taniyin", "ekibimiz", "vizyon-misyon", "misyon-vizyon",
              "sirket-profili"),
}

# -- STR-3: page kinds -------------------------------------------------------------------------------------------

# The first folder of a product's address, and of an article's. English words first (the lists STR-3 had).
PRODUCT_FOLDERS = frozenset({"product", "products", "shop", "store", "item", "items", "urun", "urunler", "magaza",
                             # German, French, Spanish, Italian (G21)
                             "produkt", "produkte", "produit", "produits", "producto", "productos", "prodotto"})
ARTICLE_FOLDERS = frozenset({"blog", "news", "article", "articles", "post", "posts", "insights", "stories", "journal",
                             "haber", "haberler", "makale", "makaleler", "yazilar", "rehber", "bilgi-bankasi", "duyurular",
                             # German, French, Spanish, Italian (item 11): a page's Article markup or og:type=article
                             # still counts first wherever it is (STR-6 reads both before the folder).
                             "nachrichten", "aktuelles", "artikel", "actualites", "actualite", "noticias", "articulos",
                             "notizie"})
# A folder anywhere in the address that makes the page a list of other pages: never a product, never an article.
CATEGORY_WORDS = frozenset({"kategori", "category", "etiket", "tag", "koleksiyon", "marka",
                            "kategorie", "categorie", "categoria", "collections"})
# The last segment of a pricing page's address, and of an FAQ page's.
PRICING_WORDS = frozenset({"pricing", "plans", "prices", "fiyatlar", "fiyatlandirma", "paketler", "preise", "tarifs",
                           "precios"})
# P2: the spelled-out forms too ("sıkça" folds to "sikca"; seen live: /sikca-sorulan-sorular, /frequently-asked-questions).
FAQ_WORDS = frozenset({"faq", "faqs", "sss", "sik-sorulan-sorular", "sikca-sorulan-sorular", "frequently-asked-questions",
                       "haeufige-fragen", "haeufig-gestellte-fragen", "preguntas-frecuentes", "questions-frequentes",
                       "foire-aux-questions", "domande-frequenti", "perguntas-frequentes", "veelgestelde-vragen"})
# The text of a button or a link that buys (folded: "Satın Al" is "satin al", "Añadir" is "anadir"). English and
# Turkish, then German, French, Spanish, Italian and Arabic (G21): whole phrases, not a bare "kaufen" or "comprar",
# which also name links such as "where to buy".
BUY_WORDS = ("sepete ekle", "sepete at", "satin al", "hemen al", "add to cart", "add to basket", "add to bag", "buy now",
             "in den warenkorb", "jetzt kaufen", "ajouter au panier", "acheter maintenant", "anadir al carrito",
             "agregar al carrito", "comprar ahora", "aggiungi al carrello", "أضف إلى السلة")
# A form whose address names the cart or the checkout buys too ("/cart/add", "/sepete-ekle", "/checkout/line-item/add",
# "?route=checkout/cart/add", "/warenkorb", "/panier/ajouter"). A structural sign: it holds in any language.
CART_ACTION = re.compile(r"(?<![a-z])(?:cart|basket|sepet|sepete|checkout|warenkorb|panier|carrito|carrello)(?![a-z])")

# -- restaurants (the owner's answer of 2026-10-15; read by the sector guess, DECISIONS 228) -----------------------

# Words in addresses, the navigation and headings (folded) that mark a restaurant's site: its menu, its branches,
# its bookings and its delivery.
RESTAURANT_WORDS = ("menu", "sube", "rezervasyon", "paket servis")


# P4: words a site's own header, menu and footer use for its controls, by language (folded), to tell a menu left in
# another language than the page ("My Cart" on a Turkish page). Whole labels or "/"-separated parts only. Left out:
# words used as they are in many languages (login, shop, blog, newsletter, online, sale, outlet, menu, home, contact),
# and language names, which a language switcher shows on purpose.
UI_WORDS = {
    "en": ("my cart", "cart", "shopping cart", "my basket", "basket", "wishlist", "favorites", "favourites",
           "my account", "sign in", "sign up", "log in", "log out", "sign out", "register", "create account",
           "checkout", "search", "about us", "contact us", "my orders", "track order", "customer service",
           "privacy policy", "terms of use", "cookie policy", "returns", "delivery", "shipping", "my favorites"),
    "tr": ("sepet", "sepetim", "sepete git", "favoriler", "favorilerim", "hesabim", "hesap", "giris yap", "uye girisi",
           "uye ol", "kayit ol", "cikis yap", "odeme", "arama", "iletisim", "hakkimizda", "anasayfa", "ana sayfa",
           "siparislerim", "siparis takibi", "yardim", "gizlilik politikasi", "kullanim kosullari",
           "cerez politikasi", "iade", "teslimat", "kargo"),
    "de": ("warenkorb", "mein konto", "anmelden", "registrieren", "abmelden", "merkzettel", "wunschliste", "kasse",
           "suche", "uber uns", "startseite", "datenschutz", "versand"),
    "fr": ("panier", "mon panier", "mon compte", "se connecter", "connexion", "s'inscrire", "inscription",
           "deconnexion", "favoris", "liste de souhaits", "recherche", "rechercher", "contactez-nous", "a propos",
           "accueil", "mentions legales", "livraison"),
    "es": ("carrito", "mi carrito", "mi cuenta", "iniciar sesion", "registrarse", "cerrar sesion", "favoritos",
           "lista de deseos", "buscar", "sobre nosotros", "inicio", "envio"),
    "it": ("carrello", "il mio account", "accedi", "registrati", "preferiti", "cerca", "chi siamo", "spedizione"),
    "pt": ("carrinho", "minha conta", "entrar", "cadastre-se", "favoritos", "pesquisar", "sobre nos"),
    "nl": ("winkelwagen", "mijn account", "inloggen", "registreren", "zoeken", "over ons", "verzending"),
}
UI_WORD_LANGUAGES: dict[str, frozenset] = {}
for _lang, _words in UI_WORDS.items():
    for _word in _words:
        UI_WORD_LANGUAGES[_word] = UI_WORD_LANGUAGES.get(_word, frozenset()) | {_lang}
