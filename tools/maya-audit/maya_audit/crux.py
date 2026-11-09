"""Core Web Vitals from the Chrome UX Report (CrUX): what real Chrome visitors experienced over the last 28 days.

Optional and free. It needs a Google API key in MAYA_AUDIT_CRUX_API_KEY (environment or .env, read the same way as
the other keys); without one the report says "Core Web Vitals not available (no API key)". One request per audit,
about the site's origin, on phones. The key travels in the request's address, so the address is never printed,
logged or written to a report, and every error message is cleaned of it.

The request and response shapes were read from Google's public documentation on 2026-10-08; the API was not called
while this was written.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from .dataforseo.credentials import REDACTED, read_env_file
from .fetcher import utc_now

KEY_VAR = "MAYA_AUDIT_CRUX_API_KEY"
# DECISIONS 332: one Google API key serves the Chrome UX Report and PageSpeed Insights (the CLI's --pagespeed, PRF-3).
# A key set under the PageSpeed name is used for Core Web Vitals too, so one line in .env is enough.
GOOGLE_KEY_VAR = "MAYA_AUDIT_GOOGLE_API_KEY"
ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
NO_KEY = "Core Web Vitals not available (no API key)"
SOURCE = "Chrome UX Report (Google): real Chrome visitors on phones, the last 28 days, 75th percentile"
# Google's published thresholds: (good up to, poor above). Times in milliseconds.
THRESHOLDS = {"largest_contentful_paint": (2500, 4000), "interaction_to_next_paint": (200, 500), "cumulative_layout_shift": (0.1, 0.25)}
LABELS = {"largest_contentful_paint": "Largest Contentful Paint (LCP)", "interaction_to_next_paint": "Interaction to Next Paint (INP)",
          "cumulative_layout_shift": "Cumulative Layout Shift (CLS)", "first_contentful_paint": "First Contentful Paint",
          "experimental_time_to_first_byte": "Time to First Byte"}
# Tests replace this with a mock transport. Nothing else should.
TRANSPORT: httpx.BaseTransport | None = None


def load_key(environ: Mapping[str, str] | None = None) -> str | None:
    """The Chrome UX Report key: MAYA_AUDIT_CRUX_API_KEY, else MAYA_AUDIT_GOOGLE_API_KEY (DECISIONS 332), each from the
    environment first, then the .env file (MAYA_AUDIT_ENV_FILE). The value is never printed."""
    environ = os.environ if environ is None else environ
    saved = None
    for name in (KEY_VAR, GOOGLE_KEY_VAR):
        if environ.get(name):
            return environ[name]
        if saved is None:
            saved = read_env_file(Path(environ.get("MAYA_AUDIT_ENV_FILE") or ".env"))
        if saved.get(name):
            return saved[name]
    return None


def google_key(environ: Mapping[str, str] | None = None) -> str | None:
    """DECISIONS 332: the key for PageSpeed Insights (the CLI's --pagespeed): MAYA_AUDIT_GOOGLE_API_KEY, else
    MAYA_AUDIT_CRUX_API_KEY, from the environment or the .env file."""
    environ = os.environ if environ is None else environ
    saved = read_env_file(Path(environ.get("MAYA_AUDIT_ENV_FILE") or ".env"))
    for name in (GOOGLE_KEY_VAR, KEY_VAR):
        if environ.get(name) or saved.get(name):
            return environ.get(name) or saved.get(name)
    return None


def _rating(metric: str, value: float) -> str | None:
    if metric not in THRESHOLDS:
        return None
    good, poor = THRESHOLDS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs improvement"


def _show(metric: str, value: float) -> str:
    if metric == "cumulative_layout_shift":
        return f"{value:.2f}"
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


def unavailable(reason: str = NO_KEY) -> dict[str, Any]:
    return {"source": SOURCE, "status": "not_available", "summary": reason, "metrics": []}


def collect(url: str, key: str | None = None, *, transport: httpx.BaseTransport | None = None, clock=None) -> dict[str, Any]:
    """The origin's Core Web Vitals, or why they are not available. Never raises; never shows the key."""
    key = key if key is not None else load_key()
    if not key:
        return unavailable()
    timeout = 20.0
    if clock is not None:
        blocked = clock.why_not(2.0)
        if blocked:
            return unavailable(f"Core Web Vitals not available: {blocked} before Google was asked.")
        timeout = clock.timeout(timeout)
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    clean = lambda text: text.replace(key, REDACTED)  # noqa: E731
    try:
        with httpx.Client(timeout=timeout, trust_env=False, transport=transport or TRANSPORT) as http:
            # The key goes in a header, not the address (A26): an address ends up in logs and error messages.
            response = http.post(ENDPOINT, headers={"X-Goog-Api-Key": key}, json={"origin": origin, "formFactor": "PHONE"})
    except httpx.HTTPError as exc:
        return unavailable(f"Core Web Vitals not available: Google's Chrome UX Report could not be reached ({type(exc).__name__}).")
    if response.status_code == 404:
        return {**unavailable("Core Web Vitals not available: Google has too few real Chrome visits for this site to publish figures. "
                              "That is common for small sites and says nothing about speed."), "origin": origin, "fetched_at": utc_now()}
    if response.status_code != 200:
        try:
            detail = clean(str((response.json().get("error") or {}).get("message") or ""))[:200]
        except ValueError:
            detail = ""
        return unavailable(f"Core Web Vitals not available: Google's Chrome UX Report answered HTTP {response.status_code}"
                           + (f" ({detail})" if detail else "") + ". Check the API key and that the Chrome UX Report API is enabled for it.")
    try:
        record = response.json()["record"]
        rows = []
        for metric, label in LABELS.items():
            p75 = ((record.get("metrics") or {}).get(metric) or {}).get("percentiles", {}).get("p75")
            if p75 is None:
                continue
            value = float(p75)
            rows.append({"metric": metric, "label": label, "p75": value, "shown": _show(metric, value), "rating": _rating(metric, value)})
        period = record.get("collectionPeriod") or {}
        last = period.get("lastDate") or {}
        until = f"{last['year']:04d}-{last['month']:02d}-{last['day']:02d}" if {"year", "month", "day"} <= set(last) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return unavailable("Core Web Vitals not available: Google's answer could not be read.")
    core = [row for row in rows if row["rating"]]
    if not core:
        return {**unavailable("Core Web Vitals not available: Google's answer held none of the three core metrics."), "origin": origin}
    passed = all(row["rating"] == "good" for row in core) and len(core) == 3
    worst = [f"{row['label']} {row['shown']} ({row['rating']})" for row in core if row["rating"] != "good"]
    summary = ("Real visitors on phones: all three Core Web Vitals are good." if passed else
               "Real visitors on phones: " + ("; ".join(worst) if worst else "the metrics published are good, but not all three are published") + ".")
    return {"source": SOURCE, "status": "assessed", "origin": origin, "form_factor": "PHONE", "data_until": until,
            "fetched_at": utc_now(), "passes_core_web_vitals": passed, "summary": summary, "metrics": rows}


def lines(section: dict[str, Any]) -> list[str]:
    out = ["Core Web Vitals (real visitors)", section["summary"]]
    for row in section.get("metrics") or []:
        out.append(f"{row['label']}: {row['shown']}" + (f" ({row['rating']})" if row["rating"] else ""))
    if section.get("status") == "assessed":
        out.append(f"Source: {section['source']}; data up to {section.get('data_until') or 'not stated'}; fetched {section['fetched_at']}.")
    return out


def markdown(section: dict[str, Any]) -> str:
    body = lines(section)
    return "\n".join(["", "## Core Web Vitals (real visitors)", "", body[1], "", *(f"- {line}" for line in body[2:]), ""])
