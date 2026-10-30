# False alarms

Every confirmed false alarm: a time a report said something about a site that was not true of the site, with the
test that now guards against it. One entry per alarm, headed `## FA-nnn`, newest last. An entry is added when the
cause has been found in the saved page copies or the saved report, not when a result merely looks odd.

Each entry has the same fields: **Date** (when it was seen), **Site** (and what kind of site it is), **Report said**,
**Page really had**, **Cause**, **Rule now** (with the decision that records it) and **Test** (the test that fails
if the alarm comes back).

## FA-001

- **Date:** 2026-10-11
- **Site:** ticimax.com (an e-commerce platform's own site)
- **Report said:** "No indexable HTML pages" on 20 checks (19 STR checks and TSEO-1); all 50 pages read were
  treated as noindex. The homepage's title was read as "…MarkaTeam Blue Widget".
- **Page really had:** its own head with `<meta name="robots" content="INDEX,FOLLOW">`. At the end of the body, a
  support widget's iframe, whose document the page reader had written into the page copy:
  `<div src="https://cdn.hub-prod.team.blue/widget/index.html?..." data-original-tag="iframe"><!DOCTYPE html><html
  lang="en"><head>… <meta name="robots" content="noindex, nofollow"> <title>Team Blue Widget</title>`.
  Read without the widget's document, 49 of the 50 pages are indexable (only /login is really noindex).
- **Cause:** every `<meta name>` and every `<title>` in the HTML was read as the page's, wherever it stood,
  including those of a document embedded in the page.
- **Rule now:** an embedded document is treated like the iframe it came from: any element carrying
  `data-original-tag="iframe"`, and any second `<!DOCTYPE>` or `<html>` after the body began, is taken out before
  the page is read (`maya_audit/own_document.py`; DECISIONS 167, rule A1(a)). It is recorded in
  `analysis.embedded_documents`.
- **Test:** `test_an_inlined_iframe_documents_noindex_is_not_the_pages` (`tests/test_own_document.py`)

## FA-002

- **Date:** 2026-10-11
- **Site:** carpexonline.com (a shop)
- **Report said:** page titles such as "… | Carpex inveon.ai", and 20 page titles above the 60-character band.
- **Page really had:** its own `<title>` in the head, and in the body a chat widget's
  `<title>inveon.ai</title><meta name="description" content="inveon.ai">`. With only the page's own title read, 5
  titles are over 60 characters.
- **Cause:** the text of every `<title>` in the HTML was joined into one title, and a `<meta name>` in the body was
  read like one in the head.
- **Rule now:** the title (the first one only), `<meta name>`, `<meta property>`, the canonical link and hreflang
  links are the page's only before its body starts; later ones are counted in `analysis.outside_head` and not read
  as the page's (DECISIONS 167, rule A1(b)). On the saved copies of this site the widget's tags sat inside an
  element marked `data-original-tag="iframe"`, so rule A1(a) removes them as well.
- **Test:** `test_a_title_in_the_body_is_not_the_pages_title` (`tests/test_own_document.py`)

## FA-003

- **Date:** 2026-10-11
- **Site:** ticimax.com (an e-commerce platform's own site)
- **Report said:** RND-5, Blocker: "1 page(s) redirect a cookie-less visitor to a login, consent, age, or country
  page".
- **Page really had:** `/musteri-hesabi` (the customer's account page) answering 302 to
  `/login?ReturnUrl=%2Fmusteri-hesabi`. That is what an account page should do for a visitor who is not signed in.
  (The same response goes from https:// to http://, which is real and is still reported by IDX-3.)
- **Cause:** any redirect to a login address, from any page that was not itself a login page, was a wall.
- **Rule now:** a redirect to a login page from an account, cart, checkout or sign-in page (`config.ACCOUNT_PATHS`,
  matched on path segments without case, Turkish letter marks or a file extension) is one Info note, "{n} account,
  cart or checkout page(s) send a signed-out visitor to the login page (expected)". A content page that redirects
  to the login page, and every consent, age or country wall, is reported as before (DECISIONS 173).
- **Test:** `test_an_account_page_redirecting_to_login_is_a_note` (`tests/test_false_alarms.py`)

## FA-004

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site; the page is a glossary of crypto terms)
- **Report said:** STR-12: "section headings in another language than they declare (declared Turkish, headings in
  English)" on `/kripto-sozluk/`.
- **Page really had:** Turkish questions around an English term: "Proof of Work (PoW) Nedir?". The only English
  evidence in such a heading was the word "of", and the Turkish question word was in no list.
- **Cause:** one stopword of a language was enough to call a heading, wherever it stood, and "nedir" was not known as
  Turkish.
- **Rule now:** in a heading these are not evidence of a language: words in parentheses, a stopword between two
  capitalised words (a term or a name), and a stopword that is an ordinary word in the page's declared language.
  Turkish question words (nedir, nasıl, neden, hangi, …) are Turkish evidence. One stopword is otherwise still
  enough, and three headings are still needed (DECISIONS 174; a heuristic, LG-62).
- **Test:** `test_a_turkish_glossary_heading_with_an_english_term_is_not_english` (`tests/test_false_alarms.py`)

## FA-005

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site)
- **Report said:** a heading of `/destek/` was counted as French.
- **Page really had:** "Bizi Takip Et" ("follow us"). "Et" is Turkish for "do"; it is also French for "and".
- **Cause:** the stopword lists of the eight languages overlap, and the page's own language was not asked.
- **Rule now:** a stopword of another language that is an ordinary word in the declared language is not evidence
  (`language.NOT_FOREIGN_IN`: for Turkish et, de, da, o, en, on, an, son, al, in, ne, se, su) (DECISIONS 174).
- **Test:** `test_et_in_a_turkish_heading_is_not_french` (`tests/test_false_alarms.py`)

## FA-006

- **Date:** 2026-10-11
- **Site:** magazanolsun.com (a services site: e-commerce packages, an academy, events)
- **Report said:** STR-4, High: "3 page(s): structured-data price differs from the price shown on the page", with
  "29 USD" as the price shown.
- **Page really had:** markup prices of 0 TRY ("Free") for a course and 0, 60000 and 250 TRY for events, and no price
  of their own in the text. "29 USD" is a competitor's monthly price in a blog teaser card ("… aylık 29 USD'den
  başlayan …") that a carousel repeats on 22 of 53 pages. The word "ücretsiz" is on the page.
- **Cause:** every price anywhere in the page's text was a candidate for the page's own price. The teaser was under
  the 60% bar for "site furniture", and a price of 0 was never matched with the word for free.
- **Rule now:** a price is the page's own only in its main content, outside link text, outside a block that at least
  25% of the pages (and at least 5) repeat, and in the markup's currency when it carries a currency mark. A markup
  price of 0 matches "ücretsiz", "bedava", "free" or "ücret alınmaz". With no price of the page's own, a person
  looks: a review item whose rows hold the markup price with its currency, what the page shows and why it could not
  be relied on (DECISIONS 175; the 25% bar is not calibrated, LG-63).
- **Test:** `test_a_teaser_price_is_not_the_pages_price` (`tests/test_false_alarms.py`)

## FA-007

- **Date:** 2026-10-11
- **Site:** magazanolsun.com (a services site)
- **Report said:** STR-4, High: "structured-data price differs" on the homepage.
- **Page really had:** three packages in the markup at 50000, 95000 and 190000 TRY. The headline says "50.000 TL'den
  Başlayan Fiyatlar", which is the first. The other amounts on the page are customers' earnings in testimonials
  ("Aylık Kazanç 189,039 TL").
- **Cause:** when no shown price equalled a markup price, any other price on the page was taken for that offer's,
  and with several prices on the page the conflict was called "Inferred" and still reported as High.
- **Rule now:** a difference is High only when exactly one price of the page's own is left after the prices that
  other offers match are set aside, and it can be paired with one offer. Several prices left, or one price and
  several offers left beside an offer that matched, is a review item (DECISIONS 175).
- **Test:** `test_sibling_offers_beside_a_matched_price_are_review_items` (`tests/test_false_alarms.py`)

## FA-008

- **Date:** 2026-10-11
- **Site:** magazanolsun.com (a services site)
- **Report said:** STR-4, Medium: "structured-data product name differs from the product name shown on the page".
- **Page really had:** "Mağazanolsun - PREMIUM PLUS" in the markup and "PREMIUM PLUS" on the package pages: the same
  name with the site's own in front. On the homepage the package names are not written at all.
- **Cause:** the whole markup name, brand prefix included, was looked for in the text; a name that was not found was
  compared with the title and the H1, and little overlap was called a different name.
- **Rule now:** the site's own name (og:site_name, the site's Organization and WebSite names, its host name) is
  dropped from a product name's separator segments before it is compared. A name that is not on the page is "not
  shown" (a review item). A different name needs a page about one product whose H1 names something else
  (DECISIONS 175).
