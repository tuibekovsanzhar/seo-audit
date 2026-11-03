"""Existing English recommendation estimates, shared by engine and web/client adapters.

These are labelled owner/effort estimates, not measurements or evidence of business impact.
Moved unchanged from the web catalog; qualification can select a better supported action.
"""
import re

_NOTES: dict[str, tuple[str, str, str]] = {
    "ACC-3": ("seo", "S", "A noindex or no-snippet instruction tells engines not to show or quote the page."),
    "ACC-4": ("developer", "M", "A firewall can turn AI crawlers away even when robots.txt allows them."),
    "ACC-5": ("developer", "M", "Server logs show which AI crawlers really visit, rather than which are allowed to."),
    "ACC-6": ("seo", "S", "Blocking a training crawler and a search crawler are different choices with different effects. "
                          "This note records which is which on this site."),
    "ACC-8": ("content", "S", "llms.txt is an optional file some sites publish for AI tools. No major answer engine documents "
                              "using it, so it is recorded, not scored."),
    "ACC-9": ("developer", "M", "When a site's protection turns away a crawler that says who it is, AI search and assistant "
                                "crawlers may be turned away the same way, and then cannot read or quote the site. Only Maya's "
                                "own crawler was measured here."),
    "IDX-9": ("seo", "S", "This is Google's own record of whether the page is in its index. A page that is not indexed cannot "
                          "appear in Google's results or AI answers."),
    "PRF-3": ("developer", "L", "Core Web Vitals describe how fast the page feels to real visitors, measured by Google from real visits."),
    "RND-5": ("developer", "M", "A consent wall, sign-in screen or paywall in the page's HTML is what a crawler reads instead of the content behind it."),
    "STR-11": ("developer", "M", "Two structured-data blocks that describe the same thing with different values leave an engine to guess which is right."),
    "STR-13": ("developer", "S", "An unfilled template marker such as {{price}} is read by engines as the actual value, and shown to visitors as it is."),
    "STR-15": ("content", "M", "A page with very little text of its own gives an engine little to quote."),
    "STR-16": ("content", "S", "The same description on many pages does not tell a reader, or an engine, which page to choose."),
    "STR-17": ("developer", "S", "A page with no link onward is a dead end for visitors and for crawlers that follow links."),
    "STR-18": ("content", "S", "The homepage title is the name engines show for the site. Without the brand name in it, a searcher "
                               "cannot tell whose site it is."),
    "STR-20": ("content", "M", "Crawlers read text; they do not watch video or run animation. A message that exists only in a "
                               "video is, for an engine, not on the page."),
    "STR-21": ("content", "M", "Engines and visitors look for who is behind a site, what it offers, how to reach it, and answers "
                               "to common questions. When one of these has no page, there is nothing to quote for it."),
    "STR-22": ("content", "M", "A news page that only links out sends engines to other sites for the story. The company's own "
                               "site then has nothing of its own to be quoted for it."),
    "STR-23": ("developer", "M", "JobPosting markup is how search engines recognise a page as an open position. Google requires "
                                 "it to show a job in its job listings."),
}

