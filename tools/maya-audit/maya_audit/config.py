from __future__ import annotations

from dataclasses import dataclass, field

from .intent import DeclaredPolicy, IntentMarking

PRODUCT_TOKEN = "Maya-Audit"
# Never written to reports or logs (replaced with "redacted" when set).
SECRET_FIELDS = ("gsc_access_token", "bing_api_key", "indexnow_key", "site_verification_token", "google_api_key",
                 # DataForSEO credentials are never put in CrawlConfig at all (see maya_audit/dataforseo);
                 # they are listed so that a field added under either name could not reach a report.
                 "dataforseo_login", "dataforseo_password", "firecrawl_api_key")
PRODUCT_VERSION = "0.2"
# ACC-2: a robots.txt rule that only keeps bots out of paths like these is ordinary housekeeping, not a
# visibility problem. A URL is "private or technical" when one of its path segments (lower-cased, file
# extension dropped) is in this set. English and Turkish; policy, not fact, and reported with each finding.
PRIVATE_PATH_SEGMENTS = frozenset({
    # shopping and payment
    "checkout", "cart", "basket", "bag", "payment", "pay", "order", "orders", "order-tracking", "wishlist", "compare",
    "sepet", "sepetim", "odeme", "siparis", "siparisler", "siparislerim", "siparis-takip", "favoriler", "favorilerim",
    "karsilastir",
    # accounts
    "account", "my-account", "myaccount", "profile", "login", "log-in", "signin", "sign-in", "logout", "signup",
    "sign-up", "register", "password", "forgot-password", "reset-password", "member", "members",
    "hesap", "hesabim", "uye", "uyelik", "uye-girisi", "uye-giris", "uye-ol", "uyeol", "giris", "giris-yap", "cikis",
    "kayit", "kayit-ol", "sifre", "sifremi-unuttum", "profil", "profilim",
    # site machinery
    "admin", "administrator", "wp-admin", "wp-login", "wp-json", "wp-includes", "cgi-bin", "cdn-cgi", "api", "ajax",
    "xmlrpc", "feed", "preview", "search", "arama", "ara", "yonetim", "panel", "tmp", "temp", "cache",
    # the signed-in product itself: the app, its dashboard and settings (added 2026-10-07: a Disallow: /app/ on a
    # software site was reported as a Medium block of search bots)
    "app", "dashboard", "console", "portal", "settings", "billing", "subscribe", "subscription", "onboarding",
    "auth", "oauth", "sso", "backoffice", "workspace",
    "uygulama", "kontrol-paneli", "yonetim-paneli", "ayarlar", "hesap-ayarlari", "abonelik", "faturalama", "fatura",
    "oturum", "oturum-ac", "giris-yap", "kullanici",
})

# ACC-3 (DECISIONS 222): a utility page, usually left out of search on purpose: the private and technical paths, and a
# QR menu, a print page, a thank-you page and the site's search. A segment of the path, as in PRIVATE_PATH_SEGMENTS.
UTILITY_PATH_SEGMENTS = PRIVATE_PATH_SEGMENTS | frozenset({
    "qr-menu", "qrmenu", "qr", "print", "yazdir", "thank-you", "thanks", "tesekkurler", "search", "arama",
})

# RND-5: a page that belongs to one signed-in customer. A redirect from one of these to the login page is what such
# a page should do, and is a note, not a wall (DECISIONS 173). A page is one of these when a segment of its path,
# compared without case, Turkish letter marks or a file extension ("/Hesabim.aspx"), is in this set. An agent default.
ACCOUNT_PATHS = frozenset({
    "account", "my-account", "hesabim", "hesabım", "musteri-hesabi", "uyelik", "uye-girisi", "uye-ol", "giris", "giris-yap",
    "login", "signin", "register", "kayit", "sepet", "sepetim", "cart", "basket", "checkout", "odeme", "siparis",
    "siparislerim", "orders", "favori", "favorilerim", "wishlist", "profil", "profile", "adreslerim"})
# RND-5: query parameters with which a login page is told where to send the visitor back ("/login?ReturnUrl=%2Fsepet").
LOGIN_RETURN_PARAMS = frozenset({"returnurl", "return_url", "return_to", "redirect", "next", "continue"})

# Text or a price that appears on at least this share of the audited pages is treated as site furniture
# (a menu, a footer, a "from 29 USD" banner), not as one page's own content. Needs enough pages to tell.
SITEWIDE_SHARE = 0.6
SITEWIDE_MIN_PAGES = 4
# STR-4: a text block on at least this share of the audited pages, and on at least TEASER_MIN_PAGES of them, is a
# teaser the site repeats (a carousel of blog cards), not one page's own content: a price inside it is not taken for
# the page's price. Lower than SITEWIDE_SHARE on purpose: a teaser block sits on a section of a site, not on all of
# it. Not calibrated (docs/LAUNCH-GATE.md).
TEASER_SHARE = 0.25
TEASER_MIN_PAGES = 5
# IDX-8 compares main content only; a page with fewer words of its own than this is not compared.
MIN_MAIN_WORDS_TO_COMPARE = 30

