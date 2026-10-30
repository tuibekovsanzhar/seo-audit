"""How a site owner lets Maya's own crawler in. Shown only when a site could not be read at all.

These are instructions for the owner's own firewall, to copy and hand over. Maya never changes anything on a site,
and never tries to get past protection on its own. A user agent can be copied by anyone, so each instruction also
names the safer pairing with the auditor's IP address, and says to remove the rule afterwards.
"""

from __future__ import annotations

from typing import Any

BOT_PAGE = "docs/BOT.md"


def instructions(product_token: str, user_agent: str, blocker: str | None = None) -> list[dict[str, Any]]:
    """One block per kind of protection; the one the audit recognised comes first."""
    rule = f'(http.user_agent contains "{product_token}")'
    blocks = [
        {"id": "cloudflare", "title": "Cloudflare",
         "steps": ["In the Cloudflare dashboard open the site, then Security → WAF → Custom rules → Create rule.",
                   f"Name it “Allow {product_token} audit”. Choose “Edit expression” and paste:  {rule}",
                   "Action: Skip. Tick “All remaining custom rules”, “All rate limiting rules”, “All managed rules” and “All Super Bot Fight Mode Rules”. Deploy.",
                   "On the Free plan, Bot Fight Mode cannot be skipped by a rule: switch it off under Security → Bots for the length of the audit, or add an "
                   "IP Access rule (Security → WAF → Tools) that allows the auditor's IP address.",
                   "Safer: add  and (ip.src eq AUDITOR_IP)  to the expression, with the IP address the auditor gives you. Delete the rule after the audit."],
         "copy": rule},
        {"id": "akamai", "title": "Akamai",
         "steps": ["In Akamai Control Center open Bot Manager (or App & API Protector) for the site's security configuration.",
                   f"Under Custom Bot Categories, add a category “{product_token} audit” and define a custom bot whose User-Agent contains:  {product_token}",
                   "Set that category's action to Monitor (not Deny, Tarpit or Challenge) in the policy that protects the site, and activate the configuration.",
                   "Safer: add the auditor's IP address to a network list and exempt that list from bot and rate controls instead. Remove it after the audit."],
         "copy": product_token},
        {"id": "generic", "title": "Any other firewall, CDN or bot protection",
         "steps": [f"Add an allow rule for requests whose User-Agent contains “{product_token}”. The full user agent is:  {user_agent}",
                   "Exempt that rule from challenges (CAPTCHA, JavaScript checks) and from rate limiting. The audit sends about one request a second.",
                   "Safer: allow the auditor's IP address instead of, or as well as, the user agent.",
                   "Keep the rule only for the audit, and check robots.txt does not disallow the crawler."],
         "copy": product_token},
    ]
    first = (blocker or "").strip().lower()
    return sorted(blocks, key=lambda block: block["id"] != first)


def lines(product_token: str, user_agent: str, blocker: str | None = None) -> list[str]:
    out = [f"How to let the audit in (for the site's owner). The crawler identifies itself as “{user_agent}”; what it is and how to "
           f"reach its operator is described in {BOT_PAGE}."]
    for block in instructions(product_token, user_agent, blocker):
        out.append(block["title"] + ":")
        out += [f"  {number}. {step}" for number, step in enumerate(block["steps"], 1)]
    return out


def markdown(product_token: str, user_agent: str, blocker: str | None = None) -> str:
    out = ["", "## How to let the audit in (for the site's owner)", "",
           f"The site answered Maya's own crawler with a block or a challenge, and no other reader could read it. The crawler identifies "
           f"itself as `{user_agent}`; what it is and how to reach its operator is described in `{BOT_PAGE}`. Maya does not try to get past "
           "protection: these are steps for the owner's own firewall.", ""]
    for block in instructions(product_token, user_agent, blocker):
        out += [f"### {block['title']}", "", *(f"{number}. {step}" for number, step in enumerate(block["steps"], 1)), ""]
    return "\n".join(out)
