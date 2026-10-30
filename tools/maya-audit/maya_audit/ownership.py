"""Proving who controls a site, so the audit may test what AI crawlers receive (ACC-4).

Two methods, either is enough:

- a meta tag on the homepage:  <meta name="maya-site-verification" content="TOKEN">
- a DNS TXT record on the domain:  maya-site-verification=TOKEN

The token is not a secret. It is made from the domain and a random value kept on the auditor's computer, so it is
the same every time for that site and cannot be guessed for another. Only someone who can edit the site or its
DNS can publish it.

The DNS record is looked up through Google's public DNS-over-HTTPS service, because Python has no TXT lookup of its
own. That request names the domain and nothing else. It is made only when a token is configured, the DNS method is
switched on, and the meta tag was not found.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

META_NAME = "maya-site-verification"
TXT_PREFIX = "maya-site-verification="
RESOLVER = "https://dns.google/resolve"
# Tests replace this with a mock transport. Nothing else should.
TRANSPORT: httpx.BaseTransport | None = None


def token_for(domain: str, secret: str) -> str:
    """The site's verification token: the same for a domain on this computer, unguessable for any other."""
    digest = hmac.new(secret.encode("utf-8"), domain.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
    return "maya-" + digest[:32]


def meta_tag(token: str) -> str:
    return f'<meta name="{META_NAME}" content="{token}">'


def txt_record(token: str) -> str:
    return TXT_PREFIX + token


def instructions(domain: str, token: str) -> list[str]:
    """The two ways to verify, as text to hand to whoever runs the site."""
    return [f"Either add this tag inside <head> on the homepage of {domain}:  {meta_tag(token)}",
            f"Or add a DNS TXT record on {domain} (name @) with this value:  {txt_record(token)}",
            "Then run the audit again with ownership verification switched on. DNS changes can take up to a day to be seen.",
            "Remove the tag or the record when the audits are finished; it does nothing else."]


def dns_txt_verified(domain: str, token: str, *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Whether the domain publishes the token in a TXT record. Never raises."""
    base = {"method": "dns_txt", "domain": domain, "record": txt_record(token), "resolver": RESOLVER}
    try:
        with httpx.Client(timeout=10, trust_env=False, transport=transport or TRANSPORT) as http:
            response = http.get(RESOLVER, params={"name": domain, "type": "TXT"}, headers={"accept": "application/dns-json"})
        if response.status_code != 200:
            return {**base, "verified": False, "reason": f"the DNS lookup answered HTTP {response.status_code}, so the TXT record could not be checked"}
        records = [str(answer.get("data", "")).replace('" "', "").strip('"') for answer in response.json().get("Answer") or []
                   if isinstance(answer, dict) and answer.get("type") == 16]
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        return {**base, "verified": False, "reason": f"the DNS lookup failed ({type(exc).__name__}), so the TXT record could not be checked"}
    if txt_record(token) in records:
        return {**base, "verified": True, "reason": "the domain's DNS TXT record matches the configured token"}
    return {**base, "verified": False, "txt_records_found": len(records),
            "reason": "the domain has no DNS TXT record matching the configured token"}


def section(ownership: dict[str, Any], domain: str, token: str, checked_at: str) -> dict[str, Any]:
    """The report's `ownership` section, from what the audit found."""
    verified = bool(ownership.get("verified"))
    return {"verified": verified, "method": ownership.get("method") if verified else None, "token": token, "checked_at": checked_at,
            "summary": (f"Ownership of {domain} is verified ({'meta tag on the homepage' if ownership.get('method') == 'meta_tag' else 'DNS TXT record'}), "
                        "so the audit tested what named AI and search crawlers receive (ACC-4)." if verified else
                        f"Ownership of {domain} is not verified: {ownership.get('reason') or 'no token was found'}. ACC-4 did not run."),
            "instructions": instructions(domain, token)}