# RND-4: an iframe from one of these hosts (or a host ending in one) carries a tracker, a consent tool or a
# bot check, never page content. Policy, not fact; the number ignored is reported.
TRACKING_IFRAME_HOSTS = frozenset({
    "googletagmanager.com", "google-analytics.com", "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "facebook.com", "facebook.net", "hotjar.com", "clarity.ms", "bing.com", "linkedin.com", "licdn.com", "tiktok.com",
    "twitter.com", "t.co", "pinterest.com", "snapchat.com", "sc-static.net", "criteo.com", "criteo.net", "yandex.ru",
    "yandex.com", "mc.yandex.ru", "taboola.com", "outbrain.com", "adform.net", "insider.com", "useinsider.com",
    "segment.com", "segment.io", "hubspot.com", "hs-analytics.net", "cookiebot.com", "onetrust.com", "cookielaw.org",
    "recaptcha.net", "hcaptcha.com", "challenges.cloudflare.com", "stripe.com", "stripe.network", "paypal.com",
})
# ... and an iframe whose address looks like one of these, whatever host serves it (a server-side Tag Manager
# on the site's own subdomain serves /ns.html?id=GTM-XXXX).
TRACKING_IFRAME_PATTERN = r"/ns\.html\?id=GTM-|[?&]id=GTM-|/gtm\.|/recaptcha/|/tr\?id=|/pixel[./?]|/collect\?|/beacon[./?]|about:blank"
# RND-4: a <canvas> whose id or class says it is an effect, not a chart.
DECORATIVE_CANVAS_HINT = (r"particle|confetti|firework|snow|sparkle|star|wave|gradient|background|backdrop|\bbg\b|[-_]bg\b|"
                          r"\bbg[-_]|anim|effect|decor|lottie|three|webgl|shader|noise|blob|glow|cursor|trail|ripple|"
                          r"hero|fluid|aurora|matrix|canvas-bg")

# STR-12: a page whose main content is at least this share in a language it does not declare is reported.
FOREIGN_CONTENT_SHARE = 0.5
# ... when at least this many words of main content could be assigned to a language.
MIN_WORDS_FOR_LANGUAGE_SHARE = 40
# STR-12: a page with at least this many headings in one language it does not declare is reported, whatever
# the share of its body text (a template's leftover section titles sit among real content).
MIN_FOREIGN_HEADINGS = 3
# STR-12: titles and degrees that go with a person's name. A heading that carries one is a name ("Prof. Dr. Vehbi
# Alp Üçok", "Pelin Taş, M.D."), and a name says nothing about the language of a page. The second group is also
# an ordinary word in some language ("op", "doc", "av"), so it counts only when written with its full stop.
PERSONAL_TITLES = ("prof", "dr", "doç", "uzm", "psk", "dyt", "fzt", "md", "m.d", "phd", "ph.d", "msc", "m.sc")
PERSONAL_TITLES_WITH_STOP = ("op", "doc", "yrd", "yard", "ecz", "öğr", "arş", "gör", "av", "kl", "dt", "hem", "mr", "mrs", "ms")
# ... and a short heading with every word capitalised and no common word of any language is treated as a name too.
MAX_NAME_WORDS = 4
# Render-assisted link discovery: the rendered page has "clearly more" links to this site than its raw HTML when
# it adds at least this many targets and at least this share on top of the raw ones.
RENDER_DISCOVERY_MIN_NEW_LINKS = 5
RENDER_DISCOVERY_MIN_GROWTH = 0.5
# STR-14: anchor texts that say nothing about the page they lead to. Compared after lower-casing the Turkish way
# and dropping punctuation and arrows, so "Devamını Oku »" matches "devamını oku".
GENERIC_ANCHORS = (
    "click here", "click", "here", "read more", "more", "learn more", "see more", "view more", "more info",
    "more information", "details", "view details", "see details", "link", "this link", "this page", "go", "continue",
    "continue reading", "view", "see all", "view all",
    "tıklayın", "tıklayınız", "tıkla", "buraya tıklayın", "buraya tıklayınız", "buraya tıkla", "burada", "buradan",
    "buraya", "devamı", "devamını oku", "devamını gör", "devamı için tıklayın", "devam", "devam et", "daha fazla",
    "daha fazlası", "daha fazla bilgi", "daha fazla oku", "detay", "detaylar", "detaylı bilgi", "detaylı incele",
    "detayları gör", "ayrıntılar", "incele", "git", "bağlantı", "tümünü gör", "tümü", "hepsini gör", "oku",
)
# STR-15: an indexable content page whose own text has fewer words than this is reported (Info).
THIN_CONTENT_WORDS = 150
# ... unless its address or title says it is a page that is short by nature.
THIN_CONTENT_EXEMPT = (
    "iletisim", "iletişim", "contact", "kontakt", "bize-ulasin", "bize ulaşın", "ulasim", "ulaşım", "randevu", "appointment",
    "kvkk", "gizlilik", "privacy", "cerez", "çerez", "cookie", "terms", "kosullar", "koşullar", "sartlar", "şartlar",
    "sozlesme", "sözleşme", "yasal", "legal", "impressum", "aydinlatma", "aydınlatma", "login", "giris", "giriş", "uye",
    "üye", "register", "kayit", "kayıt", "sepet", "cart", "checkout", "odeme", "ödeme", "search", "arama", "sitemap",
    "site-haritasi", "404", "tesekkur", "teşekkür", "thank",
)
# STR-7: image formats built for the web's current browsers, and the older ones they replace.
NEXT_GEN_IMAGE_TYPES = ("webp", "avif")
OLDER_IMAGE_TYPES = ("jpg", "jpeg", "png", "gif", "bmp")
MIN_IMAGES_FOR_FORMAT_SHARE = 10
# STR-12: text left behind by a template or a site builder. Matched case-insensitively in the running text of
# main content only, never in a title, a heading or a link label: "Sample Page", "Örnek Sayfalar" and
# "Hello world!" are also what real pages are called, so they are not in this list.
PLACEHOLDER_TEXT = (
    "lorem ipsum", "dolor sit amet", "consectetur adipiscing", "this is an example page",
    "this is a sample", "sample text", "dummy text", "placeholder text", "your company name", "company name here",
    "your business name", "your text here", "your title here", "your content here", "insert text here",
    "add your content here", "add your text here", "enter your text", "text goes here", "content goes here",
    "title goes here", "replace this text", "edit this text", "click here to edit", "welcome to wordpress",
    "this is your first post", "just another wordpress site",
    "örnek metin", "deneme yazısı", "deneme metni", "metin buraya", "buraya metin", "içerik buraya",
    "buraya içerik", "başlık buraya", "şirket adınız", "firma adınız", "firma adı buraya", "içerik eklenecek",
    "açıklama eklenecek", "metninizi buraya",
)