_BY_TITLE: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "ACC-1": (
        (r"robots\.txt returned a server error", "developer", "S", "Crawlers read robots.txt before anything else. When it fails to load, some stop and read nothing, and others treat the whole site as off-limits until it loads again."),
        (r"larger than 500 KiB", "developer", "S", "Crawlers may stop reading robots.txt after 500 KiB, so rules beyond that point can be ignored."),
        (r"returns an HTML page", "developer", "S", "A robots.txt address that answers with a web page gives crawlers no rules to read. Most then treat the site as having none."),
        (r"before any User-agent line", "developer", "S", "Rules written above the first User-agent line in robots.txt belong to no crawler, so a block the site meant to set is not set."),
    ),
    "ACC-2": (
        (r"blocks .* bot\(s\)", "seo", "S", "robots.txt decides which crawlers may read which pages. A rule can shut out a crawler you wanted, or one you did not mean to."),
        (r"Policy mismatch", "seo", "S", "What the site says it wants for AI crawlers and what its robots.txt tells them are different. Crawlers follow the file."),
        (r"which no longer have any effect", "seo", "S", "Rules for a crawler name that is no longer used do nothing. A block the site meant to keep may not be in place for the crawler that replaced it."),
        (r"Group precedence", "seo", "S", "A crawler with its own section in robots.txt ignores the general (*) rules. A rule you thought applied to everyone may not apply to it."),
    ),
    "ACC-3": (
        # The checklist's quick checks (DECISIONS 304).
        (r"carry noindex but robots\.txt blocks", "seo", "S", "A crawler that robots.txt keeps out never reads the page, so it never sees the noindex either, and the address can stay in the index from links to it."),
        (r"internal search or cart page\(s\) can be indexed", "developer", "S", "A site's own search results and cart are not pages to find in search: indexed, they spend crawl time and can show as thin or duplicate results."),
    ),
    "ACC-7": (
        (r"Crawl-delay: .* applies to", "developer", "S", "A long crawl delay means a crawler reads only a small part of the site in each visit, so new and changed pages are picked up late."),
        (r"asks .* to wait", "developer", "S", "The site asked this audit to slow down. The audit obeyed, which limited how many pages it could read in the time it had."),
    ),
    "IDX-1": (
        (r"server error \(5xx\)", "developer", "M", "A page that answers with a server error cannot be read, indexed or quoted, and repeated errors make crawlers visit less often."),
        (r"fail at the connection level", "developer", "M", "A page that cannot be connected to does not exist as far as a crawler is concerned."),
        (r"time out on every attempt", "developer", "M", "A page that never answers in time is given up on by crawlers, as it would be by a visitor."),
        (r"client error \(4xx\)", "content", "S", "A link or sitemap entry that leads to a missing page wastes a crawler's visit and sends visitors to an error."),
        (r"soft 404", "developer", "M", "When a missing address answers as if it were a real page, engines cannot tell real pages from mistakes and may index empty ones."),
        (r"answer with an empty page", "developer", "M", "Recorded empty responses supplied this client no readable page content at those times; intended purpose, other clients and business impact require corroboration."),
        (r"server error message with the server's file paths", "developer", "S", "An error message on a live page shows visitors and crawlers how the server is built, and engines may read the error text as the page's content."),
    ),
    "IDX-2": (
        (r"TLS certificate is not valid", "developer", "S", "With an invalid certificate, browsers show a warning and most crawlers refuse to read the site at all."),
        (r"expires in", "developer", "S", "When the certificate expires, browsers show a warning and crawlers stop reading the site until it is renewed."),
        (r"No HTTP to HTTPS redirect", "developer", "S", "Without a redirect, the http:// and https:// addresses are two copies of the site. Links to the http:// one do not count for the secure one, and visitors who type it get an insecure page."),
        (r"temporary redirect", "developer", "S", "A temporary redirect (302 or 307) says the move is not for good, so engines may keep the http:// address as the one they index."),
    ),
    "IDX-3": (
        (r"redirect loop", "developer", "S", "The tested native requests entered a redirect cycle. This does not establish access for every client or time."),
        (r"intermittently redirect to themselves", "developer", "S", "A request that is sent back to the same address is wasted. Crawlers that get it often enough may read the page less often."),
        (r"loop (for visitors without cookies|in Maya)", "developer", "S", "Maya observed a page response after sending the site's cookie; cookie-less checks cycled. Other clients were not measured."),
        (r"redirected to themselves once|verification is incomplete", "developer", "S", "A redirect cycle was observed, but verification is incomplete. Persistence and the underlying cause remain unknown."),
        (r"redirect chain", "developer", "S", "Each extra redirect is another request before the page appears. Crawlers follow only a few and may give up."),
        (r"did not follow", "developer", "S", "The page sends visitors on to an address this audit does not follow, so what they finally see was not checked."),
    ),
    "IDX-4": (
        (r"canonical that is broken, noindexed, or an error", "seo", "M", "The canonical tag names the version of a page that should be indexed. When it points at a page that cannot be indexed, neither may be."),
        (r"canonical that redirects back to the page itself", "seo", "S", "The canonical sends engines to another address and the redirect sends them back, so the page never states which address it prefers."),
        (r"canonical that redirects to another address", "seo", "S", "A canonical should name the final address; a redirecting one makes engines follow an extra step and weakens the signal."),
        (r"conflicting canonicals", "seo", "S", "Two different canonical signals leave the engine to choose, and it may choose neither."),
        (r"canonical on another site", "seo", "S", "A canonical pointing at another site tells engines to credit that site for this page's content."),
        (r"http:// or www variant", "seo", "S", "A canonical on the http:// or www version of the site names an address the site does not serve the page at, so engines get a second, weaker address for it."),
        (r"noindex and declare a canonical", "seo", "S", "noindex says to leave the page out; a canonical to another page says to fold it into that one. Together they are mixed signals, and the engine chooses."),
    ),
    "IDX-5": (
        # The checklist's quick checks (DECISIONS 304).
        (r"lists no images although", "developer", "S", "Image entries in the sitemap help engines find and index the images of a site with many, including ones loaded late or by a script."),
        (r"lists no videos although", "developer", "S", "A video sitemap tells engines where each video is, what it is about and which thumbnail to show, so the videos can appear in video results."),
        (r"No usable XML sitemap", "developer", "S", "A sitemap is the list of pages you want found. On a larger site, pages that are not well linked are found late or not at all without one."),
        # Reports saved before the sitemap check (`SAVED_ONLY`).
        (r"non-200 or noindex", "developer", "S", "A sitemap that lists missing or blocked pages is trusted less, and crawlers spend visits on pages that cannot be used."),
        (r"are not live, indexable pages", "developer", "S", "A sitemap that lists missing, redirected, empty or noindexed pages is trusted less, and crawlers spend visits on pages that cannot be used."),
        (r"could not be loaded", "developer", "S", "The referenced sitemap file was unavailable in the recorded request. Discovery through that file is unverified; links and other sitemaps may still expose its pages."),
        (r"written wrongly", "developer", "S", "An address with a “?” where a letter should be leads to another address than the page's, so the page it stands for is not found through the sitemap."),
        (r"not percent-encoded", "developer", "S", "Addresses are meant to be written with letters outside A to Z percent-encoded. Most crawlers read both forms, so this is a note, not a problem."),
        (r"<lastmod> values are identical", "developer", "S", "When every page claims the same change date, the dates carry no information and engines stop using them to decide what to re-read."),
        (r"same <lastmod>", "developer", "S", "Dates stamped by the generator, not by real changes, tell engines nothing about which pages changed."),
        (r"in the future", "developer", "S", "A change date in the future is an obvious error, and makes the sitemap's other dates less believable."),
        (r"draft or test page", "content", "S", "A draft or test page in the sitemap is offered to engines as a page of the site, and may be shown or quoted in place of a finished one."),
    ),
    "ACC-8": (
        (r"lead to pages that do not work", "content", "S", "An AI tool that follows llms.txt is sent to pages that are gone, empty or moved, so the file points it away from the site's real content."),
        (r"point to an address that redirects", "content", "S", "A link in llms.txt that redirects sends an AI tool one step further than needed, and some tools do not follow the step."),
        (r"does not open with", "content", "S", "The llms.txt proposal opens the file with the site's name as a “# ” title. A tool that reads the file that way may not find the name."),
    ),
    "IDX-6": (
        # The checklist's quick checks (DECISIONS 304).
        (r"whose canonical is another page", "developer", "S", "A link to a duplicate address sends crawlers to a page they then fold into another one: visits are spent twice and the canonical page gets its links second-hand."),
        (r"external destination.*GET redirect cycle", "developer", "M", "An observed redirect cycle prevents that request from reaching its destination; other client contexts may differ."),
        (r"Link target returns", "content", "S", "A broken link sends visitors and crawlers to nothing."),
        (r"tracking parameters", "developer", "S", "Internal links with tracking parameters create a second address for the same page, which splits its signals and wastes crawler visits."),
        (r"point to another site.*returns \d", "content", "S", "A link that looks internal but goes to another site's missing page sends visitors and crawlers to an error."),
        (r"point to another site.*could not be checked", "content", "S", "A link that looks internal leaves the site; whether the other page exists could not be checked."),
        (r"to other sites on .* 404 or 410", "content", "S", "A link to a page another site has removed sends visitors to an error page and tells engines the page is not kept up to date."),
        # Reports saved before team-preview-14, when the other address was not requested (`SAVED_ONLY`).
        (r"point to another site \([^)]*\) at a path that exists on this one$", "content", "S", "A menu or footer link that looks internal but leaves the site sends visitors and crawlers away from the page they expected."),
        (r"Cloudflare e-mail obfuscation", "developer", "S", "Cloudflare swaps the address for a placeholder that a script turns back into the address. A crawler or assistant that runs no script sees no contact address."),
    ),
    "IDX-7": (
        # The checklist's quick checks (DECISIONS 304).
        (r"do not link to their next page", "developer", "S", "Crawlers follow <a href> links, not buttons or scrolling: without a link to the next page, the items listed only there are found late or not at all."),
        (r"no breadcrumb or link to a category", "seo", "S", "A link from each product back to its category tells engines how the catalogue is organised and passes the product's visits on to the category."),
        (r"listed only in the sitemap", "seo", "M", "A page that nothing links to is found only through the sitemap, and engines treat pages nobody links to as less important."),
        (r"clicks from the homepage", "seo", "M", "Pages many clicks deep are crawled later and less often, and are treated as less important."),
    ),
    "IDX-8": (
        (r"differ mostly by the place name", "content", "L", "Many pages that repeat one text with only the place name changed can be treated as doorway pages, and none of them gives a reason to be shown."),
        (r"identical visible text", "seo", "M", "When several addresses show the same content, engines pick one to show, and it may not be the one you want."),
        (r"share the title", "content", "S", "Pages with the same title look like the same page in search results, so engines and visitors cannot tell them apart."),
        (r"nearly identical main content", "seo", "M", "Pages that say almost the same thing compete with each other, and an engine may show only one of them."),
        (r"copies or near-copies of each other", "seo", "M", "Groups of pages that are copies of each other compete with each other, and an engine "
                                                            "picks one page of each group to show, which may not be the one you want."),
        (r"reachable at two addresses", "developer", "S", "A page at two addresses gets its links and signals split between them, and engines choose which one to show."),
    ),
    "IDX-10": (
        (r"Bing's last crawl", "developer", "S", "Bing's index also feeds several AI assistants. A page Bing could not fetch is missing from all of them."),
        (r"IndexNow key", "developer", "S", "IndexNow tells Bing and others about changed pages at once. With a missing or wrong key file, those notices are ignored."),
    ),
    "PRF-1": (
        (r"The homepage takes .* to start answering", "developer", "M", "The homepage is the page every visitor and crawler reaches first. When it is slow to start answering, everything that follows starts late."),
        (r"take more than", "developer", "M", "A slow server makes crawlers read fewer pages per visit, and some give up before the page arrives."),
        (r"time out on some attempts", "developer", "M", "A page that sometimes does not answer is sometimes missing when a crawler visits."),
        (r"not cached at the CDN", "developer", "S", "When the CDN does not keep a copy of the HTML, every visitor and every crawler waits for the origin server, which is often the slowest part of the answer."),
        (r"baseline security header", "developer", "S", "Security headers protect visitors from injected scripts, framing and leaks of the address they came from. They are not a search signal."),
        (r"Strict-Transport-Security", "developer", "S", "Strict-Transport-Security tells browsers to use https only. It is a security setting; no answer engine documents using it."),
    ),
    "PRF-2": (
        (r"failed on some attempts", "developer", "M", "Pages that fail now and then are sometimes missing when a crawler visits, and crawlers come back less often to unreliable sites."),
        (r"of fetches failed across the audit", "developer", "M", "When a noticeable share of all requests fail, the site as a whole looks unreliable to crawlers."),
    ),
    "RND-1": (
        (r"Main content is missing from the raw HTML", "developer", "L", "Many AI crawlers do not run JavaScript. Content that appears only after scripts run is invisible to them."),
        (r"Part of the content", "developer", "L", "Part of the page appears only after JavaScript runs. Crawlers that do not run it see an incomplete page."),
        (r"may be client-rendered", "developer", "M", "The page's HTML looks like an empty shell that a script fills in. If so, crawlers that do not run JavaScript see nothing. It was not opened in a browser to confirm."),
    ),
    "RND-2": (
        (r"declared critical fact", "developer", "M", "Key facts such as prices should be in the page the server sends, so that every crawler can read them."),
        (r"appear only after JavaScript", "developer", "M", "Headings and prices that appear only after scripts run are missing for crawlers that do not run them."),
    ),
    "RND-3": (
        (r"only after a click or scroll", "developer", "M", "Crawlers do not click or scroll. Text that appears only after a visitor does is not read."),
        (r"may hide content behind interaction", "developer", "M", "The page's HTML suggests content behind tabs, accordions or 'load more'. Crawlers do not click, so it may go unread. It was not opened in a browser to confirm."),
    ),
    "RND-4": (
        (r"iframe.*accessible name", "developer", "S", "An unnamed frame lacks a label in the captured naming evidence. Verify its accessible name; this is an accessibility issue, not evidence of an SEO extraction failure."),
        (r"<canvas> is on .* part of the site's layout", "developer", "S", "A canvas draws pixels, not text, so nothing in it can be read by an engine. One that sits on every page is usually a background effect and holds nothing to read; this is recorded so that someone can confirm it."),
        (r"iframe(?!.*accessible name)", "developer", "M", "An iframe embeds a separate document. Its presence alone does not establish that essential content is inaccessible or that engines cannot extract it; inspect its purpose and equivalent page content."),
        (r"draw content on a <canvas>", "developer", "M", "A canvas draws pixels, not text. A chart or diagram drawn there cannot be read by an engine unless the page also says it in text."),
        (r"banner-shaped images", "content", "M", "Text that is part of a picture cannot be read by engines. If these banners contain words, the words are missing from the page as far as an engine can tell."),
    ),
    "RND-6": (
        (r"The homepage's HTML is", "developer", "M", "A heavy homepage is slower for every visit and leaves less of a crawler's budget for the content itself."),
        (r"HTML larger than", "developer", "M", "Very large pages may be cut off before the important part is read, and are slower for everyone."),
        (r"start their main content more than", "developer", "M", "When the content starts far down the HTML, after menus and scripts, a crawler that reads only the beginning may never reach it."),
    ),
    "RND-7": (
        (r"of their text in the main content", "developer", "M", "The extracted ratio compares content and surrounding text. It does not establish an extraction failure; actual reading and page purpose were not assessed by this ratio."),
        (r"no <main> or <article>", "developer", "S", "The assessed HTML has no <main> or <article> element. Content may still be identified through other structure; extraction failure was not assessed."),
    ),
    "STR-1": (
        (r"have no <title>", "content", "S", "The title is the name an engine shows for the page. Without one, the engine makes one up."),
        (r"title\(s\) are shared", "content", "S", "Pages with the same title look like the same page in search results, so engines and visitors cannot tell them apart."),
        (r"generic title", "content", "S", "A title such as 'Home' or only the site name says nothing about what the page is about."),
        (r"begin with the same", "content", "S", "Repeated prefixes can obscure the page subject when a title is truncated. Display width varies; there is no fixed Google character limit."),
    ),
    "STR-2": (
        (r"only <h1> is hidden|only a hidden <h1>", "developer", "S", "A heading hidden from readers may be read as hidden text, and the page's topic is then left to weaker hints."),
        (r"have no <h1>", "content", "S", "The main heading tells engines what the page is about. Without it they rely on weaker hints."),
        (r"have an empty <h1>", "content", "S", "An empty heading does not supply a meaningful page topic."),
        (r"The homepage has no <h1>", "content", "S", "The homepage's main heading is where a visitor and an engine read what the whole site is. Without it they take it from the title and the menu."),
        (r"visible section heading", "content", "M", "Section headings are the homepage's outline: they tell a reader moving by headings and a machine reading the page what each part is about."),
        (r"no subheadings", "content", "M", "Subheadings divide a long page into passages an engine can quote one at a time."),
        (r"more than one <h1>", "content", "S", "Several main headings make it less clear which one names the page's topic. This is a small matter."),
    ),
    "STR-3": (
        # The checklist's quick checks (DECISIONS 304).
        (r"name no author", "content", "S", "A named author with a page of their own is one of the signals engines use to judge who stands behind advice and how far to trust it."),
        (r"Product markup without a GTIN or MPN", "developer", "S", "A GTIN or MPN lets Google match the product to the same item elsewhere, which its shopping results and merchant listings rely on."),
        (r"Organization block does not parse", "developer", "S", "A block that does not parse is ignored whole, so the Organization it describes is not read at all."),
        (r"Organization structured data has no", "developer", "S", "A logo and profile links let engines tie the site to the brand's other official pages."),
        (r"VideoObject that looks like an unfilled default", "content", "S", "A placeholder name or date tells engines nothing true about the video and can make the markup look unreliable."),
        (r"JSON-LD that does not parse", "developer", "S", "Structured data that does not parse is ignored entirely, as if it were not there."),
        (r"no Organization structured data", "developer", "M", "Organization markup on the homepage tells engines who is behind the site: name, logo and official profiles."),
        (r"values in a form Google cannot read", "developer", "S", "A rating or price Google cannot read as a number or code is dropped, so the item loses what it was marked up to show."),
        (r"missing Google-required properties", "developer", "M", "Google ignores structured data that lacks the properties it requires for that type."),
        (r"lack the structured data type expected", "developer", "M", "Structured data states what a page is (a product, an article) in a form machines read directly."),
        (r"questions and answers but have no FAQPage", "content", "S", "FAQPage markup states, in a form machines read directly, which questions the page answers and what the answers are."),
        (r"breadcrumb trail but have no BreadcrumbList", "developer", "S", "BreadcrumbList markup tells engines where the page sits in the site; Google can show the trail instead of the bare address."),
        (r"one price and no buy button", "content", "S", "A page that shows one price may sell one product. If it does, Product structured data says so to the engines that read it."),
        (r"structured data that returns an error", "developer", "S", "An address in structured data that leads to an error points engines at nothing."),
        (r"different URL in their structured data than their canonical", "developer", "S", "Structured data and the canonical tag should name the same address. When they differ, engines get two answers to 'which page is this'."),
        (r"@id that no crawled page defines", "developer", "S", "A reference to something that is defined nowhere leaves that part of the structured data empty."),
        (r"@id\(s\) are given different types", "developer", "S", "One identifier described as two different kinds of thing is a contradiction engines cannot resolve."),
    ),
    "STR-4": (
        (r"differs from the .* shown on the page", "developer", "M", "When structured data disagrees with the visible page, an engine may quote the wrong value or trust neither."),
        (r"did not show when it was read", "developer", "S", "The markup lists prices the page did not show when it was read, usually the other side of a monthly/yearly switch. That is not a conflict, but someone should confirm the page can show each of them."),
        (r"is not shown on the page", "developer", "S", "Google asks sites not to mark up things readers cannot see. A value in the markup that is not on the page may be ignored, or may be out of date."),
    ),
    "STR-5": (
        (r"@id\(s\) carry a different name", "developer", "M", "One brand identifier with different names on different pages makes it harder for engines to treat the brand as one entity."),
        (r"brand is named .* different ways", "content", "M", "A consistent name helps engines recognise the brand as one entity across the site."),
        (r"sameAs profile link", "content", "S", "Profile links tell engines which social and directory pages belong to the brand. Dead ones weaken that."),
        (r"og:site_name holds the page title", "developer", "S", "og:site_name is where a page says which site it belongs to. A page title in it gives every page a different site name."),
    ),
    "STR-6": (
        (r"looks auto-stamped", "developer", "M", "The date pattern needs comparison with actual edit records. Same-day values alone do not prove incorrect dates."),
        (r"carry a future date", "content", "S", "A date in the future is an obvious error and makes the page's other dates less believable."),
        (r"date signals more than", "content", "S", "When a page's dates disagree, engines cannot tell how fresh it is."),
        (r"show no published or updated date", "content", "S", "Dates tell engines how fresh an article is. Without one, it may be treated as old."),
    ),
    "STR-7": (
        (r"placeholder alt text", "content", "S", "A filename or generic label may not describe an informative image. Its actual purpose, equivalent text and decorative intent require review."),
        (r"do(es)? not load", "developer", "S", "An image that fails to load shows visitors a gap and gives engines nothing to show beside the page."),
        (r"WebP or AVIF", "developer", "M", "Markup references do not establish delivered image formats. Compare saved response formats, byte sizes and acceptable quality before recommending delivery alternatives; savings are not guaranteed."),
        (r"missing or empty alt text|has no alt text|with no alt text", "content", "M", "Alt text is how an engine, and a screen reader, knows what an image shows."),
        (r"have no alt attribute", "content", "S", "An image with no alt attribute at all is announced by screen readers by its file name. These look decorative, so it is a small matter."),
        (r"sampled image file\(s\) are over 500 KB", "developer", "S", "A heavy image slows the page for every visitor, most on mobile data."),
        (r"format their file name does not say", "developer", "S", "A file whose name and format disagree was usually never converted, and is often far larger than it needs to be."),
        (r"no width and height \(layout shift risk\)", "developer", "S", "An image with no declared size makes the page jump as it loads, which readers notice and Core Web Vitals count."),
        (r"image preload\(s\) declare", "developer", "S", "A preload the browser skips gives no head start to the image it was meant to speed up."),
        (r"video file\(s\) the pages play are over 5 MB", "developer", "M", "A large video loaded with the page costs visitors time and mobile data before they choose to watch it."),
    ),
    "STR-8": (
        (r"lack supported header associations", "developer", "M", "Data cells without meaningful header relationships can be difficult to interpret with a screen reader; this does not establish a ranking penalty."),
        (r"pricing or spec comparisons", "developer", "M", "Prices and specifications in a real table can be read row by row. Laid out with plain boxes, an engine sees a run of numbers with nothing saying which belongs to what."),
        (r"other table-like", "developer", "S", "Content laid out to look like a table, without being one, is harder for engines to read in the right order."),
        (r"empty <table>", "developer", "S", "An empty table announces rows of facts and holds none. An engine or a screen reader that reads the page as the server sent it finds nothing in it."),
    ),
    "STR-9": (
        (r"same hreflang code to two or more", "developer", "S", "Two addresses for one language code leave engines to guess which version to show."),
        (r"hreflang target page\(s\) are not indexable", "developer", "S", "A language version that cannot be indexed, or has no title or description, has nothing to show for its readers."),
        (r"lack x-default or a link to themselves", "developer", "S", "x-default and a link to the page itself complete the set of versions, so engines can pick one for every reader."),
        (r"hreflang links to URLs that do not return 200", "developer", "S", "A language-version link that leads to an error tells engines about a version that is not there."),
        (r"hreflang links that are not returned", "developer", "M", "Language versions must point at each other. A one-way link is ignored, and engines may then show the wrong language."),
        (r"<html lang> that does not match", "developer", "S", "The declared language tells engines which readers the page is for. A wrong one can send it to the wrong audience."),
        (r".", "developer", "S", "Language and region declarations help engines serve each page to the right readers."),
    ),
    "STR-10": (
        (r"Open Graph tags but no Twitter card", "developer", "S", "Without twitter:card a link shared on X shows as a bare address instead of a card with title and image."),
        (r"og:image that returns", "content", "S", "The declared preview-image request failed in the recorded scope. Whether a platform shows another image or an empty preview was not assessed."),
        (r"site icon as share image", "content", "S", "The share image is what appears when the page is shared or shown as a source. A tiny site icon is blurred or left out of the preview."),
        (r"share image smaller than 200", "content", "S", "Networks and engines do not show a share image under 200 × 200 pixels, so the page is shown with no picture."),
        (r"share image smaller than 600", "content", "S", "Under 600 × 315 pixels the large networks show the share image as a small thumbnail beside the text, not as the large card."),
        (r"have no |have an empty ", "content", "S", "The assessed page lacks the recorded preview metadata or description. Its actual search snippet or social preview was not assessed; review each channel before changing metadata."),
    ),
    "STR-13": (
        # Unfilled template markers take the check's own note (`_NOTES`).
        (r"invisible characters", "content", "S", "Invisible characters may affect text processing or copying. Their presence does not prove a ranking or indexing failure."),
    ),
    "STR-12": (
        (r"mostly in another language", "content", "M", "A page written in one language and declared as another may be shown to readers who cannot read it."),
        (r"section headings in another language", "content", "S", "Headings in a different language from the text read as an unfinished translation."),
        (r"placeholder or template text", "content", "S", "Placeholder text on a live page ('lorem ipsum', 'your company name') reads as an unfinished site."),
    ),
    "STR-14": (
        (r"generic text", "content", "S", "Link text tells engines what the linked page is about. 'Click here' tells them nothing."),
        (r"no text at all|ha(?:s|ve) no text \(on ", "developer", "S", "A link with no text gives engines, and screen readers, no idea where it leads."),
    ),
    "STR-19": (
        # "lead nowhere" is the wording of reports saved before team-preview-8.
        (r"no address a crawler can follow|lead nowhere|ha(?:s|ve) no address \(", "developer", "S", "A crawler follows addresses, not clicks. A link to content with '#' or a script in place of an address gives it nothing to follow, even when it works for a visitor."),
        (r"control\(s\) are coded as links|control group\(s\) use anchors", "developer", "S", "A control is not automatically a broken navigation link. Review its accessible role, name and keyboard behavior; saved markup alone does not establish whether interaction works."),
        (r"in the footer look like links", "content", "S", "Footer entries with no address behind them promise pages that cannot be reached. To visitors and engines the site looks unfinished."),
    ),
    "TSEO-1": (
        # The checklist's quick checks (DECISIONS 304).
        (r"decomposed character", "developer", "M", "A letter written as two code points makes a second address for the same word: links typed or copied with the normal letter lead elsewhere, and the address looks garbled when shared."),
        (r"unclear slug", "developer", "M", "A short address made of words tells visitors and engines what the page is before they open it; ids and symbols say nothing."),
        (r"end <head> early: canonical", "developer", "S", "Google stops reading the head at the first element that cannot stand in it, so a canonical, robots or hreflang tag after it is ignored."),
        (r"end <head> early: meta", "developer", "S", "Tags after an element that ends the head early are read as body; previews and some crawlers then miss them."),
        (r"no viewport meta tag", "developer", "S", "Google indexes the mobile version of a page; without a viewport phones show a shrunken desktop layout."),
        (r"same analytics tag more than once", "developer", "S", "A visit counted twice doubles page views and halves the bounce rate, so the site's own numbers mislead."),
        (r"stop readers from zooming", "developer", "S", "Readers who need larger text cannot zoom in, which also fails an accessibility criterion."),
        (r"over plain http:// \(mixed content\)", "developer", "S", "Browsers block insecure scripts and styles on a secure page, so parts of it break or it shows as not fully secure."),
        (r"script\(s\) in <head> without defer or async", "developer", "M", "Scripts that block the first render make every visitor wait for code before seeing the page."),
        (r"guidance band", "content", "S", "Character bands are editorial guidance, not Google limits or proof of a technical failure. Review clarity and usefulness in context."),
        (r".", "content", "S", "Titles, descriptions and headings are the basics every search engine reads to decide what a page is about and how to show it."),
    ),
    "STR-15": (
        # The checklist's quick checks (DECISIONS 304).
        (r"list no product or almost none", "content", "S", "An indexable list page with nothing in it can be treated as a soft 404, and a visitor who lands on it from search finds nothing to buy."),
    ),
}