- **Test:** `test_a_brand_prefix_or_an_absent_name_is_not_a_different_name` (`tests/test_false_alarms.py`)

## FA-009

- **Date:** 2026-10-11
- **Site:** carpexonline.com (a shop)
- **Report said:** STR-5: "The brand is named 13 different ways", with no list of the thirteen.
- **Page really had:** `<meta property="og:site_name" content="KVKK | Caprexonline">` and six more like it on seven
  static pages: the page's title pasted into og:site_name. Those were seven of the thirteen. One more was the widget
  title of FA-002. The rest are real spellings of the shop's own name. No product or manufacturer brand was among
  them: STR-5 does not read `Product.brand`.
- **Cause:** every og:site_name value was a name of the brand; and no output printed the names.
- **Rule now:** an og:site_name that equals the page's own title (and is not the value most pages give), or that has
  a title separator in it, is not a name: such pages are one Low finding, "og:site_name holds the page title on {n}
  page(s)", with the pages and values. Every name is listed with what gave it and on how many pages, in the
  finding's own section and in the "Whole site" row (DECISIONS 176).
- **Test:** `test_og_site_name_holding_the_title_is_one_line_not_n_names` (`tests/test_false_alarms.py`)

## FA-010

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site)
- **Report said:** STR-19: links with no address a crawler can follow, on 47 pages.
- **Page really had:** the footer's cookie-settings opener:
  `<a href="…#" class="js-open-cookie-settings">Çerez Ayarları</a>`. It opens a panel; there is no page behind it.