# --save-evidence: what one saved page may hold, and how much one audit may save in all.
EVIDENCE_MAX_TEXT_CHARS = 20_000
EVIDENCE_MAX_JSONLD_CHARS = 40_000
EVIDENCE_MAX_PAGES = 500
EVIDENCE_MAX_TOTAL_BYTES = 20 * 1024 * 1024

# STR-13: markers a template engine or an editor should have replaced before the page was published.
# Each is (name, regular expression). Matched in visible text, the title, meta tags, JSON-LD and link or
# image addresses. Deliberately narrow: an identifier inside the brackets, not any bracketed text.
TEMPLATE_MARKERS = (
    ("{{...}}", r"\{\{\s*[#/^>!&]?\s*[\w$.\-:| ]{1,60}?\s*\}\}"),
    ("{%...%}", r"\{%-?\s*[\w$.\-:|'\" ]{1,80}?\s*-?%\}"),
    ("[[...]]", r"\[\[\s*(?=[^\]]*[A-Za-z_])[\w$.\-:| ]{1,60}?\s*\]\]"),   # [[cta]], not the footnote [[1]]
    # An editor's note in single guillemets, written tight: ‹teyit›. Not "‹ Önceki" / "Sonraki ›" pagination arrows.
    ("‹...›", r"‹[^\W\d_]+(?:[ \-][^\W\d_]+){0,3}›"),
    ("${...}", r"\$\{\s*[\w$.\-]{1,60}\s*\}"),
    ("<%...%>", r"<%=?\s*[\w$.\-() ]{1,60}?\s*%>"),
    ("%7B...%7D", r"%7B(?:%7B)?[\w$.\-]{1,60}%7D(?:%7D)?"),
    ("{...} in a URL", r"(?<=/)\{[\w$.\-]{1,60}\}(?=$|[/?#])"),
)
# IDX-6: query parameters that tag a visit for analytics. On a link from the site to itself they create a second
# address for the same page and credit the visit to the wrong source.
TRACKING_PARAMETERS = frozenset({
    "gclid", "gbraid", "wbraid", "dclid", "fbclid", "msclkid", "ttclid", "twclid", "li_fat_id", "yclid", "mc_cid",
    "mc_eid", "igshid", "_hsenc", "_hsmi", "hsctatracking", "srsltid", "_ga", "_gl", "ref_src",
})
TRACKING_PARAMETER_PREFIXES = ("utm_",)


def estimated_duration_s(max_pages: int, key_pages: int = 0, delay_s: float = 1.0, render: bool = True,
                         render_budget: int = 20, prf: bool = True, sitemap_check: int = 0, external_links: int = 0) -> float:
    """A rough upper estimate of how long an audit takes, from five live 10-page runs (170-217 s each).

    About (3 + delay) seconds a page to crawl, 8 a rendered page, and 150 for robots.txt sampling,
    link checks and the performance rounds. Uncalibrated beyond that; it exists so a larger run gets
    a time limit that fits instead of losing its last checks. The sitemap check (IDX-5, DECISIONS 206) adds
    (delay + 0.3) seconds for each of its at most `sitemap_check` light requests: an upper estimate, since the URLs
    the crawl already read cost nothing. The requests to other sites (DECISIONS 211) add the same for each of their
    at most `external_links` (`external_link_cap`): also an upper estimate for sites that answer, while a site that does
    not answer costs up to the request timeout once (its robots.txt) and is then asked nothing more.
    """
    pages = max_pages + key_pages
    rendered = min(render_budget, pages) if render else 0
    return (pages * (3 + delay_s) + rendered * 8 + (150 if prf else 60)
            + (max(0, sitemap_check) + max(0, external_links)) * (delay_s + 0.3))


# Fast check (DECISIONS 219): what each optional request cap becomes. Rendered pages are decision 27's template slots.
FAST_RENDER_BUDGET = 6
FAST_SITEMAP_CHECK_MAX = 50
# The sitemap check's sample (Owner, 2026-11-02; DECISIONS 294; were 1,000 and 200).
STANDARD_SITEMAP_CHECK_MAX = 300
QUICK_SITEMAP_CHECK_MAX = 100
FAST_LLMS_LINK_CHECKS_MAX = 20
FAST_IMAGE_CHECKS_MAX = 10
FAST_KEY_IMAGE_CHECKS_MAX = 15
FAST_EXTERNAL_LINK_CHECKS_MAX = 30


def external_link_cap(max_ceiling: int, base: int, pages_read: int, single_page: bool = False) -> int:
    """How many requests to other sites an audit may send, robots.txt included (DECISIONS 211): the base plus one for
    each page read, at most the ceiling; the base alone in a single-page audit (20: that page's links)."""
    return max(0, min(max_ceiling, base if single_page else base + max(0, pages_read)))


