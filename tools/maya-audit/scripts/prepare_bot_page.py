"""Turn the guarded template into the exact file to publish (launch gate LG-02).

    .venv/bin/python scripts/prepare_bot_page.py                     # writes the default file
    .venv/bin/python scripts/prepare_bot_page.py --contact ops@x.com # different address

`site/maya-audit-bot/index.html` keeps its publishing checklist and its
REPLACE-BEFORE-PUBLISHING marker on purpose: that marker is what stops a half-finished
page from ever being accepted, and a test proves the crawler refuses it. This script
produces the published version from it, so the two can never drift apart:

  * deletes the publishing-checklist comment;
  * replaces the contact placeholder with a real address;
  * refuses to write anything if the marker survives either step.

The output is verified the same way the crawler verifies it before a live crawl.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_audit.botinfo import UNPUBLISHED_MARKER  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "site", "maya-audit-bot", "index.html")
DEFAULT_OUT = os.path.join(ROOT, "site", "maya-audit-bot", "published", "index.html")
DEFAULT_CONTACT = "sanzhar.tuibekov@withmaya.ai"
# The deployment currently serving this page is a test host, and the page says so.
DEFAULT_NOTE = ("This page is hosted on a test deployment while Maya's crawler is being validated. The crawler is operated by Maya (withmaya.ai); the address below is monitored and reaches the person responsible.")
PLACEHOLDER = f"<p>{UNPUBLISHED_MARKER}: add a real contact address for crawler questions and complaints.</p>"


def build(template: str, contact: str, note: str | None = None) -> str:
    contact_line = (f'<p>Questions or complaints about this crawler: '
                    f'<a href="mailto:{contact}">{contact}</a>. We answer every message about crawler '
                    f'behavior, and we will stop crawling a site on request.</p>')
    if PLACEHOLDER not in template:
        raise SystemExit("template no longer contains the contact placeholder; update this script")
    page = template.replace(PLACEHOLDER, contact_line)
    if note:  # e.g. a test deployment hosted somewhere other than the company's own domain
        marker = '<p class="muted">If you found <code>Maya-Audit</code> in your server logs, this page explains what it is.</p>'
        if marker not in page:
            raise SystemExit("template intro paragraph moved; update this script")
        page = page.replace(marker, marker + f'\n<p class="muted"><strong>{note}</strong></p>')
    page = re.sub(r"<!--.*?-->\n?", "", page, flags=re.S)
    if UNPUBLISHED_MARKER in page:
        raise SystemExit("refusing to write: the unpublished marker survived")
    if "Maya-Audit" not in page:
        raise SystemExit("refusing to write: the page no longer names Maya-Audit")
    return page


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contact", default=DEFAULT_CONTACT, help=f"contact address (default {DEFAULT_CONTACT})")
    parser.add_argument("-o", "--out", default=DEFAULT_OUT)
    parser.add_argument("--note", default=DEFAULT_NOTE,
                        help="extra line under the intro; pass --note '' to omit it")
    args = parser.parse_args()

    with open(TEMPLATE, encoding="utf-8") as fh:
        page = build(fh.read(), args.contact, args.note)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)

    print(f"wrote {args.out}")
    print(f"  contact address:            {args.contact}")
    print(f"  names Maya-Audit:           {'Maya-Audit' in page}")
    print(f"  unpublished marker present: {UNPUBLISHED_MARKER in page}")
    print(f"  HTML comments left:         {len(re.findall(r'<!--', page))}")
    print("\nPublish this file at a stable HTTPS URL, then verify with:")
    print("  .venv/bin/python -c \"from maya_audit.botinfo import check_bot_info_page as c; "
          "print(c('https://<url>', 'Maya-Audit/0.2 (+https://<url>)', 'Maya-Audit'))\"")


if __name__ == "__main__":
    main()