_DEFAULT = ("seo", "M", "This check looks at whether search and answer engines can read and understand the page.")


# DECISIONS 306: a fix that renames many addresses and needs a redirect for each old one is at least Medium effort and
# never a quick win, whatever its own entry says (the client reports read `renames_addresses`).
RENAMES_ADDRESSES = frozenset({"tseo1.url_decomposed", "tseo1.url_slug_unclear"})
EFFORT_ORDER = ("S", "M", "L")


def renames_addresses(check_id: str, title: str = "", rule: str | None = None) -> bool:
    if rule is None:
        from .rules import rule_id
        rule = rule_id(check_id, title)
    return rule in RENAMES_ADDRESSES


def note(check_id: str, title: str = "") -> dict[str, str]:
    """The note for a finding: `owner`, `effort`, `why`. `title` picks the right one when a check reports several kinds
    of thing. A check with neither kind of entry gets the general note (and the catalog test fails). A fix that renames
    addresses is at least "M" (DECISIONS 306)."""
    found = _note(check_id, title)
    if found["effort"] == "S" and title and renames_addresses(check_id, title):
        found = {**found, "effort": "M"}
    return found


def _note(check_id: str, title: str = "") -> dict[str, str]:
    owner, effort, why = _NOTES.get(check_id, _DEFAULT)
    variants = _BY_TITLE.get(check_id, ())
    for pattern, by_owner, by_effort, by_why in variants:
        if re.search(pattern, title, re.IGNORECASE):
            return {"owner": by_owner, "effort": by_effort, "why": by_why}
    if variants and not title:  # the check as a whole (a follow-up about "IDX-2"): its first note
        _, owner, effort, why = variants[0]
    return {"owner": owner, "effort": effort, "why": why}