def default_time_limit_s(*args, **kwargs) -> float:
    """The time limit used when none is given: the estimate plus a quarter, in half minutes, never under 300 s."""
    return float(max(300, -(-estimated_duration_s(*args, **kwargs) * 1.25 // 30) * 30))


# DataForSEO backlink panel: a referring domain whose spam score (0-100, DataForSEO's own measure) is
# at or above this is counted as "looks like spam". Policy, not fact; every report states the value used.
SPAM_SCORE_THRESHOLD = 50


@dataclass(frozen=True)
class CrawlConfig:
    """Crawl limits and policy thresholds.

    Every threshold here is policy, not fact (spec §1): the report records the
    values used so a finding can always be traced back to the rule that fired.
    """

    # The token matched against robots.txt `User-agent` lines (RFC 9309).
    product_token: str = PRODUCT_TOKEN
    # Optional public page explaining the crawler. If configured, its status is
    # recorded in INT-4; a missing or unavailable page never blocks a crawl.
    bot_info_url: str | None = None

    max_pages: int = 50
    # A single-page audit (Owner, 2026-10-13): only the address given is read and checked. No link is followed, no
    # sitemap is asked for and no key page is added; the page cap is 1. What the page depends on that belongs to the
    # site (robots.txt, the redirects that lead to it, http:// to https:// on its host) is still looked at.
    single_page: bool = False
    time_limit_s: float = 300.0
    # Part of the time limit kept for a page reader that runs after Maya's own crawl (maya_audit.runclock). The crawl
    # stops this long before the limit; the reader and the paid panels may use the rest.
    reader_reserve_s: float = 0.0
    # Requests to the audited site in flight at once after the crawl, Maya's own and the page reader's together
    # (maya_audit.sitelimit, DECISIONS 294): 1 to 10. Starts stay at least the polite gap apart. 1 when robots.txt sets
    # a Crawl-delay or the crawl was rate-limited.
    site_concurrency: int = 5
    # The crawl stops fetching new pages once it has used this share of the time limit. 1.0 (DECISIONS 219; was 0.6):
    # page reading is never cut to make room for the checks; the later steps lose their optional requests instead
    # (other-site links first, then llms.txt links, the sitemap check, the performance rounds and rendering).
    crawl_time_share: float = 1.0
    # IDX-1: ask once for an address that cannot exist, to see whether the site answers 404 for missing pages.
    soft_404_probe: bool = True
    # Set true when hosted; permits localhost only for explicit local development.
    block_loopback: bool = False
    # Spec IDX-1 / PRF-1 refer to "Maya's 15 s timeout".
    request_timeout_s: float = 15.0
    request_delay_s: float = 1.0
    # Faster requests (DECISIONS 219 part 2; amends 82). On: each host has its own gap; the requests to other sites
    # run in a pool of `other_site_workers` threads (one other site at a time each, its robots.txt first, at that
    # site's own gap) while the audited site stays on the audit's own thread, one request at a time; and the audited
    # site's gap narrows by `pacing_factor` after `pacing_clean_answers` clean answers in a row (2xx, 3xx, 404 or 410,
    # first byte within `pacing_clean_ttfb_ms`), never below `min_request_delay_s` nor a robots.txt Crawl-delay. A
    # 429, a 5xx, a timeout, a failed connection or a first byte later than `pacing_reset_ttfb_ms` puts the gap back
    # to the configured one and stops the narrowing for the rest of the audit. Off: one gap for every host, no pool,
    # no narrowing: the request order of before (for tests).
    adaptive_pacing: bool = True
    min_request_delay_s: float = 0.5
    pacing_clean_answers: int = 20
    pacing_factor: float = 0.75
    pacing_clean_ttfb_ms: float = 1500.0
    pacing_reset_ttfb_ms: float = 2000.0
    other_site_workers: int = 4
    # A declared Crawl-delay is honored up to this ceiling; the real declared
    # value is still reported (INT-4 evidence, ACC-7 finding).
    max_crawl_delay_s: float = 90.0
    max_body_bytes: int = 5 * 1024 * 1024

    # 429 handling: wait and retry once if Retry-After is at most this long;
    # a longer requested wait stops the crawl (INT-2 stop reason rate_limit).
    # A Retry-After up to this long is waited out once (429, or 503 with Retry-After); a longer one stops the crawl.
    # 30 s (was 5 s, A13): a 10-second Retry-After is a routine answer, not a reason to end the audit.
    max_retry_after_s: float = 30.0
    # The start page alone (DECISIONS 286): a 429 there with a Retry-After up to this long is waited out once, because
    # without it nothing at all is read (nihan.com.tr answered its first page request with 429 and Retry-After: 60).
    start_max_retry_after_s: float = 120.0
    # Stop after this many consecutive rate-limited pages without Retry-After.
    rate_limit_stop_after: int = 3
    # Adaptive backoff. A rate-limited response widens the gap between *all* later requests by this
    # factor, and the widened gap is never narrowed again for the rest of the crawl. A site that
    # says "slow down" once is telling us something about the whole crawl, not about one URL, and
    # returning to the original pace after a single pause is how a polite crawler becomes a rude one.
    rate_limit_backoff_factor: float = 2.0
    # Where the crawl frontier lives. None keeps it in memory, which is a crawl that cannot be
    # resumed; a path makes the frontier outlive the process so --resume can continue it.
    db_path: str | None = None
    resume: bool = False
    # Ceiling on the widened gap, so backoff cannot stall a crawl indefinitely.
    max_request_delay_s: float = 30.0
    # Total time spent waiting out rate limits before the crawl gives up. Past this, the site has
    # spent long enough telling Maya to go away that continuing is not a judgment call.
    max_total_cooldown_s: float = 1800.0

    # INT-1: audit is "degraded" when at least this share of fetched pages is
    # blocked or rate-limited, or when the start URL is (spec INT-1 rule).
    degraded_threshold: float = 0.20

    max_sitemap_docs: int = 50
    # Share of the crawl's time limit that sitemap discovery may use. A site with dozens of sitemap
    # documents (one real site had 50, listing 8,133 URLs) would otherwise spend the whole budget on
    # sitemaps and never fetch a page.
    sitemap_time_share: float = 0.25
    max_sitemap_depth: int = 3
    max_sitemap_bytes: int = 10 * 1024 * 1024
    # RFC 9309 lets parsers ignore content past 500 KiB.
    max_robots_bytes: int = 500 * 1024

    # User-marked key pages (spec §8 Q3). Auto-suggestion is not built yet.
    key_pages: tuple[str, ...] = ()
    # The business type ("İşletme türü", DECISIONS 311): "auto" (suggested from the homepage and addresses), or a profile
    # id of maya_audit.business_types. It weights page importance and key pages only; no check reads it.
    business_type: str = "auto"

    # Additional hosts allowed for redirects or optional cross-origin checks.
    # The requested start host is added automatically for each audit.
    allowed_live_hosts: frozenset[str] = field(default_factory=frozenset)
    # Extra trust store (PEM) for TLS verification; used by tests with a local CA.
    ca_bundle: str | None = None

    # --- ACC checks ---------------------------------------------------------
    policy: DeclaredPolicy = field(default_factory=DeclaredPolicy)
    intent_markings: tuple[IntentMarking, ...] = ()
    # Ownership verification (meta tag method) gates ACC-4 probes and ACC-1
    # per-bot robots.txt fetches (spec §8 Q1).
    site_verification_token: str | None = None
    # Also look for the token in the domain's DNS TXT record (one lookup through a public DNS-over-HTTPS resolver).
    site_verification_dns: bool = False
    probes_enabled: bool = True
    max_probe_requests: int = 150
    probe_sample_size: int = 12
    probe_retries: int = 2
    probe_retry_cooldown_s: float = 30.0
    # ACC-4 without ownership (DECISIONS 205, LG-77): at most this many URLs, each asked once with a browser user agent
    # and once with Googlebot's, tagged and never retried. 0 switches it off.
    ua_check_urls: int = 3
    degraded_word_ratio: float = 0.5
    # ACC-1: fetch robots.txt this many times, this far apart, to catch intermittent 5xx.
    robots_samples: int = 3
    robots_sample_interval_s: float = 120.0
    # ACC-2 URL sample size (homepage, one per template, key pages, sitemap sample).
    url_sample_size: int = 30
    # ACC-3 thresholds (policy).
    min_max_snippet: int = 50
    # Round-number estimate, not calibrated: revisit once real pages are available to check it against.
    data_nosnippet_share: float = 0.9
    # ACC-7: "very high" crawl-delay (policy).
    high_crawl_delay_s: float = 60.0
    # ACC-5 (T3): access logs and vendor IP-range files, all local.
    access_logs: tuple[str, ...] = ()
    access_log_format: str = "combined"  # "combined" (nginx) | "cloudflare_logpush"
    ip_range_files: tuple[tuple[str, str], ...] = ()  # (bot token, path)

    # --- IDX checks ---------------------------------------------------------
    # IDX-1: refetch 5xx and transport failures once, this long after the crawl.
    refetch_delay_s: float = 5.0
    max_refetches: int = 20
    # IDX-1: a 2xx answer under this many bytes, with no title and no visible text, is an empty page (DECISIONS 204,
    # LG-75). Empty pages are refetched once too, within max_refetches.
    empty_response_max_bytes: int = 512
    # IDX-2: warn when the certificate expires within this many days (DECISIONS 321/322: 30 or fewer Medium, 14 or fewer High, 7 or fewer Blocker).
    tls_expiry_warning_days: float = 30.0
    # IDX-2: port for the HTTP -> HTTPS redirect check (None = 80). Tests use a local port.
    http_port: int | None = None
    # IDX-4: fetch at most this many canonical targets the crawl did not fetch.
    max_canonical_fetches: int = 20
    # IDX-4 / IDX-8: estimated similarity at or above which two pages count as the same content.
    # Round-number estimate, not calibrated.
    same_content_similarity: float = 0.9
    location_template_min_pages: int = 5  # IDX-8 place pages under one section (DECISIONS 264)
    # IDX-4 / ANS-1: share of words identical and in the same order at or above which two pages count as the same
    # content. Set from one measured site (Midas, 2026-09-22): the same article at /x and /x/ shared 0.901, two
    # different articles on the same template 0.419. One site is not a calibration (LG-21).
    same_content_block_share: float = 0.8
    # IDX-5 thresholds (policy, from the spec).
    sitemap_bad_share: float = 0.10
    sitemap_required_above_pages: int = 50
    # IDX-5 (DECISIONS 206, LG-78): the sitemap URLs the crawl did not read are each asked once with a light request
    # (at most 64 KB read, no redirect followed), at most this many. The command line sets 100 for up to 499 pages
    # (Quick), 300 from 500 (Standard) and 0 for a single page (DECISIONS 294; were 200 and 1,000). Above the cap a
    # sample spread evenly over the sitemap files is asked, the same every run, 4 at a time through the site limit.
    sitemap_check_max: int = 100
    # Fast check (DECISIONS 219, --fast, the web app's "Fast check" switch): fewer optional requests, the FAST_* caps.
    # Pages read, robots.txt samples, ACC-4, redirect re-checks, the page reader and paid data are unchanged.
    fast_check: bool = False
    # ACC-8 (DECISIONS 208, LG-80): links in llms.txt to this site that neither the crawl nor the sitemap check read
    # are asked with the same light request, at most this many.
    llms_link_checks_max: int = 50
    # IDX-7: click depth at which a page is "deep" (spec): 5 means more than 4 clicks from the homepage.
    deep_page_depth: int = 5
    # How many links to this site, and to other sites, are kept per page, and how many distinct anchor texts per
    # target. Links beyond the cap are still followed by the crawl; the cap bounds what the report stores.
    max_outlinks_per_page: int = 1000
    max_external_links_per_page: int = 300
    max_anchor_texts_per_target: int = 20
    # Link discovery through the browser, for sites that build their links with JavaScript: the homepage and
    # the key pages are rendered during the crawl, and when the rendered page has clearly more links to this
    # site than its raw HTML, the extra ones are followed too. Needs render_enabled.
    render_discovery: bool = True
    render_discovery_budget: int = 6
    # IDX-9 (T2): Google Search Console URL Inspection. The OAuth token is supplied by the operator.
    gsc_access_token: str | None = None
    gsc_site_url: str | None = None
    gsc_endpoint: str = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
    gsc_max_inspections: int = 20
    # IDX-10 (T2): Bing Webmaster Tools API. Endpoint path not verified (see README).
    bing_api_key: str | None = None
    bing_site_url: str | None = None
    bing_endpoint: str = "https://ssl.bing.com/webmaster/api.svc/json"
    # Launch gate: stays False until the JSON endpoint and response shape are confirmed against Microsoft's
    # documentation. While False, IDX-10 never calls a non-loopback Bing endpoint. Deliberately not a CLI flag.
    bing_api_verified: bool = False
    # IDX-10: IndexNow key, and its location if not /{key}.txt.
    indexnow_key: str | None = None
    indexnow_key_location: str | None = None
    # IDX-3: a URL that redirected in a loop during the crawl, and always the homepage, is requested again this many
    # times before anything is said about it; a chain is followed for at most this many hops (DECISIONS 195).
    redirect_recheck_attempts: int = 3
    redirect_recheck_max_hops: int = 10
    # IDX-6: other domains of the same brand (a sister shop, the group's site), as plain host names. A link to one of
    # them, or to a subdomain of one, is never reported as "a link to another site" and is never requested.
    brand_family_domains: tuple[str, ...] = ()
    # IDX-6: a link to another site at one of this site's own paths is requested once, to see whether it leads to a
    # page. At most this many distinct addresses; the other site's robots.txt is fetched and obeyed first (DECISIONS 196).
    idx6_other_site_checks_max: int = 10

    # --- RND checks ---------------------------------------------------------
    # T1 rendering (headless Chromium via Playwright; optional dependency).
    render_enabled: bool = True
    render_budget: int = 20  # spec §8 F8
    render_key_page_slots: int = 10
    render_template_slots: int = 6
    render_timeout_s: float = 15.0
    render_settle_ms: int = 3000
    render_browser_channel: str | None = None  # None = Playwright's Chromium; "chrome" = installed Chrome
    # Resources on other origins are not loaded while rendering unless this is on (see README).
    render_third_party: bool = False
    render_interactions: bool = True
    render_max_clicks: int = 10
    # RND-3: how long the page is left alone, with no click, before interacting (the control snapshot), and again
    # after the clicks. Content that appears by itself in this window is late loading, not revealed by a click.
    render_control_wait_ms: int = 1000
    # RND-1 thresholds (spec; policy).
    raw_missing_ratio: float = 0.5
    raw_partial_ratio: float = 0.8
    raw_min_words: int = 50
    rendered_min_words: int = 200
    # RND-2: owner-declared critical facts, as (page URL or path, exact text).
    critical_facts: tuple[tuple[str, str], ...] = ()
    # RND-3: content counts as revealed by interaction at this many new words, or this much growth.
    interaction_min_new_words: int = 30
    interaction_min_growth: float = 0.2
    # RND-5: a page this short that matches a wall signature is treated as a wall (Estimated).
    wall_max_words: int = 200
    # RND-6 thresholds (spec; policy; vendor limits undocumented).
    payload_max_bytes: int = 1_000_000
    homepage_payload_max_bytes: int = 500_000  # homepage only, Medium (DECISIONS 258)
    main_offset_max_bytes: int = 500_000
    # RND-7: flag when main content is less than this share of visible text (policy, uncalibrated).
    main_content_min_share: float = 0.3

    # --- STR checks ---------------------------------------------------------
    # Status checks for URLs that pages point to (og:image, sameAs, hreflang targets) that the crawl did not fetch.
    # Same-origin URLs obey this site's robots.txt; at most this many extra requests.
    str_link_checks_max: int = 50
    # STR-7: how many image files are requested to see whether they load (a sample spread over the pages).
    image_checks_max: int = 30
    # STR-7 (P1): every content image and preload of the homepage and the key pages is sized on top of the sample
    # above, at most this many; none when image_checks_max is 0. A banner with no declared size, or a lazy one further
    # down the homepage, is then measured however the sample falls (live: three 1.1-1.8 MB banners were missed).
    key_image_checks_max: int = 40
    # URLs on OTHER sites (a profile, a CDN, a page a link points to) are asked whether they still exist (DECISIONS 211;
    # before: off, DECISIONS 35). On by default, off with --no-external-links and in the web app's demo mode. Each
    # other site's robots.txt is fetched and obeyed first and counts toward the cap; a link is asked with one HEAD
    # (a 405 or 501 is asked again once as a GET of at most 4 KB). At most min(external_link_checks_max,
    # external_link_checks_base + pages read) requests (`external_link_cap`), external_link_checks_base in a
    # single-page audit, and at most external_sites_max other sites. sameAs profile links are asked even when this is
    # off, at most same_as_checks_max (as DECISIONS 196 does for a link to another site at one of this site's paths).
    check_external_links: bool = True
    external_link_checks_max: int = 100
    external_link_checks_base: int = 20
    external_sites_max: int = 25
    same_as_checks_max: int = 10
    # STR-2 (spec): "long page" word count for the no-subheadings rule.
    long_page_words: int = 800
    homepage_min_subheadings: int = 3  # homepage outline, High (DECISIONS 258)
    homepage_outline_min_words: int = 300
    # The second look at the most serious findings before the report is written (maya_audit.verification, DECISIONS 272).
    verification_enabled: bool = True
    verification_max_requests: int = 12
    verification_urls_per_finding: int = 2
    verification_time_s: float = 60.0
    # STR-6 (spec): date signals further apart than this conflict.
    date_conflict_days: int = 30
    # STR-6 auto-stamping: at least this many pages carry the signal and this share of them is dated the audit day.
    # Both are uncalibrated guesses.
    autostamp_min_pages: int = 5
    autostamp_share: float = 0.9

    # --- PRF checks ---------------------------------------------------------
    # PRF-1/PRF-2: extra fetches of a sample of URLs after the crawl (the crawl fetch is attempt 1).
    prf_enabled: bool = True
    prf_extra_rounds: int = 2  # spec: >= 3 attempts per sampled URL
    prf_round_gap_s: float = 30.0
    prf_key_page_slots: int = 10
    prf_template_slots: int = 6
    prf_max_urls: int = 30
    # PRF-1 (spec, policy): median total HTML time above this is slow. Needs this many successful samples.
    prf_slow_median_s: float = 1.5
    homepage_ttfb_max_ms: int = 800  # web.dev "good" TTFB; homepage only, High (DECISIONS 258)
    prf_min_samples: int = 3
    # PRF-2 (spec, policy): sitewide failure share above this. Only computed from at least this many attempts
    # (the minimum is an uncalibrated guess, not from the spec).
    prf_sitewide_failure_share: float = 0.05
    prf_sitewide_min_attempts: int = 20
    # Where Maya's requests leave from, as written by the operator (e.g. "eu-central-1"). Not looked up.
    egress_region: str | None = None
    # PRF-3 (T2, optional): PageSpeed Insights lab runs and CrUX field data. Key from the environment only.
    pagespeed_enabled: bool = False
    google_api_key: str | None = None
    psi_endpoint: str = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"
    crux_endpoint: str = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
    psi_runs: int = 3
    psi_max_urls: int = 5

    # --- ANS panel ----------------------------------------------------------
    # Citation records (T4, produced upstream) as a JSON file; see maya_audit/ans_data.py for the shape.
    citations_file: str | None = None
    # Ranked cited-domain export (T4) as a JSON file; see maya_audit/ans_domains.py for the shape.
    citation_domains_file: str | None = None
    # Cited URLs the crawl did not fetch are fetched once each, up to this many.
    ans_max_fetches: int = 50

    def snapshot(self) -> dict:
        """Config as recorded in reports, with secrets redacted."""
        from dataclasses import asdict

        out = {}
        for key, value in asdict(self).items():
            if key in SECRET_FIELDS:
                value = "redacted" if value else None
            elif isinstance(value, frozenset):
                value = sorted(value)
            out[key] = value
        return out

    @property
    def user_agent(self) -> str:
        if self.bot_info_url:
            return f"{self.product_token}/{PRODUCT_VERSION} (+{self.bot_info_url})"
        return f"{self.product_token}/{PRODUCT_VERSION}"


# IDX-1 / IDX-6 (review H09): Cloudflare serves its own machinery under this first path segment
# (/cdn-cgi/l/email-protection, /cdn-cgi/challenge-platform/). A link there is not a page of the site, so a 404 there is
# not a broken page. Only this segment: a dead link under /api/ or /admin/ is still a dead link.
CLOUDFLARE_PATH_SEGMENT = "cdn-cgi"
# Where Cloudflare's e-mail obfuscation points an address it hid, and the text it puts in its place.
CLOUDFLARE_EMAIL_PATH = "/cdn-cgi/l/email-protection"
# IDX-5 (review H13): words of a path segment that name a draft or test page, folded (no case, no Turkish letter marks)
# and matched as whole words of the segment ("/test-marka", not "/latest"). An agent default from one audited shop.
DRAFT_PATH_WORDS = frozenset({"test", "deneme", "draft", "taslak", "ornek", "sample", "demo"})
# IDX-8 (review H20): file extensions a server may answer with and without (/UyeGiris and /UyeGiris.aspx).
PAGE_EXTENSIONS = (".aspx", ".asp", ".php", ".html", ".htm", ".jsp")

# -- review fixes, page content and structure (W2, 2026-10-21) ------------------------------------------------------

# STR-7 (H16): alt values that name no image, compared whole after folding (Turkish lower case, no diacritics, spaces
# for punctuation). A theme's default ("image title"), a field label ("alt text"), a bare noun in English or Turkish.
PLACEHOLDER_ALTS = frozenset({
    "image", "images", "photo", "picture", "img", "pic", "image title", "image alt", "alt", "alt text", "alt tag",
    "image description", "untitled", "placeholder", "banner", "default", "thumbnail", "gorsel", "gorsel adi", "resim",
    "fotograf", "foto", "afis", "baslik", "image title here", "your image", "insert image",
})
# An alt that is a file name ("IMG-2034.png", "DSC_1.jpg") or a camera's numbering ("IMG_2034", "DSC 1").
PLACEHOLDER_ALT_FILE = r"^[\w ()+.-]*\.(?:jpe?g|png|gif|webp|avif|svg|bmp|tiff?|heic)$|^(?:img|dsc|dscn|dscf|pxl|photo|image|screenshot)[ _-]?\d+$"

# -- generalisation (gx3, 2026-10-22) -------------------------------------------------------------------------------

# PRF-1 (G05): "the HTML is not cached at the CDN" only when the CDN's own status says it did not serve a cached copy on
# at least this share of the HTML pages that carry its status (one page served from the edge is not the rule).
CDN_NOT_CACHED_SHARE = 0.9
# Report noise policy (G25, review G section 2): Info findings that carry a fix but are site-wide hygiene, seen on most
# healthy sites. Every output lists them after the Notes as one short "Hygiene" list, capped (the rest by ID / in JSON).
# (check id, words in the title, folded to lower case): loose on purpose, so a reworded title still matches. "The same
# analytics tag twice" is not here: once G10 narrows it, what remains is real double counting.
HYGIENE_FINDINGS = (
    ("PRF-1", "strict-transport-security"),
    ("PRF-1", "not cached at the cdn"),
    ("STR-7", "width and height"),
    ("STR-10", "twitter"),
    ("TSEO-1", "<head>"),
)
# How many hygiene lines a report shows before "N more" (the rest stay in the JSON report, by finding ID).
HYGIENE_LINES = 4

# -- generalisation: any language, platform and CDN (review G, worker gx2, 2026-10-22) -----------------------------
# Word lists below are compared folded (page_words.fold: lower case, no letter marks) and kept short on purpose: a
# structural signal (schema.org, HTTP, the URL's shape) is read first wherever one exists.

# STR-7 (G09): the placeholder nouns of PLACEHOLDER_ALTS in German, Spanish, Italian, Portuguese and Arabic ("image" is
# already the French one). Matched only as the WHOLE alt: "Foto" is a placeholder, "Foto der Praxis" is not.
PLACEHOLDER_ALTS_MORE = frozenset({"bild", "bildtitel", "imagen", "titulo de la imagen", "immagine", "imagem", "صورة"})
# STR-3 (G20): a VideoObject name that names nothing, in the same languages (compared folded).
PLACEHOLDER_VIDEO_NAMES_MORE = frozenset({"vidéo", "vídeo", "sans titre", "sin titulo", "ohne titel", "فيديو"})
# STR-7 (G08): heavy media. An image over the first size is heavy (S4); over the second it is S3, but only when it is
# shown on the homepage or a key page (elsewhere it stays S4: a recipe's or a campaign's large photo is not the
# site's first impression). A video over the third size is S4.
IMAGE_HEAVY_BYTES = 500_000
IMAGE_VERY_HEAVY_BYTES = 1_000_000
VIDEO_HEAVY_BYTES = 5_000_000
# STR-7 (G07): the Accept header the image sample sends, as a browser does, so an image service that picks the format
# from it answers what a reader would get.
IMAGE_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
# STR-7 (G07): image addresses an image service answers in the format the browser asks for (the name's extension is
# then not a promise): Shopify's CDN and its /cdn/shop/ path, Cloudinary f_auto, imgix auto=format, Next.js
# /_next/image, Cloudflare Images /cdn-cgi/image/, and a format=auto / fm=webp parameter. A Vary: Accept answer says
# the same for any host.
FORMAT_NEGOTIATING_IMAGE = (r"//cdn\.shopify\.com/|/cdn/shop/|/f_auto[,/]|[,/]f_auto\b|[?&]auto=[^&#]*format"
                            r"|/_next/image\b|/cdn-cgi/image/|[?&](?:fm|format)=(?:auto|webp|avif)\b")
# STR-7 sample (live gap 1): before images are taken page by page, this many from the top of the homepage (the hero
# and the banners above the fold) and the largest-declared ones of the homepage and the key pages, at most this share
# of the sample.
IMAGE_SAMPLE_HERO = 3
IMAGE_SAMPLE_PRIORITY_SHARE = 0.5
# STR-7 sample (live gap 4): a host on another domain that serves at least this share of the site's content images,
# and at least this many of them, is the site's own asset host (static.<platform>.cloud, a shop's image CDN): its
# images are sampled like the site's own, also with --no-external-links, under the same cap.
ASSET_HOST_SHARE = 0.5
ASSET_HOST_MIN_IMAGES = 5
# TSEO-1 (G11): scripts their vendors document as loaded synchronously in <head> (consent managers must run before any
# tag; A/B tools hide the page until they have run). Never told to add defer or async. Matched as the host or a
# subdomain of it.
SYNC_REQUIRED_SCRIPT_HOSTS = ("cookielaw.org", "onetrust.com", "cookiebot.com", "cookiebot.eu", "usercentrics.eu",
                              "privacy-center.org", "didomi.io", "iubenda.com", "optimizely.com",
                              "visualwebsiteoptimizer.com")
# TSEO-1 (G11): render-blocking scripts in <head> are on most healthy sites (a theme's jQuery). They are a finding only
# when a page blocks on at least this many of the site's own scripts; fewer are an observation.
BLOCKING_SCRIPTS_FINDING_MIN = 3
# STR-7 (G12): a class that sizes an image by CSS (aspect-ratio and object-fit utilities, responsive-embed wrappers).
CSS_SIZED_IMAGE_CLASS = r"aspect|ratio|object-(?:fit|cover|contain)|embed-responsive|img-fluid"
# STR-6 (G22): month names in German, French and Spanish (January first), and the words before a date that label it.
MONTH_NAMES_MORE = (
    ("januar", "janvier", "enero"), ("februar", "février", "febrero"), ("märz", "mars", "marzo"),
    ("april", "avril", "abril"), ("mai", "mayo"), ("juni", "juin", "junio"), ("juli", "juillet", "julio"),
    ("august", "août", "agosto"), ("september", "septembre", "septiembre"), ("oktober", "octobre", "octubre"),
    ("november", "novembre", "noviembre"), ("dezember", "décembre", "diciembre"),
)
DATE_LABELS_MORE = r"veröffentlicht|aktualisiert|publié|mis à jour|publicado|actualizado"

# -- generalisation, index and access (gx1, review G, 2026-10-22) ---------------------------------------------------

# IDX-5 (G02): draft words in other languages beside DRAFT_PATH_WORDS (tr/en), folded the same way (no case, no
# accents). A word only counts as the address's name (`index_data._draft_word`), and only on an untitled or
# placeholder-titled page found only through the sitemap.
DRAFT_PATH_WORDS_OTHER = frozenset({"entwurf", "brouillon", "borrador", "prueba", "bozza", "مسودة", "تجربة"})
# IDX-5: draft words that also end real names ("/request-demo", "/dilekce-ornek"): a draft only first in a slug.
DRAFT_WORDS_ALSO_CONTENT = frozenset({"demo", "ornek", "sample", "prueba"})
# IDX-5 (G02): titles a CMS writes for a page nobody named, folded (no case, no accents). Matched whole, or as one part
# of a title the site name was added to ("Başlıksız – Mavi Atölye").
DRAFT_PLACEHOLDER_TITLES = frozenset({
    "basliksiz", "untitled", "untitled page", "new page", "yeni sayfa", "sans titre", "nouvelle page", "sin titulo",
    "nueva pagina", "ohne titel", "neue seite", "senza titolo", "بدون عنوان", "صفحة جديدة",
})
# IDX-1 / IDX-6 (G06 link side, G27): first path segments where a CDN or edge platform serves its own machinery (bot
# sensors, analytics beacons, challenge pages, e-mail protection), folded to lower case, with the vendor named in the
# evidence. A link there is not a page of the site, so a 404 there is not a broken page. Generalises
# CLOUDFLARE_PATH_SEGMENT; only these exact segments: a dead link under /api/ or /admin/ is still a dead link.
EDGE_MACHINERY_SEGMENTS = {"cdn-cgi": "Cloudflare", "akam": "Akamai", "_vercel": "Vercel", ".netlify": "Netlify",
                           "_incapsula_resource": "Imperva"}
# IDX-1 (first review C1/C2, live Adile run: 57 URLs empty to Maya's own user agent, read fine by a browser-like
# reader): before two empty answers to Maya's own client are called a site fault, at most this many of those URLs are
# asked once more with a browser user agent (purpose `empty_browser_check`, tagged like ACC-4's requests).
EMPTY_BROWSER_CHECK_URLS = 3
# Crawl order (live gap 3): at most this many hreflang alternates and canonical targets per page (homepage and key pages
# only) are queued at scratchpad.PRIORITY["alternate"]; the rest still come in through links or the sitemap.
ALTERNATE_PRIORITY_MAX_PER_PAGE = 10
