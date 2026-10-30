"""AI user-agent registry (spec §4), stored as versioned data.

Every row records when and where it was checked. Rows with a non-empty
`launch_gate` must not ship unverified (spec §4 launch gate, §8 F6). Findings
that involve a gated row are labeled as such in reports.
"""

from __future__ import annotations

from dataclasses import dataclass

REGISTRY_VERSION = "2026-10-21"

ROLES = ("search", "live", "training")

UNVERIFIED_PROBE_UA = "probe user-agent string not verified against vendor docs"
# A search or live bot ACC-4 does not imitate: no user-agent string was checked for it (B14).
NOT_PROBED = "not tested by ACC-4: no user-agent string was checked to send as this bot"


@dataclass(frozen=True)
class BotEntry:
    token: str
    vendor: str
    engine: str
    role: str  # "search" | "live" | "training" (provisional when role is launch-gated)
    purpose: str
    honors_robots: str
    ip_ranges_url: str | None
    # Full UA string used by ACC-4 probes; None for robots-only tokens.
    probe_user_agent: str | None
    verified_on: str | None
    source: str
    launch_gate: tuple[str, ...] = ()

    @property
    def launch_gated(self) -> bool:
        return bool(self.launch_gate)

    def provenance(self) -> dict[str, str | None]:
        """Where each fact in this row comes from, field by field.

        Derived only from what the row already records (`source`, `verified_on`, `launch_gate`), so it
        can never claim more than the row does. A row is `verified` only when no launch-gate reason
        remains; press-sourced or provisional facts say so on the field they affect.
        """
        gate = set(self.launch_gate)
        press = PRESS_ONLY in gate
        base = "press coverage (not vendor documentation)" if press else (
            self.source if self.verified_on else "not checked")
        return {
            "identity_source": base,
            "role_source": "provisional: not verified against vendor docs" if ROLE_UNVERIFIED in gate else base,
            "robots_source": ("not checked" if "robots.txt behavior not checked" in gate else base),
            "ua_source": (None if self.probe_user_agent is None else
                          "unverified: probe user-agent string not checked against vendor docs"
                          if UNVERIFIED_PROBE_UA in gate else base),
            "ip_source": self.ip_ranges_url or "not checked (no published range file identified)",
            "verified_at": self.verified_on,
            "verification_status": "verified" if not gate else (
                "unverified" if self.verified_on is None else "partially verified"),
        }


OPENAI_DOCS = "https://developers.openai.com/api/docs/bots"
PERPLEXITY_DOCS = "https://docs.perplexity.ai/guides/bots"
GOOGLE_DOCS = "https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers"
# Read 2026-09-22: "Does Anthropic crawl data from the web, and how can site owners block the crawler?", last
# updated 2026-04-07 (support.anthropic.com/en/articles/8896518 redirects here). Names all three bots and their
# purposes, says all three honor robots.txt including Crawl-delay, and publishes one IP-range file shared by the
# three. It gives no full user-agent strings, so the probe strings below stay unverified.
ANTHROPIC_DOCS = "https://support.claude.com/en/articles/8896518"
ANTHROPIC_IPS = "https://claude.com/crawling/bots.json"
# The range file covers all three Anthropic bots: an IP match proves "an Anthropic crawler", not which one.
PRESS_ONLY = "sourced from press coverage, not Anthropic's own documentation"
ROLE_UNVERIFIED = "role not verified against vendor docs (provisional)"