# Qualified observation titles are produced after the raw checks; original variants remain for older reports.
for _cid, _rows in {
 'IDX-6': ((r'external destination.*HEAD errors', 'content','S','HEAD failures do not establish deleted destinations; GET corroboration is required.'),
           (r'external destination.*mixed HEAD/GET', 'content','S','Mixed request results require source and time context, not a universal conclusion.')),
 'IDX-1': ((r'returned repeated empty GET', 'developer','M','Repeated empty responses are scoped retrieval failures; intended content and cause require diagnosis.'),
           (r'returned an empty response', 'developer','M','One empty response does not establish persistent page failure.')),
 'IDX-5': ((r'sitemap URL observation', 'seo','M','Review each URL response and intended indexing before changing sitemap entries.'),),
 'STR-14': ((r'generic-text link occurrence','content','S','Link purpose depends on accessible name and surrounding context.'),),
 'STR-2': ((r'no meaningful <h1>','content','S','An empty heading does not supply a meaningful page topic.'),),
}.items():
    _BY_TITLE[_cid]=(*_rows,*_BY_TITLE.get(_cid,()))


def why(check_id: str, *titles: str) -> str | None:
    """Why a finding matters, in the catalogue's words (CR-16), for the first of `titles` that has its own entry (the
    title as the check wrote it, before qualification, then the shown one); else the check's own note. None when only
    the general note would be given: a report then says nothing rather than a sentence about no finding in particular.
    A title that matches none of a check's kinds is not given the check's first kind."""
    for title in [t for t in titles if t] or [""]:
        found = note(check_id, title)
        if found["why"] != _DEFAULT[2]:
            return found["why"]
    return None
