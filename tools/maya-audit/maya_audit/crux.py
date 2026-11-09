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


NO_DATA = ("Core Web Vitals not available: Google has too few real Chrome visits for this site to publish figures. "
           "That is common for small sites and says nothing about speed.")


def unavailable(reason: str = NO_KEY, code: str | None = None) -> dict[str, Any]:
    """DECISIONS 334: `reason` says why in a sentence; `reason_code` is "no_key", "no_data" (Google has no record),
    "error" (Google could not be reached or refused) or "time_limit"."""
    return {"source": SOURCE, "status": "not_available", "summary": reason, "metrics": [],
            "reason_code": code or ("no_key" if reason == NO_KEY else "error")}


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def _parse(record: dict) -> dict[str, Any] | None:
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
    core = [row for row in rows if row["rating"]]
    if not core:
        return None
    passed = all(row["rating"] == "good" for row in core) and len(core) == 3
    worst = [f"{row['label']} {row['shown']} ({row['rating']})" for row in core if row["rating"] != "good"]
    summary = ("Real visitors on phones: all three Core Web Vitals are good." if passed else
               "Real visitors on phones: " + ("; ".join(worst) if worst else "the metrics published are good, but not all three are published") + ".")
    return {"metrics": rows, "data_until": until, "passes_core_web_vitals": passed, "summary": summary}


def collect(url: str, key: str | None = None, *, transport: httpx.BaseTransport | None = None, clock=None,
            final_url: str | None = None, homepage: str | None = None) -> dict[str, Any]:
    """The site's Core Web Vitals, or why they are not available. Never raises; never shows the key.

    DECISIONS 334: Google keeps a record per origin, and a typed address that only redirects has none (enpara.com ->
    www.enpara.com: 404 for the first, data for the second). The origin the site lands on (`final_url`, the crawl's
    origin) is asked first, then the typed one; the first with a record is the site's figures. The homepage's own
    record (`homepage`, URL level) is asked too and kept apart (`homepage`). Every request is listed in `attempts`
    (origin or address, HTTP status), so a report says exactly what was asked."""
    key = key if key is not None else load_key()
    if not key:
        return unavailable()
    timeout = 20.0
    if clock is not None:
        blocked = clock.why_not(2.0)
        if blocked:
            return unavailable(f"Core Web Vitals not available: {blocked} before Google was asked.", "time_limit")
        timeout = clock.timeout(timeout)
    clean = lambda text: text.replace(key, REDACTED)  # noqa: E731
    origins = list(dict.fromkeys(o for o in (_origin(final_url), _origin(url)) if o))
    attempts: list[dict[str, Any]] = []
    found: dict[str, Any] | None = None
    error: str | None = None
    empty = False  # a record with none of the three core metrics

    def ask(http, body):
        try:
            # The key goes in a header, not the address (A26): an address ends up in logs and error messages.
            response = http.post(ENDPOINT, headers={"X-Goog-Api-Key": key}, json={**body, "formFactor": "PHONE"})
        except httpx.HTTPError as exc:
            return None, None, (f"Core Web Vitals not available: Google's Chrome UX Report could not be reached "
                                f"({type(exc).__name__}).")
        if response.status_code == 200:
            try:
                return 200, response.json()["record"], None
            except (ValueError, KeyError, TypeError):
                return 200, None, "Core Web Vitals not available: Google's answer could not be read."
        if response.status_code == 404:
            return 404, None, None
        try:
            detail = clean(str((response.json().get("error") or {}).get("message") or ""))[:200]
        except ValueError:
            detail = ""
        return response.status_code, None, (f"Core Web Vitals not available: Google's Chrome UX Report answered HTTP "
                                            f"{response.status_code}" + (f" ({detail})" if detail else "")
                                            + ". Check the API key and that the Chrome UX Report API is enabled for it.")

    with httpx.Client(timeout=timeout, trust_env=False, transport=transport or TRANSPORT) as http:
        for origin in origins:
            status, record, problem = ask(http, {"origin": origin})
            attempts.append({"origin": origin, "http_status": status})
            if problem:
                error = problem
                if status not in (None, 200):
                    break  # a refused key is the same for every origin
                continue
            parsed = _parse(record) if record is not None else None
            if parsed is not None:
                found = {"origin": origin, **parsed}
                break
            empty = empty or record is not None
        home = None
        if homepage and error is None:
            status, record, problem = ask(http, {"url": homepage})
            attempts.append({"url": homepage, "http_status": status})
            parsed = _parse(record) if record is not None else None
            home = {"url": homepage, "http_status": status, **({"status": "assessed", **parsed} if parsed else {"status": "not_available"})}
    stamp = {"fetched_at": utc_now(), "attempts": attempts, "origins_asked": origins}
    if found is not None:
        return {"source": SOURCE, "status": "assessed", "origin": found["origin"], "form_factor": "PHONE",
                "data_until": found["data_until"], "passes_core_web_vitals": found["passes_core_web_vitals"],
                "summary": found["summary"], "metrics": found["metrics"], "reason_code": None, **stamp,
                **({"homepage": home} if home else {})}
    if error and not any(a.get("http_status") == 404 for a in attempts):
        return {**unavailable(error, "error"), **stamp}
    if empty:
        return {**unavailable("Core Web Vitals not available: Google's answer held none of the three core metrics.", "no_data"),
                "origin": origins[0] if origins else None, **stamp}
    asked = " and ".join(origins)
    summary = NO_DATA.replace(" to publish figures.", f" to publish figures (asked for {asked}).") if origins else NO_DATA
    return {**unavailable(summary, "no_data"), "origin": origins[0] if origins else None, **stamp,
            **({"homepage": home} if home else {})}


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


# ---------------------------------------------------------------- a saved audit (DECISIONS 334)

SAVED_FILE = "crux.json"  # beside a saved report.json: Core Web Vitals fetched again; report.json is never written


def targets_of(report: dict) -> tuple[str, str | None, str | None]:
    """(typed address, the origin the site landed on, the homepage address) of a saved report, as `collect` takes them."""
    crawl = report.get("crawl") or {}
    start = crawl.get("start_url") or ""
    pages = [p for p in crawl.get("pages") or [] if isinstance(p, dict)]
    home = next((p.get("url") for p in pages if p.get("depth") == 0 and isinstance(p.get("status"), int)
                 and 200 <= p["status"] < 300), None)
    return start, crawl.get("origin") or None, home


def saved_beside(folder) -> dict[str, Any] | None:
    """The Core Web Vitals section fetched again for a saved audit (`<artifacts>/crux.json`), or None."""
    import json
    path = Path(folder) / SAVED_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("source") == SOURCE else None


def with_saved(report: dict, folder) -> dict:
    """`report` with the section fetched again, when there is one (a shallow copy; the saved file is not changed)."""
    again = saved_beside(folder)
    return {**report, "crux": again} if again else report


def refresh_saved(folder, key: str | None = None, *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Ask Google again for a saved audit's Core Web Vitals (site-level data is live anyway) and write the section to
    `<folder>/crux.json`. Free: one request per origin and one for the homepage. Never shows the key."""
    import json
    import os
    folder = Path(folder)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    start, final, home = targets_of(report)
    section = {**collect(start, key, transport=transport, final_url=final, homepage=home), "fetched_for_saved_audit": True}
    tmp = folder / (SAVED_FILE + ".part")
    tmp.write_text(json.dumps(section, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, folder / SAVED_FILE)
    return section