REGISTRY: tuple[BotEntry, ...] = (
    BotEntry("OAI-SearchBot", "OpenAI", "ChatGPT search", "search",
             "Surfaces websites in ChatGPT search results", "yes", "https://openai.com/searchbot.json",
             "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
             "2026-09-13", OPENAI_DOCS, (UNVERIFIED_PROBE_UA,)),
    BotEntry("ChatGPT-User", "OpenAI", "ChatGPT (live fetch)", "live",
             "User-initiated fetches in ChatGPT and Custom GPTs", "robots.txt rules may not apply",
             "https://openai.com/chatgpt-user.json",
             "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
             "2026-09-13", OPENAI_DOCS, (UNVERIFIED_PROBE_UA,)),
    BotEntry("GPTBot", "OpenAI", "OpenAI model training", "training",
             "Content that may be used to train OpenAI foundation models", "yes", "https://openai.com/gptbot.json",
             None, "2026-09-13", OPENAI_DOCS),
    BotEntry("Claude-SearchBot", "Anthropic", "Claude search", "search",
             "Indexes content to improve search result quality", "yes, including Crawl-delay (Anthropic docs)",
             ANTHROPIC_IPS, "Mozilla/5.0 (compatible; Claude-SearchBot/1.0; +https://www.anthropic.com)",
             "2026-09-22", ANTHROPIC_DOCS, (UNVERIFIED_PROBE_UA,)),
    BotEntry("Claude-User", "Anthropic", "Claude (live fetch)", "live",
             "Retrieves content when a user directs Claude to access a website",
             "yes, including Crawl-delay (Anthropic docs)", ANTHROPIC_IPS,
             "Mozilla/5.0 (compatible; Claude-User/1.0; +https://www.anthropic.com)",
             "2026-09-22", ANTHROPIC_DOCS, (UNVERIFIED_PROBE_UA,)),
    BotEntry("ClaudeBot", "Anthropic", "Anthropic model training", "training",
             "Collects web content for AI model training and development",
             "yes, including Crawl-delay (Anthropic docs)", ANTHROPIC_IPS,
             None, "2026-09-22", ANTHROPIC_DOCS),
    BotEntry("PerplexityBot", "Perplexity", "Perplexity search", "search",
             "Surfaces and links websites in Perplexity search; not used for foundation-model training", "yes",
             "https://www.perplexity.com/perplexitybot.json",
             "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
             "2026-09-13", PERPLEXITY_DOCS),
    BotEntry("Perplexity-User", "Perplexity", "Perplexity (live fetch)", "live",
             "User-initiated fetches during answers", "no: generally ignores robots.txt",
             "https://www.perplexity.com/perplexity-user.json",
             "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
             "2026-09-13", PERPLEXITY_DOCS),
    BotEntry("Googlebot", "Google", "Google AI Overviews / AI Mode", "search",
             "AI Overviews and AI Mode use the regular Search index", "yes", None,
             "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
             "2026-09-13", GOOGLE_DOCS, (UNVERIFIED_PROBE_UA,)),
    BotEntry("Google-Extended", "Google", "Gemini apps / Vertex AI grounding and training", "training",
             "robots.txt token only; does not affect Google Search or AI Overviews", "yes (token)", None,
             None, "2026-09-13", GOOGLE_DOCS),
    BotEntry("Bingbot", "Microsoft", "Microsoft Copilot (Bing index)", "search",
             "Bing index grounds Copilot", "yes", None,
             "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
             None, "not re-verified in this session", (UNVERIFIED_PROBE_UA,)),
    BotEntry("Applebot", "Apple", "Siri / Spotlight search", "search",
             "Apple search features", "not checked", None,
             "Mozilla/5.0 (compatible; Applebot/0.1; +http://www.apple.com/go/applebot)",
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked", UNVERIFIED_PROBE_UA)),
    BotEntry("Applebot-Extended", "Apple", "Apple model training (opt-out token)", "training",
             "Training opt-out token", "not checked", None, None,
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked")),
    BotEntry("meta-externalagent", "Meta", "Meta AI", "training",
             "AI training / product features", "not checked", None, None,
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked")),
    BotEntry("CCBot", "Common Crawl", "Common Crawl corpus (used in model training)", "training",
             "Open web corpus widely used in model training", "yes", None, None,
             None, "not checked", ("IP ranges not checked",)),
    BotEntry("Amazonbot", "Amazon", "Alexa / Amazon AI features", "search",
             "Alexa / AI features", "not checked", None,
             "Mozilla/5.0 (compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)",
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked", UNVERIFIED_PROBE_UA)),
    BotEntry("DuckAssistBot", "DuckDuckGo", "DuckAssist answers", "live",
             "DuckAssist answers", "not checked", None,
             "DuckAssistBot/1.0; (+http://duckduckgo.com/duckassistbot.html)",
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked", UNVERIFIED_PROBE_UA)),
    BotEntry("MistralAI-User", "Mistral", "Le Chat (live fetch)", "live",
             "Le Chat user-initiated fetches", "not checked", None,
             "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)",
             None, "not checked", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked", UNVERIFIED_PROBE_UA)),
    # Added 2026-10-21 (review B14), from the vendors' crawler pages as the review cites them; not re-read in this session,
    # so every row is launch-gated. No probe string: ACC-4 sends no request as these bots.
    BotEntry("Bytespider", "ByteDance", "ByteDance model training", "training",
             "Collects web content for ByteDance's AI models", "not checked", None, None,
             None, "not re-verified in this session", (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked")),
    BotEntry("GoogleOther", "Google", "Google product teams' research crawls", "training",
             "Generic Google crawler for one-off research and development fetches; not Google Search", "yes", None, None,
             None, GOOGLE_DOCS + " (not re-verified in this session)", (ROLE_UNVERIFIED,)),
    BotEntry("Google-CloudVertexBot", "Google", "Vertex AI Agents (site owner's request)", "training",
             "Crawls a site when its owner builds a Vertex AI Agent on it; not Google Search", "yes", None, None,
             None, GOOGLE_DOCS + " (not re-verified in this session)", (ROLE_UNVERIFIED,)),
    BotEntry("Meta-ExternalFetcher", "Meta", "Meta AI (live fetch)", "live",
             "User-initiated fetches of a link in Meta AI", "robots.txt rules may not apply", None, None,
             None, "not re-verified in this session",
             (ROLE_UNVERIFIED, "robots.txt behavior not checked", "IP ranges not checked", NOT_PROBED)),
)

# User-agent tokens that once mattered and no longer do (B14): robots.txt rules naming them have no effect. Anthropic
# documents ClaudeBot, Claude-SearchBot and Claude-User as its bots; anthropic-ai and Claude-Web are no longer used.
RETIRED_TOKENS = {
    "anthropic-ai": "Anthropic no longer uses it; ClaudeBot (training), Claude-SearchBot and Claude-User are the tokens now",
    "claude-web": "Anthropic no longer uses it; ClaudeBot (training), Claude-SearchBot and Claude-User are the tokens now",
}

BY_TOKEN = {entry.token.lower(): entry for entry in REGISTRY}

# ACC-6: per-vendor training / search / live tokens.
VENDOR_SCOPES = (
    ("OpenAI", "GPTBot", "OAI-SearchBot", "ChatGPT-User"),
    ("Anthropic", "ClaudeBot", "Claude-SearchBot", "Claude-User"),
    ("Google", "Google-Extended", "Googlebot", None),
    ("Apple", "Applebot-Extended", "Applebot", None),
    ("Perplexity", None, "PerplexityBot", "Perplexity-User"),
    ("Common Crawl", "CCBot", None, None),
)


def entry(token: str) -> BotEntry:
    return BY_TOKEN[token.lower()]


def by_role(role: str) -> list[BotEntry]:
    return [e for e in REGISTRY if e.role == role]
