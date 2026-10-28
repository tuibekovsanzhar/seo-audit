# About Maya-Audit (the crawler)

> **Draft for a public page.** The items marked **to be confirmed** must be filled in by the team before this text
> is published or sent to a site owner. Until then the crawler's user agent carries no link.

## What it is

Maya-Audit is a website auditing tool. It visits a website when someone who works with that site's owner asks for
an audit of its technical SEO and AI-readiness. It is not a search engine, it does not build an index, and it does
not collect content for training AI models. Each audit reads a limited number of pages (50 or 500) once.

## How to recognise it

| | |
|---|---|
| User agent | `Maya-Audit/0.2` (the product token is `Maya-Audit`; a link to this page is added once the page is published) |
| Public page | **to be confirmed** (the address where this text will be published) |
| Contact | **to be confirmed** (an email address read by a person) |
| Operator | **to be confirmed** (the company's legal name and country) |
| IP addresses | No fixed addresses today: audits run from the auditor's own computer. Ask the auditor for the address of the audit in question. Stable addresses are planned for the hosted service. |
| Verification | Not a verified bot today. Signed requests (Web Bot Auth) and Cloudflare's verified-bot programme are planned for the hosted service. |

Because the user agent is not verified, bot protection may challenge it like any unknown visitor. That says nothing
about how verified search or AI crawlers are treated.

## How it behaves

- It reads `robots.txt` first and obeys it, under the user agent token `Maya-Audit` (and `*` when the file does
  not name it). A 4xx answer for robots.txt is treated as "no rules", 429 as "back off", and a 5xx or unreachable
  robots.txt as "request nothing", as RFC 9309 describes.
- It sends about one request a second, one site at a time, and stops at its page cap or time limit.
- It asks only for pages and the files a page lists (the sitemap, images' headers, linked pages' status).
- It does not log in, submit forms, or add anything to a basket.
- It never tries to get past bot protection. If a site refuses it, the audit says so and stops reading.
- When the auditor has a Firecrawl key, page content is read through Firecrawl (a third-party page reader) with its
  basic proxy, which does not try to get past bot protection either. A stronger proxy is used only with the site
  owner's documented approval.

## How to allow it

Add an allow rule in your firewall or bot protection for requests whose User-Agent contains `Maya-Audit`, exempt
from challenges and rate limiting, for the length of the audit. Pairing the rule with the auditor's IP address is
safer, because a user agent can be copied. Step-by-step instructions for Cloudflare, Akamai and other firewalls are
printed in the audit report of a site that could not be read (see `maya_audit/allowlist.py`).

## How to block it

Add this to `robots.txt`:

```
User-agent: Maya-Audit
Disallow: /
```

The crawler then requests nothing from the site but `robots.txt`.

## Proving you own the site

Some checks (what named AI and search crawlers receive, ACC-4) run only for a site whose owner has verified it,
because they send requests under other crawlers' names. The auditor gives you a token; publish it either as

```html
<meta name="maya-site-verification" content="TOKEN">
```

in the `<head>` of the homepage, or as a DNS TXT record on the domain with the value
`maya-site-verification=TOKEN`. Remove it when the audits are finished.

## Questions or complaints

Write to the contact above (**to be confirmed**) with the date, the address requested and, if you have it, the IP
address the request came from.