- **Cause:** a control was known by a list of attributes and a list of labels; this label was not listed and a class
  was never read.
- **Rule now:** a link with no address is a control (the accessibility note, never a problem) when its label is a
  cookie-settings or show/hide label, or its class says so: a token containing "toggle", a token starting js-open-,
  js-close-, js-toggle-, js-show- or js-hide-, or `ot-sdk-show-settings`. "cookie" anywhere in a class, any js-
  class and btn/button were rejected as over-matching (DECISIONS 177).
- **Test:** `test_a_cookie_settings_link_is_a_control` (`tests/test_false_alarms.py`)

## FA-011

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site)
- **Report said:** the same STR-19 finding, for a link in an article's table of contents.
- **Page really had:** `<a href="…#" class="lwptoc_toggle_label" data-label="göster">gizle</a>`: the "hide / show"
  switch of the table of contents.
- **Cause:** as FA-010.
- **Rule now:** as FA-010: "gizle", "göster", "show", "hide" and their longer forms are control labels, and a class
  token containing "toggle" marks a control (DECISIONS 177).
- **Test:** `test_a_show_hide_toggle_is_a_control` (`tests/test_false_alarms.py`)

## FA-012

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site)
- **Report said:** STR-7: "218 likely meaningful image(s) on 11 page(s) have missing or empty alt text".
- **Page really had:** about 190 country flags in one table of an economic calendar, each beside its country code:
  `<td class="country"><img src="…/country/AU.svg" width="300" height="150"> AU </td>`. Most of the rest were
  illustrations with a deliberate `alt=""` above their captions.
- **Cause:** an image was "meaningful" when its declared width or height was 150 or more, and 300×150 is the size a
  browser gives an image that has none (in the saved copies of four sites every image of exactly that size was an
  SVG); and a deliberate empty alt was counted like a missing one.
- **Rule now:** an image whose parent holds 1 to 60 characters of its own text and at most two images is "beside a
  label": with `alt=""` it is decorative, with no alt it goes to the Info list. The same kind of image five or more
  times on a page is one row with a count. A deliberate `alt=""` is doubted only in a `<figure>` or for a telling
  file name, never for size. Exactly 300×150 is not size evidence. The title says "no alt text" and "empty alt"
  apart (DECISIONS 178; LG-64).
- **Test:** `test_a_flag_beside_its_code_is_decorative_and_counted_once` (`tests/test_false_alarms.py`)

## FA-013

