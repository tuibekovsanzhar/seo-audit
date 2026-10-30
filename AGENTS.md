# Agent rules for withmaya/seo-audit

This repository holds Maya's SEO and GEO audit work. Each folder has its own rules; read them before working there.
For the Maya Audit tool, the full rules are in [`tools/maya-audit/AGENTS.md`](tools/maya-audit/AGENTS.md). Work on it
from inside `tools/maya-audit/`.

Rules that apply everywhere in this repository:

- **Never read, print, search inside, copy or commit `.env`**, credentials or authentication files. Never expose keys.
- **No paid calls and no live crawls in tests.** Firecrawl, DataForSEO and other paid providers, and real websites, are
  used only on the owner's explicit request in that session. Tests use fake servers and mock transports only.
- **Push only when the owner asks.** Never force-push, and never rewrite history that has been pushed.
- Never reset, clean, overwrite or automatically stash work. Never move or reuse a release tag.