- **Date:** 2026-10-11
- **Site:** getmidas.com (a finance app's site)
- **Report said:** STR-8: "1 page(s) lay out pricing or spec comparisons as <div> grids instead of <table>" for
  `/ucretler/`.
- **Page really had:** eight real `<table>` elements with `<th scope="col">` header cells, and inside an accordion a
  `<div>` list of the same fees whose rows are `data-toggle="collapse"` switches for one of those tables.
- **Cause:** a `<div>` grid was reported without looking at the page's real tables or at whether the grid folds away.
- **Rule now:** a grid is not reported when it or an element around it is a collapse or an accordion (by class, by
  `data-toggle` / `data-bs-toggle="collapse"`, or by `aria-expanded`), or when half or more of its row labels are
  the row labels of a real table with header cells on the same page. What was left out is counted in
  `evidence.grids_left_out` (DECISIONS 178).
- **Test:** `test_a_collapsed_copy_of_a_real_table_is_not_reported` (`tests/test_false_alarms.py`)

## FA-014

- **Date:** 2026-10-12
- **Site:** adilehanim.com (a confectionery maker's catalogue site)
- **Report said:** STR-7: "52 likely meaningful image(s) on 2 page(s): 0 with no alt text, 52 with an empty alt".
- **Page really had:** an embedded Google Map on the two contact pages: 24 tiles (`maps.googleapis.com/maps/vt?…`), a
  pin and a transparent overlay (`maps.gstatic.com/mapfiles/…`), each with `alt=""`.
- **Cause:** the file-name hint was searched in the whole address, so "map" in the host and the folder counted.
- **Rule now:** the hint is read from the file name only, as whole words; images from map hosts are decorative
  (DECISIONS 186).
- **Test:** `test_map_tiles_are_not_meaningful_images` (`tests/test_false_alarms.py`)

## FA-015

- **Date:** 2026-10-13
- **Site:** a confectionery maker's catalogue site and a card programme's campaign site (both named in the external
  review of 2026-10-13, not here)
- **Report said:** STR-9: "`<html lang>` says Turkish, but the text reads as Portuguese", for an allergen page and for
  campaign pages.
- **Page really had:** Turkish text. The allergen page is a table with an "o" under each allergen a product holds
  (356 of them). The campaign pages name a marketplace with a suffix after an apostrophe ("…'da" 873 times, "…'de"
  506 times) and list 308 addresses ending in ".com".
- **Cause:** the language guess cut words at the apostrophe, so each suffix counted as the Portuguese, Italian or
  Dutch word "da" or "de"; it counted the "com" of every address as Portuguese; and it did not know the page's
  declared language, so "o" counted as Portuguese on a page declared Turkish.
- **Rule now:** addresses are taken out before words are counted; a word with an apostrophe counts by the part before
  it; a common word of another language that is an ordinary word in the declared language is not counted for that
  other language (DECISIONS 194; LG-16 stays open).
- **Test:** `test_a_turkish_allergen_table_and_a_campaign_list_are_not_portuguese` (`tests/test_false_alarms.py`)

## FA-016

- **Date:** 2026-10-13
- **Site:** a card programme's campaign site (named in the error report of 2026-10-13, not here)
- **Report said:** IDX-3: "2 redirect loops: the URL never resolves", Blocker, the report's first problem.
- **Page really had:** two addresses that redirect to themselves on about half of the requests and serve the page on
  the others; the homepage did the same, though its one crawl answer was 200.
- **Cause:** the redirect map was built from one response per URL. One self-redirect was enough for a Blocker, and the
  homepage, answered 200 once, was never asked again.
- **Rule now:** every looping URL (at most `max_refetches`) and always the homepage are walked 3 more times through
  the crawl's own fetcher (same pace, robots.txt, time limit), at most 10 hops each. All loop: the Blocker as
  before. One loads: Medium, Verified, "N URL(s) intermittently redirect to themselves; the page loads on another
  try". No re-check possible: Medium, Inferred, "redirected to themselves once; this could not be re-checked"
  (DECISIONS 195; LG-72).
- **Test:** `test_a_url_that_redirects_to_itself_on_every_second_request_is_intermittent_not_a_loop` (`tests/test_false_alarms.py`)

## FA-017

- **Date:** 2026-10-13
- **Site:** the same campaign site (named in the error report of 2026-10-13, not here)
- **Report said:** IDX-6: "5 links on 4 pages point to another site (...) at a path that exists on this one", with
  the fix "the link most likely leads nowhere".
- **Page really had:** deliberate links to the parent brand's sites; every one answered 200.
- **Cause:** only the path was compared; the other address was never requested, and nothing let a person name the
  brand's other domains.
- **Rule now:** each distinct other-site address is requested once (at most 10), after that site's robots.txt is read
  and obeyed, with the usual URL safety rules and pace, also when external link checks are off. A page or a redirect:
  no finding, a count in evidence. 404 or 410: Medium, Verified, naming the status. Anything else: a note, "the other
  address could not be checked". Links to a brand-family domain (`--brand-family-domain`, the plan card's field) are
  never requested and never reported. "Leads nowhere" is gone from IDX-6 (DECISIONS 196; LG-73).
- **Test:** `test_a_link_to_another_site_that_answers_with_a_page_is_not_reported` (`tests/test_false_alarms.py`)

## FA-018

- **Date:** 2026-10-13
- **Site:** a confectionery maker's catalogue site (named in the external review of 2026-10-13, not here)
- **Report said:** STR-21: "Basic pages present: Not found among the 45 pages read: About".
- **Page really had:** an About page at `/hikayemiz/` ("our story"), among the pages read and listed in the report's
  own page table.
- **Cause:** the words that mark an About page did not hold "hikayemiz", and footer links were not looked at.
- **Rule now:** "hikayemiz" and eight more Turkish names mark the About page in an address and in a footer link's
  text; before a kind is called missing the footer links are read, and a page that is linked there and was not read
  is said as "linked from the footer, not among the pages read", never as missing (DECISIONS 197).
- **Test:** `test_an_about_page_called_hikayemiz_is_found` (`tests/test_false_alarms.py`)

## FA-019

- **Date:** 2026-10-13
- **Site:** a confectionery maker's catalogue site (named in the external review of 2026-10-13, not here)
- **Report said:** STR-14: "Shared header/footer: link to /blog/…/ has no text (on 4 pages)", with "Affects the whole
  site".
- **Page really had:** a picture link inside the related-posts block (`<div class="post-related">`) under four blog
  articles. Not in the header, not in the footer, and on four pages of about forty-five.
- **Cause:** every shared-element title began with "Shared header/footer", also when the markup named no region; an
  element that most pages of one section carry (four of the blog's pages) was given the scope of the whole site.
- **Rule now:** "Shared header/footer" only for an element in a header, a navigation or a footer; otherwise the
  block's own name ("“div.post-related” block") or "Repeated block". An element shared only within one section is a
  finding about that section's pages and says "on N page(s) of /section/"; it is listed once, never on each page's
  row, and nothing calls it the whole site (DECISIONS 198; LG-61).
- **Test:** `test_a_related_posts_block_is_named_by_its_block_and_is_not_the_whole_site` (`tests/test_false_alarms.py`)

## FA-020

- **Date:** 2026-10-13
- **Site:** the same campaign site (named in the error report of 2026-10-13, not here)
- **Report said:** STR-18: "The homepage was not read as an indexable page with a title", while the report's own
  page table showed the homepage with a title.
- **Page really had:** a homepage with the brand in its title. The audit had been started on a deep address that
  answered 404; the homepage was read from the sitemap.
- **Cause:** with no depth-0 page that answered 2xx, `homepage_url` returned the address typed, so STR-18 looked for
  the homepage at the 404 address. (Two reads that disagree, a 301 and a 200, are possible too; not confirmed there.)
- **Rule now:** when the start address gave no readable page, the homepage is the site's root if it was read with
  2xx. When the homepage still has no readable record, STR-18 compares every read of it and says "Two reads of the
  homepage disagreed: one answered {a}, another {b}. The title was not judged." (DECISIONS 199).
- **Test:** `test_a_start_address_that_answers_404_does_not_hide_the_homepage_that_was_read` (`tests/test_false_alarms.py`)

## FA-021

- **Date:** 2026-10-13
- **Site:** a card programme's campaign site (named in the external review of 2026-10-13, not here)
- **Report said:** STR-8: "2 pages lay out pricing or spec comparisons as `<div>` grids instead of `<table>`", with
  nothing saying which block was meant.
- **Page really had:** real tables with `<th>` header cells (one of 11 rows), and above them an empty `<table>` that
  a script fills. The reviewer could not find the `<div>` block the finding was about.
- **Cause:** a real table excused a grid only when half of the grid's row labels were the table's; the finding's
  title and page line never showed the grid's container or its rows; an empty table was recorded and never reported.
- **Rule now:** a page that has a `<table>` with `<th>` and at least 2 rows is not flagged by either grid finding
  (its grids are counted in `evidence.grids_left_out`); a grid that is reported says where it is and what its first
  row holds; an empty `<table>` is its own Low finding (DECISIONS 200; LG-23 stays open).
- **Test:** `test_a_page_with_a_real_table_is_not_told_to_use_one_and_its_empty_table_is_reported` (`tests/test_false_alarms.py`)

## FA-022

- **Date:** 2026-10-13
- **Site:** a restaurant site whose address is its name written as one word (named in the error report of 2026-10-13, not here)
- **Report said:** in the DataForSEO panels, none of the site's own name searches was a brand search, and the cover was
  titled with the address. The plan card had suggested a brand, which nobody had confirmed.
- **Page really had:** the name in three words in og:site_name on every page; searches for those three words ranked first.
- **Cause:** the plan card guessed the brand from the address, splitting only at "-" and "_", and passed the guess on
  as the brand although it was not confirmed. A glued address gave one word that no search contains, so nothing was
  branded. The cover read the address, not the site.
- **Rule now:** the brand is the name typed or saved, else the site's own name (og:site_name that is not a page title,
  the Organization or WebSite name, the repeated part of the titles, given on at least 3 pages or half of them), else
  the address split into words only when every piece is a word of the site's titles and headings, else none. With
  none, the keyword panels keep their plain table and say "The brand name could not be confirmed, so these keywords are
  not sorted into brand searches and other searches." The plan passes a brand only when it was confirmed, so the
  Business Profile needs a typed name. For a brand of two or more words a search is a brand search when it holds two of
  its words or its first word (DECISIONS 201; LG-74).
- **Test:** `test_the_sites_own_name_is_the_brand_when_the_address_is_one_glued_word` (`tests/test_brand_and_launch_gate.py`)

## FA-023

- **Date:** 2026-10-14
- **Site:** sites whose server answered some addresses with status 200 and no content (item 1 of the error report; not named here)
- **Report said:** the same addresses were listed as pages with no title and no H1, as a fast page in the speed sample,
  and INT-1 said "All N fetched pages returned the server's own response".
- **Page really had:** nothing: a 200 answer of 0 bytes, or a few bytes of markup with no title and no text.
- **Cause:** a 200 answer was always a page. Nothing told an answer with no content apart from a real page, so it went to
  the content checks, to PRF-1's sample and into INT-1's "all pages".
- **Rule now:** a 2xx answer under 512 bytes with no title and no visible text is an empty page: the site's own answer
  (fetch class ok), but not read by the content checks, PRF-1 or the page reader. It is refetched once, and IDX-1 reports
  "N page(s) answer with an empty page (under 512 bytes)", S1 on the homepage, a key page or 10% of the pages, else S2;
  INT-1 says how many were empty (DECISIONS 204; LG-75).
- **Test:** `test_an_empty_page_is_reported_by_idx1_and_left_out_of_content_checks_speed_and_the_page_reader` (`tests/test_round2_empty_and_googlebot.py`)

## FA-024

- **Date:** 2026-10-14
- **Site:** server-rendered sites whose pages carry a long menu and footer (item 20 of the error report; not named here)
- **Report said:** under "JavaScript rendering": "N pages have less than 30% of their text in the main content", with
  the fix "Trim repeated navigation and footer text, or mark up the main content." Read there, it sent developers to
  look for a JavaScript problem.
- **Page really had:** all of its text in the HTML the server sent, before any script ran; the menu and footer were
  simply long next to the page's own content, which had no `<main>` element around it.
- **Cause:** the web result, the printed report and the scorecard filed every check under the area named by its id's
  prefix, and RND-7 (the main content's share of the page text) begins with RND although it measures page structure.
- **Rule now:** RND-7 keeps its id and is shown under "Page structure and markup" (`summary.AREA_OF`), in new reports
  and in saved ones when they are opened, so the scorecard counts it there. Its fix says: "Mark the page's own content
  with one <main> element, so the menu, footer and sidebars sit outside it. This is page structure: no JavaScript
  change is needed.", with the `<main>` example; a saved report's old fix still reads in both languages (DECISIONS
  207; LG-22 stays open).
- **Test:** `test_the_main_content_share_is_filed_under_page_structure_not_javascript` (`tests/test_round2_followups.py`)

## FA-025

- **Date:** 2026-10-15
- **Site:** a restaurant site of the owner's team-preview-15b test (item 2; not named here)
- **Report said:** "A request with Googlebot's user agent got 500 on 1 of 3 URL(s) where a browser got 200", with the
  fix "Allow Googlebot in your WAF …".
- **Page really had:** a branch page that answered the browser with 200 and 0 bytes, and Googlebot's user agent with
  500 and a PHP "Fatal error": the server was broken for both, not refusing Googlebot.
- **Cause:** the verdict checked only that the browser got a 2xx status, and the sample picked an empty page on purpose.
- **Rule now:** the browser's answer counts only when it is a real page (2xx, not empty, no server error text);
  otherwise the pair is not assessed with "the browser also got an empty or error page: a server fault (see IDX-1),
  not a difference made for Googlebot", and Googlebot's error text is still IDX-1's finding. The sample no longer
  picks an empty page (DECISIONS 216; LG-77).
- **Test:** `test_googlebot_500_where_the_browser_got_an_empty_page_is_not_a_firewall_finding` (`tests/test_preview16_false_alarms.py`)

## FA-026

- **Date:** 2026-10-15
- **Site:** a card site of the owner's team-preview-15b test (item 3; not named here)
- **Report said:** "1 redirect loop(s): the URL never resolves" (Blocker), for an address that loads in a browser.
- **Page really had:** a 301 back to the same address on each of four cookie-less requests; the headers were not
  saved, so the cookie cause was likely but not proven.
- **Cause:** the fetcher keeps no cookies, so an address that sets a cookie and redirects to itself until the cookie
  comes back loops for Maya as it does for every crawler, and the report could not tell that apart from a real loop.
- **Rule now:** when all three cookie-less re-checks loop, one more walk sends back only the cookies the site set
  during that walk (never stored or written). If it loads, the finding is S3: "N URL(s) loop for visitors without
  cookies (crawlers); with the cookie the site sets, the page loads", with a fix about answering without a cookie; if
  it still loops, the Blocker stays (DECISIONS 217; LG-84).
- **Test:** `test_a_loop_that_loads_with_the_sites_own_cookie_is_a_cookie_loop_not_a_blocker` (`tests/test_preview16_false_alarms.py`)

## FA-027

- **Date:** 2026-10-15
- **Site:** the restaurant site of FA-025 (item 6; not named here)
- **Report said:** the cover named the brand as the address glued into one word, "typed" and "confirmed", and the
  keyword panels sorted no search of the real name as a brand search.
- **Page really had:** the name written as four words in the Organization name (37 pages), og:site_name and the titles.
- **Cause:** the plan card filled its field with the address's suggestion and posted it back as typed; any posted or
  saved value counted as confirmed, and saving the card saved the suggestion into the profile. A one-word brand
  matched only that word in the keywords.
- **Rule now:** a posted or saved value equal to the suggestion (spaces, case and Turkish letters aside) is not
  confirmed and the report reads the site's own name; the card sends the brand only when it was edited; a typed glued
  name equal to the site's name takes the site's spelling; a search that is the start of the glued brand (8 letters
  and 2 words at least) is a brand search (DECISIONS 220; LG-87).
- **Test:** `test_the_address_suggestion_posted_or_saved_unchanged_is_not_a_confirmed_brand` (`tests/test_preview16_false_alarms.py`)

## FA-028

- **Date:** 2026-10-15
- **Site:** the restaurant site of FA-025 (item 7; not named here)
- **Report said:** "The brand is named 5 different ways", listing the footer's "2023-2025 …" name and two branch names.
- **Page really had:** one name, a copyright line with a year range, and Organization nodes for two branches on their
  own pages (the name followed by the district).
- **Cause:** a "Copyright ©" line let the years through as part of the name; branch Organization nodes were counted as
  names of the brand; and "İçerenköy" was normalised to "i çerenköy".
- **Rule now:** years are taken off a copyright name; the most-used name plus 1 to 4 words, given by a structured-data
  node off the homepage, is a branch, listed and not counted; a capital dotted İ is i (DECISIONS 221; LG-88).
- **Test:** `test_copyright_years_and_branch_names_are_not_other_names_of_the_brand` (`tests/test_preview16_false_alarms.py`)

## FA-029

- **Date:** 2026-10-15
- **Site:** the restaurant site of FA-025 (item 8; not named here)
- **Report said:** "[S1] noindex via meta on 1 page(s)" for its QR menu page.
- **Page really had:** a QR-menu page with noindex, listed in the sitemap and linked from no page that was read.
- **Cause:** any noindexed page in the sitemap was a Blocker, whatever the page was for.
- **Rule now:** a utility page (QR menu, print, thank-you, search and the private paths) that is not a key page and not
  linked from the navigation is S3, "noindex via … on N utility page(s) (such as a QR menu or a print page): check that
  this is intended"; linked from the menu it stays S1 (DECISIONS 222; LG-89).
- **Test:** `test_noindex_on_a_qr_menu_page_listed_in_the_sitemap_is_a_note_and_in_the_menu_a_blocker` (`tests/test_preview16_false_alarms.py`)

## FA-030

- **Date:** 2026-10-15
- **Site:** a bank site and the card site of FA-026 (item 10; not named here)
- **Report said:** a deposit calculator was a "<div> grid at section#content > section#… > div.…" to put in a table,
  and instalment calculator pages "contain an empty <table> element".
- **Page really had:** a calculator: rows of input fields and sliders, and an empty table its script fills with the
  result.
- **Cause:** the grid rule ignored form controls, and the page line named a grid by its full CSS path.
- **Rule now:** a grid or an empty table with a form control inside, a `<form>` around, or (for a table) a control in
  its nearest block is left out as "a calculator or form: its rows are input fields, not a table of facts"; a grid is
  named by the heading it sits under (DECISIONS 223; LG-90).
- **Test:** `test_a_calculators_grid_and_an_empty_table_in_a_form_are_left_out` (`tests/test_preview16_false_alarms.py`)

## FA-031

- **Date:** 2026-10-15
- **Site:** the bank site of FA-030 (item 11; not named here)
- **Report said:** "1 page(s) declare a <html lang> that does not match the content language" for a form page.
- **Page really had:** a page declared Turkish whose main text is a notice in Turkish and English (about 250 words),
  with the menu and footer around it.
- **Cause:** STR-9 guessed from the whole page's text, and a page that holds the declared language as well as another
  was called wrongly declared.
- **Rule now:** the guess reads the main text only and needs 150 of its words; when the declared language has at least
  8 common-word hits too, the page is mixed language and not assessed (DECISIONS 224; LG-91).
- **Test:** `test_a_bilingual_notice_is_mixed_language_and_a_short_page_is_not_judged` (`tests/test_preview16_false_alarms.py`)

## FA-032

- **Date:** 2026-10-15
- **Site:** a card site (the external review's round 3; not named here)
- **Report said:** "[S3] The homepage has no Organization structured data".
- **Page really had:** Organization markup of the type BankOrCreditUnion on the homepage.
- **Cause:** STR-3's list of Organization types had 24 names and no bank, insurer, food, health or hotel type, so a
  subtype it did not list was read as no Organization at all.
- **Rule now:** the list also takes BankOrCreditUnion, InsuranceAgency, AccountingService, FoodEstablishment,
  CafeOrCoffeeShop, Bakery, BarOrPub, FastFoodRestaurant, Hospital, MedicalClinic, Physician, Dentist, Pharmacy and
  Hotel; STR-5 and the brand name read their names too. The "@id given different types" rule keeps the old list, so a
  bank typed beside FinancialService on one @id is no clash (DECISIONS 229; amends 39).
- **Test:** `test_a_homepage_typed_only_bank_or_credit_union_has_organization_markup` (`tests/test_round3_kinds_charset_locks.py`)

## FA-033

- **Date:** 2026-10-15
- **Site:** a restaurant site (the external review's round 3; not named here)
- **Report said:** "8 page(s) lack the structured data type expected for their page kind", an Article type expected.
- **Page really had:** branch pages typed Restaurant and listing pages typed CollectionPage, each with
  og:type=article (set on every page by the site builder).
- **Cause:** og:type=article alone made a page an article, whatever else the page said it was.
- **Rule now:** a page typed Restaurant or CollectionPage is not an article by its og:type alone; a path word (/blog/,
  /haberler/ …) still makes it one, and Product markup is still never evidence for a page kind (DECISIONS 229; amends 39).
- **Test:** `test_a_branch_typed_restaurant_and_a_listing_with_og_type_article_are_not_articles` (`tests/test_round3_kinds_charset_locks.py`)

## FA-034

- **Date:** 2026-10-27
- **Site:** a Turkish shop (the 27 October three-site comparison; not named here)
- **Report said:** "1 page(s) declare a <html lang> that does not match the content language", content detected as
  Italian (31 Italian stopwords against 4 Turkish).
- **Page really had:** a Turkish product list whose every card says "Ürünü İncele 2.si %10 indirimli".
- **Cause:** the ordinal suffix after a number ("2.si") was read as the word "si", an Italian stopword.
- **Rule now:** an ordinal suffix written after a number (2.si, 3üncü, 2nd, 1º) is not a word, and "si" is an
  ordinary word in Turkish (`NOT_FOREIGN_IN`) (DECISIONS 265).
- **Test:** `test_a_turkish_shop_list_with_ordinal_discounts_is_not_italian` (`tests/test_w12_false_alarms.py`)

## FA-035

- **Date:** 2026-10-27
- **Site:** a restaurant chain (the 27 October three-site comparison; not named here)
- **Report said:** branch pages "lack the structured data type expected for their page kind", an Article expected.
- **Page really had:** branch pages under /sube/ with og:type=article from the site builder and no typed markup at all
  (FA-033 covered only branch pages typed Restaurant).
- **Cause:** og:type=article made any untyped page an article.
- **Rule now:** a page under a place section (/sube/, /semt/, /bolge/, /magaza/, /lokasyon/, /branch/, /locations/,
  /store/ …) is never an article by its og:type; its kind is not guessed (DECISIONS 266).
- **Test:** `test_a_branch_page_with_og_type_article_and_no_markup_is_not_asked_for_article` (`tests/test_w12_false_alarms.py`)

## FA-036

- **Date:** 2026-10-27
- **Site:** a bank (the 27 October three-site comparison; not named here)
- **Report said:** "Part of the content (50%–80% present) is missing from the raw HTML of 2 page(s)", quoting
  "Mavi Işık Filtresi", "Daha Büyük Metin" and other labels as text that appeared only after JavaScript.
- **Page really had:** those labels in the raw HTML, inside an accessibility widget printed within <head>.
- **Cause:** the analyzer dropped all text until </head>, even after a body element had ended the head early
  (DECISIONS 260); browsers show it, so the rendered view had more words. Scripts there were also counted as
  render-blocking head scripts.
- **Rule now:** once a body element has ended the head, its text is body text and its scripts are body scripts
  (DECISIONS 267).
- **Test:** `test_text_after_an_element_that_ended_the_head_early_is_body_text` (`tests/test_w12_false_alarms.py`)

## FA-037

- **Date:** 2026-10-27
- **Site:** a restaurant chain's blog (the 27 October three-site comparison; not named here)
- **Report said:** "1 page(s) show questions and answers but have no FAQPage structured data", quoting "Bekir asıl
  sen ne yapıyorsun burada?" and other lines.
- **Page really had:** a short story whose dialogue asks questions in running paragraphs; no question-and-answer block.
- **Cause:** any run of a question-mark paragraph followed by a longer paragraph counted as a Q&A pair.
- **Rule now:** on an article (Article/BlogPosting markup or og:type=article) whose questions are all plain running
  text, neither FAQPage nor "questions not marked as headings" is asked; questions marked as headings, accordion
  toggles or <dt> are still read as a block (DECISIONS 268).
- **Test:** `test_dialogue_in_a_blog_story_is_not_a_question_and_answer_block` (`tests/test_w12_false_alarms.py`)

## FA-038

- **Date:** 2026-10-28
- **Site:** a shop's blog (the 27 October independent review of the w12 reports; not named here)
- **Report said:** "16 page(s) lack the structured data type expected for their page kind", and the client card told
  the shop to add an Article block to /blog/2, /blog/3 and /blog/4.
- **Page really had:** page 2, 3 and 4 of the blog's list of posts ("Blog | … - Sayfa 2"), each linking to several posts.
- **Cause:** a page under /blog/ was an article by its path alone; a list page was never told apart.
- **Rule now:** two of three signals (a page number in the address, in the title, links to several posts) make a page
  "pagination"; no type is expected of it, and the release gate refuses content advice for pagination, listing,
  category, 404 and unknown pages (DECISIONS 278).
- **Test:** `test_blog_pagination_expects_no_article` (`tests/test_w13_page_kind.py`)

## FA-039

- **Date:** 2026-10-28
- **Site:** a bank (the 27 October independent review of the w12 reports; not named here)
- **Report said:** "104 page(s) have no og:title", "104 page(s) have no og:description" and "68 page(s) have no meta
  description", beside TSEO-1's "end <head> early: meta or Open Graph tags after it are read as body" on the same pages;
  and the robots tag both as an Info note (ACC-3) and inside a High finding (TSEO-1).
- **Page really had:** every one of those tags, printed after an accessibility widget's <div> that ended <head>.
- **Cause:** STR-10 and ACC-3 read the tags the head held, so tags after the break looked missing or stray; the same
  cause was said up to four times, with a fix ("add og:title") that does not work while the widget stays.
- **Rule now:** pages whose tag comes after the break are said under TSEO-1 only (`evidence.absorbed_from`), and a
  canonical there is "not assessed", never absent (DECISIONS 278).
- **Test:** `test_tags_after_early_head_close_are_one_finding` (`tests/test_w13_head_family.py`)

## FA-040

- **Date:** 2026-10-28
- **Site:** a bank (the 27 October independent review of the w12 reports; not named here)
- **Report said:** a High card "11 addresses return an error and are linked internally or listed in the sitemap",
  listing the site's own /404?aspxerrorpath=… page as the affected addresses, with the step "take them out of the
  sitemap" and "re-tested: confirmed".
- **Page really had:** links whose address still held an unfilled template placeholder on the English pages; they
  redirected to the 404 page. None of the 11 addresses was in the sitemap.
- **Cause:** the 4xx finding listed the failing addresses, not the pages linking to them; the catalogue step was
  unconditional; the second look asked the 404 page again, which proves only that it answers 404.
- **Rule now:** the affected addresses are the source pages (and the sitemap entries that end at the error), the
  failing addresses are a separate field, the sitemap step appears only when an address is in the sitemap, and the
  second look checks that the source still links and the target still fails (DECISIONS 278).
- **Test:** `test_error_page_target_is_not_confirmed_but_the_source_is_retested` (`tests/test_w13_verification_target.py`)
