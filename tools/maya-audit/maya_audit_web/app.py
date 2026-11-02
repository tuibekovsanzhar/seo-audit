"""The local JSON API, version 1 (docs/WEB-API.md), and the page that uses it.

Handlers validate, call a service, and shape the answer. They decide nothing about a website: crawling,
checks, severity, confidence and spending are the engine's, reached through `runner` and `paid`, and
everything shown about a finished audit is read from its saved report through `summary`.
"""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
import re
import secrets
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Iterator
from urllib.parse import urlsplit

from fastapi import Depends, APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import client_reports
from . import API_VERSION, chat, comparison, demo, fc, followups, paid, pdf, practical, snapshot, summary, wording
from .runner import (AFFECTED_JSON, MAX_KEY_PAGES, MAX_QUEUED, MODES, REPORT_JSON, REPORT_MD, STEPS, Engine, Runner,
                     crawl_config, is_active, pages_saved, plan_shape, CRAWL_DB)
from .security import Guard, error_body, loopback_hosts
from maya_audit import archives, crux, final, ownership, release_gate
from maya_audit import brand as brand_module
from maya_audit.dataforseo import insights
from maya_audit.dataforseo import panel as dfs_panel
from maya_audit.firecrawl import settings as firecrawl_settings
from maya_audit.urls import clean_hostname, registrable_domain

from .store import ACTIVE, RESUMABLE, Store, is_id, is_past, new_id, now
from .strings import DEFAULT_LANGUAGE, LANGUAGE_NAMES, LANGUAGE_NOTES, STRINGS, current_language, set_language, t, usd
from . import strings as strings_module

STATIC = Path(__file__).resolve().parent / "static"
# A first guess at the country from the address, for the plan card. Only a suggestion; the person edits it.
COUNTRY_BY_TLD = {"tr": "Türkiye", "de": "Germany", "uk": "United Kingdom", "fr": "France", "es": "Spain", "it": "Italy",
                  "nl": "Netherlands", "us": "United States", "ca": "Canada", "au": "Australia", "ae": "United Arab Emirates"}
# The same guess from the homepage's own `html lang`, as the last saved audit of the site read it. A bare "en" or "ar"
# names no country, and a tag with a region this table does not hold suggests nothing.
COUNTRY_BY_LANGUAGE = {"tr": "Türkiye", "tr-tr": "Türkiye", "de": "Germany", "de-de": "Germany", "fr": "France", "fr-fr": "France",
                       "es": "Spain", "es-es": "Spain", "it": "Italy", "it-it": "Italy", "nl": "Netherlands", "nl-nl": "Netherlands",
                       "en-gb": "United Kingdom", "en-us": "United States", "en-ca": "Canada", "en-au": "Australia", "ar-ae": "United Arab Emirates"}
PLAN_LIFETIME_S = 30 * 60
STALE_AFTER_S = 20
DOWNLOAD_NAMES = {"json": ("json", "application/json"), "markdown": ("md", "text/markdown; charset=utf-8"),
                  "pdf": ("pdf", "application/pdf"), "evidence": ("zip", "application/zip")}
_PROJECT_ID = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# A plan made before Firecrawl existed has no such section: it asked for none.
LANGUAGE_COOKIE = "maya_language"
NO_FIRECRAWL = {"requested": False, "needs_confirmation": False, "blocked": None, "max_credits": 0, "max_usd": None, "options": {}}


# Other domains of one brand (IDX-6): at most this many, each a plain host name.
MAX_BRAND_FAMILY_DOMAINS = 20


def brand_family(values: list[str] | None) -> list[str]:
    """The brand-family domains as typed, cleaned: host names only, lower-cased, each once. Anything else (an address
    with a scheme or a path, markup, spaces) is refused with the app's usual error, never repaired or stored."""
    out: list[str] = []
    for value in values or []:
        if not value.strip():
            continue
        host = clean_hostname(value)
        if host is None:
            raise ApiError(422, "invalid_brand_family_domains", t("plan.brand_family.bad", value=value.strip()[:80]))
        if host not in out:
            out.append(host)
    if len(out) > MAX_BRAND_FAMILY_DOMAINS:
        raise ApiError(422, "invalid_brand_family_domains", t("plan.brand_family.too_many", limit=MAX_BRAND_FAMILY_DOMAINS))
    return out


class ClientSummaryIn(Strict):
    revision: int = Field(ge=1)
    one_read: str = Field(max_length=6000)
    bullets: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=4)


class ClientCardIn(Strict):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    explanation: str = Field(max_length=6000)
    steps: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=5)
    proposed_text: str = Field(default="", max_length=6000)
    proposed_code: str = Field(default="", max_length=6000)
    decision: str = Field(default="", max_length=2000)
    owner: str = Field(min_length=1, max_length=120)
    effort: str = Field(pattern="^(Küçük|Orta|Büyük)$")
    verify: str = Field(max_length=3000)
    references: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list, max_length=30)


class ClientNoticeIn(Strict):
    what: str = Field(min_length=1, max_length=500)
    why: str = Field(max_length=3000)
    how_to_enable: str = Field(max_length=2000)


class ClientComparisonTitleIn(Strict):
    group: str = Field(pattern="^(fixed|new|still_open|unknown)$")
    index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=500)


class ClientNotesIn(Strict):
    revision: int = Field(ge=1)
    not_measured: list[ClientNoticeIn] = Field(max_length=100)
    comparison_titles: list[ClientComparisonTitleIn] = Field(default_factory=list, max_length=2000)


class ClientReviewIn(Strict):
    revision: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)


class PlanIn(Strict):
    url: str = Field(min_length=1, max_length=2048, description="The website to audit. A bare domain is read as https.")
    mode: str = Field(default="quick", pattern="^(single|quick|standard)$",
                      description="single: only the address given, no links followed. quick: up to 50 pages. standard: up to 500.")
    backlinks: bool = Field(default=False, description="Ask DataForSEO for backlink figures (paid, off by default).")
    search_data: bool = Field(default=False, description="Ask DataForSEO for the search data panels: domain overview, ranked keywords, quick wins, competitors, AI mentions, Lighthouse (paid, off by default).")
    local_business: bool = Field(default=False, description="With search_data: also look up the Google Business Profile under the plan's brand name.")
    verify_ownership: bool = Field(default=False, description="Look for the site's ownership token (meta tag on the homepage, or DNS TXT record). When found, ACC-4 tests what named AI and search crawlers receive.")
    archives: bool = Field(default=False, description="If the site cannot be read at all, read archived copies (Wayback Machine, Common Crawl; free).")
    key_pages: list[str] = Field(default_factory=list, max_length=50, description="Important pages, as paths or full addresses on the same site.")
    brand_name: str | None = Field(default=None, max_length=120, description="The brand name typed on the plan card. Left out: the saved one, else a suggestion from the address. A value equal to that suggestion is not a confirmed brand.")
    country: str | None = Field(default=None, max_length=80, description="The country typed on the plan card: the market of the search data. Left out: the saved one, else a suggestion shown on the card.")
    brand_family_domains: list[Annotated[str, Field(max_length=253)]] | None = Field(default=None, max_length=MAX_BRAND_FAMILY_DOMAINS, description="Other domains of the same brand, as plain host names (other-shop.example). A link to one of them is not reported as a link to another site and is never requested. Left out: the saved ones.")
    market_default_accepted: bool = Field(default=False, description="With search_data and a country that is not recognised: use United States figures.")
    fast_check: bool = Field(default=False, description="Fast check: render 6 pages instead of 20 and check 50 sitemap addresses, 20 llms.txt links and 10 images instead of 200, 50 and 30 (and at most 30 requests to other sites). Pages read, the page reader and paid data are unchanged. Off by default.")
    external_links: bool = Field(default=True, description="Check links to other sites (one light request each, within a cap). On by default; false runs the audit with --no-external-links.")
    firecrawl: bool | None = Field(default=None, description="Read the pages through Firecrawl (paid in credits). Left out: on when a Firecrawl key is set on this computer. false: Maya's own crawler reads the pages.")
    firecrawl_render: bool = Field(default=False, description="Also render through Firecrawl when the local browser cannot start.")
    firecrawl_max_pages: int | None = Field(default=None, ge=1, le=500, description="The most pages Firecrawl may read for this audit. Left out: the plan's own page cap (at most 500).")
    firecrawl_proxy: str = Field(default="basic", pattern="^(basic|enhanced|auto)$", description="basic unless the site owner approved more.")
    firecrawl_owner_approved: bool = Field(default=False, description="The site owner has approved bypassing bot protection.")


# The largest amount a confirmation may name at all: the largest value any spending limit can be set to
# (maya_audit.dataforseo.pricing._limit). It only keeps nonsense out; the amount must still equal the plan's total, and
# the limits themselves (confirmation, per audit, per day) are enforced where money is reserved. It was 2, the daily
# limit of the first web app, which no plan that needs a confirmation today could pass.
MAX_CONFIRMABLE_USD = 10_000


class ConfirmIn(Strict):
    approved_max_usd: float | None = Field(default=None, ge=0, le=MAX_CONFIRMABLE_USD, description="The plan's exact maximum DataForSEO cost, as shown to the person.")
    approved_max_credits: float | None = Field(default=None, ge=0, le=5000, description="The plan's exact maximum in Firecrawl credits, as shown.")

    @model_validator(mode="after")
    def _something_is_approved(self) -> "ConfirmIn":
        if self.approved_max_usd is None and self.approved_max_credits is None:
            raise ValueError("a confirmation names the maximum it approves")
        return self


class AuditIn(Strict):
    plan_id: str = Field(min_length=32, max_length=32)
    message: str | None = Field(default=None, max_length=4000, description="What the person typed, kept as the first message.")
    balance_choice: str | None = Field(default=None, pattern="^(without_search_data|run_anyway)$",
                                       description="The answer to the plan's balance warning: run without the paid data, or run anyway (not offered at a balance of zero).")


class ResumeIn(Strict):
    approved_max_usd: float | None = Field(default=None, ge=0, le=MAX_CONFIRMABLE_USD)
    approved_max_credits: float | None = Field(default=None, ge=0, le=5000)


class WithoutRetentionIn(Strict):
    accept_content_may_be_stored: bool = Field(description="Must be true: client page content may be stored by Firecrawl.")
    approved_max_credits: float = Field(ge=0, le=5000, description="The exact maximum in Firecrawl credits, as shown.")


class FirecrawlReadIn(Strict):
    proxy: str = Field(default="basic", pattern="^(basic|enhanced|auto)$", description="One of the proxies the result card offers.")
    owner_approved_bypass: bool = Field(default=False, description="The site owner has approved bypassing bot protection. Needed for a stronger proxy.")
    accept_content_may_be_stored: bool = Field(default=False, description="Needed when zero data retention is not applied: page content may be stored by Firecrawl.")
    approved_max_credits: float = Field(ge=0, le=5000, description="The exact maximum in Firecrawl credits, as shown.")


class LanguageIn(Strict):
    language: str = Field(min_length=2, max_length=10, pattern="^[a-z-]+$")


class MessageIn(Strict):
    text: str = Field(min_length=1, max_length=4000)


class ProfileIn(Strict):
    brand_name: str = Field(default="", max_length=120)
    brand_aliases: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(default=None, max_length=30)
    related_organizations: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(default=None, max_length=30)
    industry: str = Field(default="", max_length=120)
    goals: list[str] = Field(default_factory=list, max_length=10)
    countries: list[str] = Field(default_factory=list, max_length=30)
    languages: list[str] = Field(default_factory=list, max_length=30)
    key_pages: list[str] = Field(default_factory=list, max_length=50)
    # Left out: what is saved stays. An empty list clears it.
    brand_family_domains: list[Annotated[str, Field(max_length=253)]] | None = Field(default=None, max_length=MAX_BRAND_FAMILY_DOMAINS)


def _without_local_folder(index_path: Path) -> str:
    """An evidence index as it goes into the download zip: its "folder" is the folder's own name, never the absolute
    path on this computer (which names the person's user account). Older saved indexes hold the full path (D-07)."""
    text = index_path.read_text(encoding="utf-8")
    try:
        index = json.loads(text)
    except ValueError:
        return text
    if isinstance(index, dict) and isinstance(index.get("folder"), str):
        index["folder"] = re.split(r"[\\/]", index["folder"].rstrip("\\/"))[-1]
        return json.dumps(index, ensure_ascii=False, indent=2)
    return text


LOG_FILE = "maya-audit-web.log"


def _remove_tree(folder: Path) -> int:
    """Remove a folder and everything in it; the number of files that could not be removed (0 when all went). Walked
    by hand rather than `shutil.rmtree(ignore_errors=True)`, which hides what it could not delete."""
    if not folder.exists():
        return 0
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            path.rmdir() if path.is_dir() and not path.is_symlink() else path.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
    return sum(1 for path in folder.rglob("*") if not path.is_dir()) if folder.exists() else 0


def _server_log(folder: Path) -> logging.Handler:
    """A rotating log file under the web home (`<folder>/logs/`): what failed, with its traceback, kept on this computer
    for whoever has to find out why (D-13). The person on the page still sees only the error's class name. The file
    is opened on the first record (`delay`), so an app that never fails leaves nothing open to lock on Windows."""
    target = (Path(folder) / "logs" / LOG_FILE).resolve()
    logger = logging.getLogger("maya_audit_web")
    for handler in logger.handlers:
        if getattr(handler, "baseFilename", None) == str(target):
            return handler
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler


def _sse(event_id: int, name: str, data: dict[str, Any]) -> str:
    return f"id: {event_id}\nevent: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(folder: Path | str, *, engine: Engine | None = None, port: int = 8770,
               allowed_hosts: frozenset[str] | None = None, heartbeat_s: float = 10.0, analysis_folder: Path | None = None) -> FastAPI:
    """The app for one data folder. `engine` decides where audits and paid calls go (real, demo or test)."""
    from .analyses import Registry
    analysis_registry = Registry(analysis_folder)
    engine = engine or Engine()
    store = Store(folder)
    server_log = _server_log(store.folder)
    try:
        runner = Runner(store, engine)
    except Exception:
        store.close()
        raise
    guard = Guard(allowed_hosts or loopback_hosts(port))
    assistant: followups.AssistantProvider = followups.DeterministicAssistant()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        runner.shutdown()  # the running audit stops politely and stays resumable
        store.close()
        logging.getLogger("maya_audit_web").removeHandler(server_log)
        server_log.close()

    app = FastAPI(title="Maya Audit local API", version=API_VERSION, docs_url=None, redoc_url=None,
                  openapi_url="/api/v1/openapi.json", lifespan=lifespan,
                  description="Local, single-user API around the Maya Audit engine. See docs/WEB-API.md.")
    app.state.store, app.state.runner, app.state.guard, app.state.engine = store, runner, guard, engine
    app.state.analyses = analysis_registry
    app.middleware("http")(guard.middleware)

    @app.middleware("http")
    async def language(request: Request, call_next) -> Response:
        # The person's choice travels in a plain cookie; it selects sentences and nothing else.
        set_language(request.cookies.get(LANGUAGE_COOKIE))
        response = await call_next(request)
        parts = request.url.path.split('/')
        if len(parts) > 5 and parts[3] == 'audits' and analysis_registry.accepts(parts[4]):
            audit = analysis_registry.get(parts[4])
            if response.status_code < 400 and audit:
                meta = audit['analysis']
                response.headers.update({'X-Maya-Analysis-ID': meta['id'], 'X-Maya-Source-Audit-ID': meta['source_audit_id'],
                    'X-Maya-Report-SHA256': meta['report_sha256'], 'X-Maya-Exported-At': now()})
        return response
    async def analysis_permissions(request: Request):
        parts = request.url.path.split('/')
        if len(parts) > 4 and parts[3] == 'audits' and analysis_registry.accepts(parts[4]):
            if request.method not in ('GET', 'HEAD') and parts[5:6] != ['client-report']:
                raise ApiError(409, 'analysis_read_only', t('analysis.read_only'))
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(analysis_permissions)])

    # -- errors: one shape, no raw exception text, no file paths -----------------------------------

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"field": ".".join(str(part) for part in err["loc"] if part != "body"), "problem": err["msg"]}
                  for err in exc.errors()[:10]]
        return JSONResponse(error_body("invalid_request", t("error.invalid_request"), {"fields": fields}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "request_failed")
        return JSONResponse(error_body(code, t(f"error.{code}")), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("maya_audit_web").error("%s %s failed", request.method, request.url.path, exc_info=exc)
        return JSONResponse(error_body("internal_error", t("error.internal"), {"kind": type(exc).__name__}), status_code=500)

    # -- lookups ---------------------------------------------------------------------------------

    def need_audit(audit_id: str) -> dict[str, Any]:
        audit = analysis_registry.get(audit_id) or (store.audit(audit_id) if is_id(audit_id) else None)
        if audit is None:
            raise ApiError(404, "audit_not_found", t("error.audit_not_found"))
        return audit

    def need_plan(plan_id: str) -> dict[str, Any]:
        plan = store.plan(plan_id) if is_id(plan_id) else None
        if plan is None:
            raise ApiError(404, "plan_not_found", t("error.plan_not_found"))
        return plan

    def artifact_folder(audit_id: str) -> Path:
        if analysis_registry.accepts(audit_id):
            if analysis_registry.get(audit_id) is None:
                raise ApiError(404, 'audit_not_found', t('error.audit_not_found'))
            return analysis_registry.artifacts(audit_id)
        return runner.artifacts(audit_id)

    def report_path(audit_id: str) -> Path:
        return artifact_folder(audit_id) / REPORT_JSON

    def load_report(audit: dict[str, Any]) -> dict[str, Any]:
        path = report_path(audit["id"])
        if not path.is_file():
            raise ApiError(409, "report_not_ready", t("chat.no_report"))
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            summary.check_readable(report)
        except summary.UnreadableReport as exc:
            raise ApiError(409, "report_version_unsupported", t("error.report_version", reason=str(exc))) from None
        except ValueError:
            raise ApiError(409, "report_unreadable", t("error.report_unreadable")) from None
        return report

    def affected(audit_id: str) -> dict[str, list[str]]:
        path = artifact_folder(audit_id) / AFFECTED_JSON
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except ValueError:
            return {}

    def project_of(url: str) -> str:
        return (urlsplit(url).hostname or "").removeprefix("www.")

    def profile_of(project_id: str) -> dict[str, Any]:
        row = store.profile(project_id)
        return {"project_id": project_id, "confirmed": row is not None, "updated_at": row["updated_at"] if row else None,
                **{"brand_name": "", "industry": "", "goals": [], "countries": [], "languages": [], "key_pages": [],
                   "brand_family_domains": []},
                **(row["profile"] if row else {})}

    # -- plans -----------------------------------------------------------------------------------

    def target(address: str) -> tuple[str, str | None, bool]:
        """(the URL to audit, an http:// fallback or None, whether the person typed http://)."""
        found = chat.find_address(address) or address
        try:
            url, plain = chat.https_first(found, allow_loopback=engine.allow_loopback)
        except chat.BadTarget as exc:
            raise ApiError(422, "private_address" if exc.key == "chat.private_url" else "invalid_url", t(exc.key)) from None
        if engine.demo and not demo.is_demo_site(url):
            raise ApiError(422, "demo_sites_only", t("chat.demo_only", sites=", ".join(demo.SITES)))
        return url, plain, bool(re.match(r"^http://", found.strip(), re.IGNORECASE)) and url.startswith("https://")

    def homepage_language(project_id: str) -> str | None:
        """The `html lang` of the homepage in the last saved report of this site. Reads a file on this computer; no
        page is fetched. Remembered per audit, so a large report is opened once."""
        last = store.latest_reported(project_id)
        if last is None:
            return None
        key = f"homepage_language:{last['id']}"
        held = store.get_meta(key)
        if held is not None:
            return held.get("lang")
        lang = None
        try:
            pages = json.loads(report_path(last["id"]).read_text(encoding="utf-8"))["crawl"]["pages"]
            home = next((page for page in pages if page.get("depth") == 0 and 200 <= (page.get("status") or 0) < 300 and page.get("analysis")), None)
            lang = (home["analysis"].get("html_lang") or None) if home else None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        store.set_meta(key, {"lang": lang if isinstance(lang, str) else None})
        return lang if isinstance(lang, str) else None

    def suggested_country(project_id: str) -> tuple[str, str] | None:
        """(country, where the guess comes from): the last audit's homepage language, else the address ending."""
        lang = (homepage_language(project_id) or "").strip().lower().replace("_", "-")
        if lang in COUNTRY_BY_LANGUAGE:
            return COUNTRY_BY_LANGUAGE[lang], t("plan.market.source.language", lang=lang)
        ending = project_id.rsplit(".", 1)[-1]
        if ending in COUNTRY_BY_TLD:
            return COUNTRY_BY_TLD[ending], t("plan.market.source.address", ending=ending)
        return None

    def address_guess(project_id: str) -> str:
        """The brand suggested from the address: its label split at "-" and "_", each piece capitalised."""
        label = registrable_domain(project_id).split(".")[0]
        return " ".join(word.capitalize() for word in re.split(r"[-_]+", label) if word)

    def business(project_id: str, brand: str | None = None, country: str | None = None) -> dict[str, Any]:
        """Brand name and country for the plan card: what was typed on the card, else what was confirmed before, else
        a suggestion to edit. A suggestion is always named as one on the card (`suggested_from`)."""
        saved = profile_of(project_id)
        guess = address_guess(project_id)
        # The suggestion from the address, posted back or saved unchanged, is not a confirmed brand (DECISIONS 220): a
        # saved value equal to it is no value, and a posted one is shown but not used.
        saved_brand = "" if brand_module.same_name(saved["brand_name"], guess) else saved["brand_name"]
        posted = brand.strip() if brand is not None else None
        suggestion = None if country is not None or saved["countries"] else suggested_country(project_id)
        chosen = country.strip() if country is not None else (saved["countries"] or [suggestion[0] if suggestion else ""])[0]
        return {"brand_name": posted if posted is not None else saved_brand or guess, "country": chosen,
                "brand_confirmed": (bool(posted) and not brand_module.same_name(posted, guess)) if posted is not None else bool(saved_brand),
                "country_confirmed": country is not None or bool(saved["countries"]),
                "suggested_from": suggestion[1] if suggestion else None,
                "note": t("plan.business.confirmed") if saved_brand else t("plan.business.suggested")}

    def place_name(code: int, fallback: str) -> str:
        key = f"market.place.{code}"
        return t(key) if strings_module.has(key) else fallback

    def market_view(options: dict[str, Any], who: dict[str, Any]) -> dict[str, Any]:
        """The market of each paid panel, as lines for the plan card, and whether search data may run at all."""
        code, language, place, known = insights.location_for(options["country"])
        accepted = bool(options.get("market_default_accepted")) and not known
        unknown = options["search_data"] and not known and not accepted
        lines = []
        if options["search_data"] and not unknown:
            lines.append({"kind": "search", "text": t("plan.market.search", place=place_name(code, place), language=strings_module.language_name(language))})
        if options["search_data"]:
            lines.append({"kind": "chatgpt", "text": t("plan.market.chatgpt")})
        if options["backlinks"]:
            lines.append({"kind": "backlinks", "text": t("plan.market.backlinks")})
        if who.get("suggested_from") and known:
            lines.append({"kind": "suggestion", "text": t("plan.market.suggested", source=who["suggested_from"], place=place_name(code, place))})
        named = (options["country"] or "").strip()
        return {"market": place, "market_known": known, "market_code": code, "market_language": language,
                "market_default_accepted": accepted, "market_unknown": unknown, "markets": lines,
                "market_block": None if not unknown else {"code": "market_unknown", "message": t("plan.market.unknown", country=named) if named else t("plan.market.none")},
                "market_default_label": t("plan.market.accept_default")}

    def ownership_of(project_id: str) -> dict[str, Any]:
        """The site's verification token and the two ways to publish it. The token is the same for a site on this computer."""
        secret = store.get_meta("ownership_secret")
        if not secret:
            secret = secrets.token_hex(24)
            store.set_meta("ownership_secret", secret)
        domain = registrable_domain(project_id)
        token = ownership.token_for(domain, secret)
        steps = ownership.instructions(domain, token)
        return {"domain": domain, "token": token, "meta_tag": ownership.meta_tag(token), "txt_record": ownership.txt_record(token),
                "instructions": steps, "instructions_shown": [wording.line(step)[0] for step in steps]}

    def plan_document(url: str, mode: str, key_pages: list[str], backlinks: bool, plain: str | None = None,
                      typed_http: bool = False, firecrawl: dict[str, Any] | None = None,
                      extras: dict[str, Any] | None = None, brand: str | None = None,
                      country: str | None = None, family: list[str] | None = None) -> tuple[dict[str, Any], str, float]:
        extras = extras or {}
        # The plan's two switches (DECISIONS 219): they change the caps, so the estimate and the fingerprint.
        switches = {"fast_check": bool(extras.get("fast_check")), "external_links": extras.get("external_links", True) is not False}
        shape = plan_shape(engine, mode, key_pages, switches)
        # Other domains of the same brand: what was typed on the card, else what is saved for this site.
        family = family if family is not None else brand_family(profile_of(project_of(url)).get("brand_family_domains"))
        who = business(project_of(url), brand, country)
        options = {"backlinks": backlinks, "search_data": bool(extras.get("search_data")), "local_business": bool(extras.get("local_business")),
                   # Only a name the person typed or saved: a suggestion from the address is shown on the card, never used
                   # (DECISIONS 201). Without it the report reads the site's own name, and the Business Profile is not looked up.
                   "brand": (who["brand_name"] or None) if who["brand_confirmed"] else None, "country": who["country"], "key_pages": key_pages,
                   # The person's tick: an unrecognised country may run on United States figures. Kept only when it applies.
                   "market_default_accepted": bool(extras.get("market_default_accepted")) and bool(extras.get("search_data"))
                   and not insights.location_for(who["country"])[3]}
        paid_wanted = backlinks or options["search_data"]
        market = market_view(options, who)
        # The account's balance, asked for by itself (one free request) when paid data is on the plan and the last answer
        # is older than ten minutes: a plan can then warn before anything is spent for a report without that data.
        fetched = paid.balance_for_plan(engine.paid, store.get_meta("provider_balance"), store.get_meta("provider_balance_failed"),
                                        paid_wanted=paid_wanted, demo=engine.demo)
        if fetched is not None:
            store.set_meta("provider_balance" if fetched["known"] else "provider_balance_failed", fetched)
        ordinary = insights.common_word_brand(who["brand_name"], project_of(url))
        # With nothing paid asked for, the backlink price is still shown, so it is known before it is chosen.
        cost = paid.price(url, engine.paid, requested=paid_wanted, options=options if paid_wanted else None)
        cap = shape["page_cap"]
        reader = fc.plan(engine.firecrawl, firecrawl, cap, shape["rendering_enabled"])
        fingerprint = paid.fingerprint(url, mode, key_pages, paid_wanted, cost["calls"], cost["total_usd"], reader,
                                       {"search_data": options["search_data"], "local_business": options["local_business"],
                                        "archives": bool(extras.get("archives")), "verify_ownership": bool(extras.get("verify_ownership")),
                                        "brand_family_domains": sorted(family), **switch_basis(switches)},
                                       market_basis(options) if paid_wanted else None)
        duration = ({"known": False, "label": t("plan.duration.demo")} if engine.demo else
                    {"known": True, "up_to_minutes": shape["up_to_minutes"],
                     "label": t("plan.duration", minutes=shape["up_to_minutes"], cap=cap)})
        balance = store.get_meta("provider_balance")
        document = {
            "id": new_id(), "fingerprint": fingerprint,
            "target": {"url": url, "host": urlsplit(url).hostname, "domain": project_of(url), "http_fallback": plain,
                       "note": t("plan.https_first.typed_http") if typed_http else t("plan.https_first") if plain else None},
            "business": who,
            "project_id": project_of(url), "mode": mode, "mode_label": t(f"plan.mode.{mode}"), "page_cap": cap,
            # A single-page audit: the scope line says the one page and, when Firecrawl reads it, about how many credits.
            "single_page": mode == "single",
            "scope_label": (None if mode != "single" else
                            t("plan.scope.single.credits", credits=reader["max_credits"]) if reader and reader.get("main_reader") and reader.get("max_credits")
                            else t("plan.scope.single")),
            "key_pages": key_pages, "max_key_pages": MAX_KEY_PAGES,
            # IDX-6: links to these domains are not "links to another site" and are never requested.
            "brand_family_domains": family, "max_brand_family_domains": MAX_BRAND_FAMILY_DOMAINS,
            "rendering": {"policy": "sampled" if shape["rendering_enabled"] else "off", "pages": shape["render_budget"],
                          "label": t("plan.rendering.on", pages=shape["render_budget"]) if shape["rendering_enabled"]
                          else t("plan.rendering.off")},
            "time_limit_minutes": shape["time_limit_minutes"], "duration": duration,
            # Fast check and the links to other sites, as switched on the card (DECISIONS 219).
            "switches": {**switches, "external_cap": shape["external_cap"],
                         "fast_label": t("plan.fast.label"), "fast_help": t("plan.fast.help"),
                         "external_label": t("plan.external.label"), "external_help": t("plan.external.help", cap=shape["external_cap"])},
            "request_delay_s": shape["request_delay_s"],
            "included": [t(f"plan.included.{name}") for name in ("access", "indexing", "rendering", "structure", "speed", "integrity")],
            "optional": [t("plan.optional.key_pages"), t("plan.optional.backlinks"), t("plan.optional.search_data"), t("plan.optional.firecrawl"),
                         t("plan.optional.verify"), t("plan.optional.archives")],
            "unavailable": [t(f"plan.unavailable.{name}") for name in ("search_console", "logs", "citations", *(() if engine.crux_key() else ("pagespeed",)))],
            "limitations": [t("plan.limit.unknown_size", cap=cap), t("plan.limit.blocking"), t("plan.limit.sample", cap=cap),
                            t("plan.limit.time", limit=shape["time_limit_minutes"]), t("plan.polite"),
                            *([t("plan.brand.common_word", brand=who["brand_name"] or ordinary)] if ordinary else [])],
            "paid": {**cost, "provider_balance": balance or {"known": False, "message": t("paid.balance.unknown")}},
            "firecrawl": reader,
            "paid_options": options, "archives": bool(extras.get("archives")),
            "ownership": {**ownership_of(project_of(url)), "requested": bool(extras.get("verify_ownership"))},
            "search_data": {"requested": options["search_data"], "local_business": options["local_business"],
                            **market,
                            "market_warning": t("plan.market.default", detail=insights.market_warning(options["country"])) if insights.market_warning(options["country"]) else None,
                            "brand_warning": t("plan.brand.common_word", brand=who["brand_name"] or ordinary) if ordinary else None,
                            "core_web_vitals": t("crux.plan.on") if engine.crux_key() else t("crux.plan.off")},
            "lines": [t("plan.intro")],
        }
        return document, fingerprint, cost["total_usd"]

    def switch_basis(switches: dict[str, Any] | None) -> dict[str, bool]:
        """What the fingerprint holds about the two switches: a changed switch is a changed plan. Written so that a plan
        with both at their defaults has the fingerprint it had before the switches existed."""
        switches = switches or {}
        return {"fast_check": bool(switches.get("fast_check")), "no_external_links": switches.get("external_links", True) is False}

    def market_basis(options: dict[str, Any] | None) -> list[Any]:
        """What the fingerprint holds about the market: a changed country, brand or accepted default is a changed plan."""
        options = options or {}
        code, language, _place, known = insights.location_for(options.get("country"))
        return [code, language, (options.get("brand") or "").strip(), known, bool(options.get("market_default_accepted"))]

    def last_balance() -> dict[str, Any] | None:
        return paid.latest_balance(store.get_meta("provider_balance"), store.get_meta("provider_balance_failed"))

    def plan_view(plan: dict[str, Any]) -> dict[str, Any]:
        confirmation = store.confirmation(plan["id"])
        audit = store._one("SELECT id FROM audits WHERE plan_id = ?", (plan["id"],))
        document = plan["document"]
        cost = document["paid"]
        reader = document.get("firecrawl") or NO_FIRECRAWL
        needs = bool(cost["needs_confirmation"]) or bool(reader["needs_confirmation"])
        market_block = (document.get("search_data") or {}).get("market_block")
        return {**document, "created_at": plan["created_at"], "expires_at": plan["expires_at"],
                # Why Start is not offered, when the reason is the plan's own (today: search data without a known market).
                "cannot_start": market_block,
                # Read now, not when the plan was made: a balance checked again with the button changes the warning.
                "balance_warning": None if audit else paid.balance_warning(cost, last_balance(), demo=engine.demo),
                "expired": is_past(plan["expires_at"]), "audit_id": audit["id"] if audit else None,
                "confirmation": None if confirmation is None else {
                    "approved_max_usd": confirmation["approved_usd"], "approved_max_credits": confirmation["approved_credits"],
                    "confirmed_at": confirmation["confirmed_at"], "expires_at": confirmation["expires_at"]},
                "needs_confirmation": needs and confirmation is None,
                # What the one Confirm button approves: dollars for DataForSEO, credits for Firecrawl, each exact.
                "to_confirm": None if not needs else {
                    "approved_max_usd": cost["total_usd"] if cost["needs_confirmation"] else None,
                    "approved_max_credits": reader["max_credits"] if reader["needs_confirmation"] else None,
                    "label": confirm_label(cost, reader)},
                "can_start": audit is None and not is_past(plan["expires_at"]) and not (cost["requested"] and cost["blocked"])
                and not (reader["requested"] and reader["blocked"]) and not (needs and confirmation is None) and not market_block}

    def confirm_label(cost: dict[str, Any], reader: dict[str, Any]) -> str:
        parts = []
        if cost["needs_confirmation"]:
            parts.append(t("confirm.part.usd", total=usd(cost["total_usd"])))
        if reader["needs_confirmation"]:
            parts.append(t("confirm.part.credits", credits=reader["max_credits"]) if reader["max_usd"] is None else
                         t("confirm.part.credits_usd", credits=reader["max_credits"], usd=f"{reader['max_usd']:.4f}"))
        return t("confirm.button", what=t("confirm.and").join(parts))

    def recheck(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Price the plan again and refuse if anything a confirmation was tied to has moved."""
        saved_options = plan["document"].get("paid_options")
        cost = paid.price(plan["url"], engine.paid, requested=plan["backlinks"], options=saved_options if plan["backlinks"] else None)
        asked = plan["document"].get("firecrawl") or NO_FIRECRAWL
        reader = fc.plan(engine.firecrawl, asked["options"] if asked["requested"] else None, plan["document"]["page_cap"],
                         plan["document"]["rendering"]["policy"] != "off")
        if paid.fingerprint(plan["url"], plan["mode"], plan["key_pages"], plan["backlinks"], cost["calls"],
                            cost["total_usd"], reader, {"search_data": bool((saved_options or {}).get("search_data")),
                                                        "local_business": bool((saved_options or {}).get("local_business")),
                                                        "archives": bool(plan["document"].get("archives")),
                                                        "verify_ownership": bool((plan["document"].get("ownership") or {}).get("requested")),
                                                        "brand_family_domains": sorted(plan["document"].get("brand_family_domains") or []),
                                                        **switch_basis(plan["document"].get("switches"))},
                            market_basis(saved_options) if plan["backlinks"] else None) != plan["fingerprint"]:
            raise ApiError(409, "plan_changed", t("plan.changed"), new_total_usd=cost["total_usd"])
        # The country and brand on the card are the run's: a plan made before they were changed is not run (DECISIONS 179).
        saved = store.profile(plan["project_id"])
        if saved is not None and saved_options is not None:
            country_now, brand_now = (saved["profile"].get("countries") or [None])[0], saved["profile"].get("brand_name") or None
            if brand_module.same_name(brand_now, address_guess(plan["project_id"])):
                brand_now = None  # a saved suggestion is no value (DECISIONS 220)
            if ((country_now is not None and country_now.strip() != (saved_options.get("country") or "").strip())
                    or (brand_now is not None and brand_now.strip() != (saved_options.get("brand") or "").strip())):
                raise ApiError(409, "plan_changed", t("plan.changed.business"), changed="business")
        block = (plan["document"].get("search_data") or {}).get("market_block")
        if block:
            raise ApiError(409, block["code"], block["message"])
        if plan["backlinks"] and cost["blocked"]:
            raise ApiError(409, cost["blocked"]["code"], cost["blocked"]["message"])
        if reader["requested"] and reader["blocked"]:
            raise ApiError(409, reader["blocked"]["code"], reader["blocked"]["message"])
        return cost, reader

    @api.get("/health", summary="Is the local server up")
    def health() -> dict[str, Any]:
        return {"status": "ok", "api_version": API_VERSION}

    @api.get("/session", summary="The action token for this browser session")
    def session() -> dict[str, Any]:
        return {"api_version": API_VERSION, "token": guard.token, "language": current_language(), "demo": engine.demo,
                "languages": [{"id": name, "label": LANGUAGE_NAMES.get(name, name), "note": LANGUAGE_NOTES.get(name)} for name in sorted(STRINGS)]}

    @api.put("/session/language", summary="Choose the interface language. Text the engine writes about a site stays in English")
    def choose_language(body: LanguageIn) -> Response:
        if body.language not in STRINGS:
            raise ApiError(422, "unknown_language", t("error.unknown_language"), available=sorted(STRINGS))
        response = JSONResponse({"language": body.language})
        response.set_cookie(LANGUAGE_COOKIE, body.language, samesite="strict", path="/", max_age=365 * 24 * 3600)
        return response

    @api.get("/strings", summary="Every sentence the page shows, for one language")
    def strings(language: str | None = Query(default=None, max_length=10)) -> dict[str, Any]:
        chosen = language if language in STRINGS else current_language() if language is None else DEFAULT_LANGUAGE
        return {"language": chosen, "available": sorted(STRINGS), "strings": strings_module.table(chosen)}

    @api.get("/settings", summary="Safe public settings. No credentials, no file paths")
    def settings() -> dict[str, Any]:
        return {"api_version": API_VERSION, "language": current_language(), "languages": sorted(STRINGS), "demo": engine.demo,
                "demo_sites": [{"address": host, "about": about} for host, about in demo.SITES.items()] if engine.demo else [],
                "modes": [{"id": mode, "label": t(f"plan.mode.{mode}"), "page_cap": cap} for mode, cap in MODES.items()],
                "max_key_pages": MAX_KEY_PAGES, "max_queued": MAX_QUEUED, "one_audit_at_a_time": True,
                "plan_lifetime_minutes": PLAN_LIFETIME_S // 60, "report_schema": "1.x",
                "paid": {"daily_cap_usd": paid.daily_cap(), "credentials_configured": engine.paid.credentials() is not None},
                "audits_recovered_at_startup": runner.recovered}

    @api.get("/budget", summary="Today's local spending allowance. Asks no provider")
    def budget() -> dict[str, Any]:
        return {**paid.budget(engine.paid),
                "provider_balance": store.get_meta("provider_balance") or {"known": False, "message": t("paid.balance.unknown")}}

    @api.post("/budget/provider-balance", summary="Ask DataForSEO's free account endpoint for the balance, because a person asked")
    def provider_balance() -> dict[str, Any]:
        result = paid.refresh_balance(engine.paid)
        if result["known"]:
            store.set_meta("provider_balance", result)
        elif result.get("checked_at"):
            store.set_meta("provider_balance_failed", result)
        return result

    @api.post("/plans", status_code=201, summary="Make a plan. Nothing is requested from the site or any provider")
    def create_plan(body: PlanIn) -> dict[str, Any]:
        url, plain, typed_http = target(body.url)
        try:
            key_pages = chat.key_page_urls(url, body.key_pages, MAX_KEY_PAGES)
        except ValueError as exc:
            raise ApiError(422, "invalid_key_pages", str(exc)) from None
        # Firecrawl reads every audit's pages when this computer has a key; `firecrawl: false` switches it off for one audit.
        on = body.firecrawl if body.firecrawl is not None else (
            firecrawl_settings.main_reader_on() and engine.firecrawl.key() is not None)
        wanted = None if not (on or body.firecrawl_render) else {
            "read_always": True, "render_fallback": body.firecrawl_render,
            "max_pages": body.firecrawl_max_pages or min(MODES[body.mode], firecrawl_settings.MAX_PAGES_LIMIT), "proxy": body.firecrawl_proxy,
            "owner_approved_bypass": body.firecrawl_owner_approved,
            "allow_without_zero_data_retention": not firecrawl_settings.zero_data_retention_wanted()}
        document, fingerprint, total = plan_document(url, body.mode, key_pages, body.backlinks, plain, typed_http, wanted,
                                                     {"search_data": body.search_data, "local_business": body.local_business and body.search_data,
                                                      "archives": body.archives, "verify_ownership": body.verify_ownership,
                                                      "market_default_accepted": body.market_default_accepted,
                                                      "fast_check": body.fast_check, "external_links": body.external_links},
                                                     brand=body.brand_name, country=body.country,
                                                     family=None if body.brand_family_domains is None else brand_family(body.brand_family_domains))
        plan = store.create_plan(project_id=document["project_id"], url=url, mode=body.mode, key_pages=key_pages,
                                 backlinks=body.backlinks or body.search_data, fingerprint=fingerprint, total_usd=total, document=document,
                                 lifetime_s=PLAN_LIFETIME_S)
        return plan_view(plan)

    @api.get("/plans/{plan_id}", summary="A plan as it was made")
    def get_plan(plan_id: str) -> dict[str, Any]:
        return plan_view(need_plan(plan_id))

    @api.post("/plans/{plan_id}/confirm", summary="Approve a paid plan's exact maximum cost. Starts nothing")
    def confirm_plan(plan_id: str, body: ConfirmIn) -> dict[str, Any]:
        plan = need_plan(plan_id)
        if is_past(plan["expires_at"]):
            raise ApiError(410, "plan_expired", t("plan.expired"))
        cost, reader = recheck(plan)
        if not cost["needs_confirmation"] and not reader["needs_confirmation"]:
            raise ApiError(409, "nothing_to_confirm", t("paid.nothing_to_pay"))
        if cost["needs_confirmation"] and (body.approved_max_usd is None
                                           or round(body.approved_max_usd, 6) != round(plan["total_usd"], 6)):
            raise ApiError(422, "amount_mismatch", t("paid.wrong_amount", approved=usd(body.approved_max_usd or 0),
                                                     total=usd(plan["total_usd"])), plan_total_usd=plan["total_usd"])
        if reader["needs_confirmation"] and (body.approved_max_credits is None
                                             or round(body.approved_max_credits, 6) != round(reader["max_credits"], 6)):
            raise ApiError(422, "credits_mismatch", t("fc.wrong_credits", approved=f"{body.approved_max_credits or 0:g}",
                                                      credits=reader["max_credits"]), plan_max_credits=reader["max_credits"])
        store.confirm(plan, plan["total_usd"] if cost["needs_confirmation"] else 0.0,
                      reader["max_credits"] if reader["needs_confirmation"] else 0.0)
        return plan_view(plan)

    # -- audits ----------------------------------------------------------------------------------

    def timeline(audit: dict[str, Any]) -> list[dict[str, Any]]:
        progress, active = audit["progress"], is_active(audit)
        seen, current = progress.get("steps_seen") or [], progress.get("step")
        rendering_on = (audit["config"] or {}).get("render_enabled", True)
        rows = []
        for step in STEPS:
            reason = None
            if step == "backlinks" and not audit["backlinks"]:
                status, reason = "skipped", t("step.skipped.backlinks")
            elif step == "backlinks" and audit["paid_state"] == "skipped":
                status, reason = "skipped", t("step.skipped.balance")
            elif step == "rendering" and not rendering_on:
                status, reason = "skipped", t("step.skipped.rendering")
            elif active and audit["state"] != "queued" and step == current:
                status = "active"
            elif step in seen:
                status = "done"
                if step == "rendering" and progress.get("render_mode") == "raw_html_only":
                    status, reason = "unavailable", progress.get("render_reason") or t("result.rendering.off")
            else:
                status = "pending" if active else "not_reached"
            rows.append({"step": step, "label": t(f"step.{step}"), "status": status, "status_label": t(f"step.status.{status}"),
                         "reason": reason})
        return rows

    def eta(audit: dict[str, Any]) -> dict[str, Any]:
        progress = audit["progress"]
        if audit["state"] != "running":
            return {"kind": "none", "label": None}
        at = progress.get("at")
        if at and (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() > STALE_AFTER_S:
            return {"kind": "waiting", "label": t("eta.waiting")}
        if progress.get("step") != "crawling":
            # After the crawl (DECISIONS 294): Firecrawl's measured pace, when it is reading; else the time limit's bound.
            reader = progress.get("firecrawl") or {}
            limit, started = (audit["config"] or {}).get("time_limit_s"), audit.get("started_at")
            limit_left = None
            if limit and started:
                limit_left = max(0, round(float(limit) - (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()))
            pace = reader.get("seconds_per_page")
            if pace and reader.get("page_cap") and (reader.get("read") or 0) < reader["page_cap"]:
                seconds = round((reader["page_cap"] - (reader.get("read") or 0)) * float(pace))
                if limit_left is not None:
                    seconds = min(seconds, limit_left)
                return {"kind": "estimate", "max_seconds": seconds,
                        "label": t("eta.reader", minutes=max(1, round(seconds / 60)), seconds=f"{float(pace):.1f}")}
            if limit_left is not None:
                return {"kind": "limit", "max_seconds": limit_left, "label": t("eta.limit", minutes=max(1, round(limit_left / 60)))}
            return {"kind": "unknown", "label": t("eta.unknown")}
        done = (progress.get("pages_checked") or 0) - (progress.get("session_pages_start") or 0)
        spent = (progress.get("elapsed_s") or 0) - (progress.get("crawl_started_s") or 0)
        left = max(0, progress.get("page_cap", 0) - (progress.get("pages_checked") or 0))
        if done < 5 or spent <= 0:
            return {"kind": "calculating", "label": t("eta.calculating")}
        seconds = round(left * spent / done)
        return {"kind": "estimate", "max_seconds": seconds, "label": t("eta.estimate", minutes=max(1, round(seconds / 60)))}

    def audit_view(audit: dict[str, Any]) -> dict[str, Any]:
        progress = audit["progress"]
        cap = MODES[audit["mode"]]
        elapsed = None
        if audit["started_at"]:
            end = datetime.fromisoformat(audit["finished_at"]) if audit["finished_at"] else datetime.now(timezone.utc)
            elapsed = max(0, round((end - datetime.fromisoformat(audit["started_at"])).total_seconds()))
        state = audit["state"]
        note = {"stopped": t("job.stopped.detail"), "interrupted": t("job.interrupted.detail")}.get(state)
        return {
            **({"analysis": audit["analysis"]} if audit.get("analysis") else {}),
            "id": audit["id"], "plan_id": audit["plan_id"], "project_id": audit["project_id"], "url": audit["url"],
            "host": urlsplit(audit["url"]).hostname, "mode": audit["mode"], "mode_label": t(f"plan.mode.{audit['mode']}"),
            # The job's lifecycle, and beside it what the audit concluded. One does not imply the other.
            "state": state, "state_label": t(f"job.state.{state}"), "state_note": note, "active": is_active(audit),
            "can_stop": state in ("queued", "running"), "can_resume": state in RESUMABLE,
            "outcome": None if not audit["outcome"] else {"code": audit["outcome"], "label": summary.outcome_label(audit["outcome"], audit["outcome_reason"]),
                                                          "reason": audit["outcome_reason"],
                                                          # the same sentence in the reader's language (the engine's stays in `reason`)
                                                          "reason_shown": wording.outcome(audit["outcome_reason"])[0],
                                                          "crawl_stop": audit["crawl_stop"]},
            "error": None if state != "failed" else {"code": audit["error_code"], "message": audit["outcome_reason"]},
            "timeline": timeline(audit),
            "counters": {"pages_checked": progress.get("pages_checked", 0), "page_cap": cap,
                         "page_cap_note": t("job.cap_note", cap=cap), "redirects": progress.get("redirects"),
                         "other_fetches": progress.get("other_fetches", 0), "requests_sent": progress.get("requests_sent", 0),
                         "discovered": progress.get("discovered"),
                         # Pages read by Firecrawl, beside Maya's own (DECISIONS 294); None before it starts.
                         "firecrawl_read": (progress.get("firecrawl") or {}).get("read"),
                         "firecrawl_cap": (progress.get("firecrawl") or {}).get("page_cap"),
                         "firecrawl_at_once": ((audit["firecrawl"] or {}).get("options") or {}).get("concurrency")},
            "current_url": progress.get("url") if is_active(audit) else None,
            "address_note": progress.get("address_note"),
            "created_at": audit["created_at"], "started_at": audit["started_at"], "finished_at": audit["finished_at"],
            "elapsed_s": elapsed, "eta": eta(audit), "sessions": audit["sessions"],
            "settings": {"mode": audit["mode"], "page_cap": cap, "key_pages": audit["key_pages"], "backlinks": audit["backlinks"],
                         "rendering": (audit["config"] or {}).get("render_enabled"),
                         "request_delay_s": (audit["config"] or {}).get("request_delay_s"),
                         "time_limit_s": (audit["config"] or {}).get("time_limit_s")},
            "paid": {"requested": audit["backlinks"], "state": audit["paid_state"], "approved_max_usd": audit["approved_usd"],
                     "skipped": audit["paid_state"] == "skipped"},
            "firecrawl": {"requested": bool(audit["firecrawl"]), "state": audit["firecrawl"].get("state", "none"),
                          "options": audit["firecrawl"].get("options"),
                          "needs_decision": audit["firecrawl"].get("state") == "needs_decision" and state == "finished",
                          # A finished audit that is only being read through Firecrawl now; the website is not asked again.
                          "continuing": bool(audit["firecrawl"].get("continue")) and is_active(audit)},
            "has_report": report_path(audit["id"]).is_file(), "last_event_id": store.last_event_id(audit["id"]),
        }

    def backlinks_view(audit: dict[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
        if report.get("dataforseo"):
            return paid.describe(report["dataforseo"], engine.paid)
        if not audit["backlinks"]:
            return None
        # Asked for, and there are no figures. Say why; never show an empty panel that reads as "no backlinks".
        reason = {"pending": t("paid.unavailable.pending"), "attempted": t("paid.unavailable.interrupted")}.get(
            audit["paid_state"], t("paid.unavailable.pending"))
        return {"available": False, "status": "not_assessed", "checks": [], "cost_usd": None, "estimated_usd": None,
                "requests_sent": None, "calls": [], "target": None, "spent_line": reason, "unavailable_reason": reason}

    def firecrawl_offer(audit: dict[str, Any], report: dict[str, Any], view: dict[str, Any]) -> dict[str, Any] | None:
        """What the result card may offer on a finished audit that the site blocked. Requests nothing."""
        if audit.get("analysis") or audit["state"] != "finished":
            return None
        return fc.offer(engine.firecrawl, report.get("firecrawl"), audit["firecrawl"], MODES[audit["mode"]],
                        crawl_blocked=view.get("blocked") is not None, offline=snapshot.exists(runner.state_folder(audit["id"])))

    def result_view(audit: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
        report = report or load_report(audit)
        view = summary.build(report, outcome=audit["outcome"], reason=audit["outcome_reason"],
                             backlinks=backlinks_view(audit, report), resumable=audit["state"] in RESUMABLE,
                             profile=profile_of(audit["project_id"]), audit={"page_cap": MODES[audit["mode"]]},
                             # A report saved before schema 1.9 holds no problems by page: the engine derives them from
                             # the report and the full page lists saved beside it. The saved files are not rewritten.
                             affected=None if "problem_summary" in report else affected(audit["id"]))
        base = f"/api/v1/audits/{audit['id']}"
        reader = fc.view(report.get("firecrawl"), {**audit["firecrawl"], "audit_page_cap": MODES[audit["mode"]]}
                         if audit["state"] == "finished" else {}, crawl=report.get("crawl"))
        full = {"audit": audit_view(audit), "demo": engine.demo, **view, "firecrawl": reader,
                "ownership": summary.ownership_view(report.get("ownership")), "verification": ownership_of(audit["project_id"]),
                "crux": summary.speed_view(report.get("crux") or crux.unavailable()),
                "archives": summary.archives_view(archives.view(report["archives"])) if report.get("archives") else None,
                "firecrawl_offer": firecrawl_offer(audit, report, view),
                # A report the release gate blocked downloads only as a marked draft, and the buttons say so (DECISIONS 280).
                "release_gate": gate_decision(report),
                "downloads": [{"format": fmt, "url": f"{base}/downloads/{fmt}" + ("?draft=true" if draft else ""),
                               "label": t("result.download.draft", label=t(f"result.download.{fmt}")) if draft
                               else t(f"result.download.{fmt}")}
                              for fmt in ("pdf", "markdown", "json", "evidence")
                              for draft in [fmt != "evidence" and gate_decision(report) == release_gate.BLOCKED]],
                "print_url": f"{base}/print", "has_previous": not audit.get("analysis") and store.previous_audit(audit) is not None}
        # The practical report in brief: the executive summary, the scorecard and the timeline's counts. The whole of it,
        # with every issue and the page table, is GET /audits/{id}/practical: a results card stays small.
        built = practical.build(full, summary.search(report, limit=100_000)["items"], report, None)
        full["practical"] = {"executive": built["executive"], "scorecard": built["scorecard"], "sources": built["sources"],
                             "by_page": built["by_page"],
                             "timeline": [{"id": step["id"], "label": step["label"], "note": step["note"], "count": len(step["items"]),
                                           "items": [{"severity": row["severity"], "severity_label": row["severity_label"], "what": row["what"],
                                                      "owner": row["owner"], "effort": row["effort"]} for row in step["items"][:10]]}
                                          for step in built["timeline"]],
                             "url": f"{base}/practical"}
        return full

    def practical_view(audit: dict[str, Any], view: dict[str, Any] | None = None) -> dict[str, Any]:
        report = load_report(audit)
        view = view or result_view(audit, report)
        result = practical.build(view, summary.search(report, limit=100_000)["items"], report, artifact_folder(audit["id"]))
        if audit.get('analysis'):
            result['analysis'] = audit['analysis']
        return result

    @api.post("/audits", summary="Start the audit a plan describes. The same plan twice gives the same audit")
    def start_audit(body: AuditIn, response: Response) -> dict[str, Any]:
        plan = need_plan(body.plan_id)
        existing = store._one("SELECT * FROM audits WHERE plan_id = ?", (plan["id"],))
        if existing:
            return audit_view(existing)
        if is_past(plan["expires_at"]):
            raise ApiError(410, "plan_expired", t("plan.expired"))
        cost, reader = recheck(plan)
        approved, credits = 0.0, 0.0
        confirmation = store.confirmation(plan["id"])
        current = confirmation is not None and confirmation["fingerprint"] == plan["fingerprint"] and not is_past(confirmation["expires_at"])
        # The account may not be able to pay for this plan: the person decides once, before anything is spent elsewhere.
        flags: dict[str, Any] = {}
        warning = paid.balance_warning(cost, last_balance(), demo=engine.demo)
        if warning:
            offered = [choice["id"] for choice in warning["choices"]]
            if body.balance_choice is None:
                raise ApiError(409, "balance_decision_required", warning["message"], level=warning["level"], choices=offered,
                               balance_usd=warning["balance_usd"], total_usd=warning["total_usd"])
            if body.balance_choice not in offered:
                raise ApiError(422, "balance_choice_not_offered", t("plan.balance.not_offered"), level=warning["level"], choices=offered)
            if body.balance_choice == "without_search_data":
                flags = {"paid_skipped": dfs_panel.balance_reason(warning["balance_usd"]), "balance_level": warning["level"]}
        if flags.get("paid_skipped"):
            pass  # nothing is approved, reserved or sent at DataForSEO; the plan and the Firecrawl approval are untouched
        elif cost["needs_confirmation"]:
            if not current or round(confirmation["approved_usd"], 6) != round(cost["total_usd"], 6):
                raise ApiError(402, "confirmation_required", t("paid.need_confirmation", total=usd(cost["total_usd"])),
                               total_usd=cost["total_usd"])
            approved = confirmation["approved_usd"]
        elif cost["requested"] and not cost["blocked"]:
            approved = cost["total_usd"]  # within the per-audit threshold: shown on the plan, recorded in the ledger, not asked about
        if reader["needs_confirmation"]:
            if not current or round(confirmation["approved_credits"], 6) != round(reader["max_credits"], 6):
                raise ApiError(402, "confirmation_required", t("fc.need_confirmation", credits=reader["max_credits"]),
                               max_credits=reader["max_credits"])
            credits = confirmation["approved_credits"]
        elif reader["requested"]:
            credits = reader["max_credits"]  # the page reader of a normal run: recorded and guarded, not asked about
        use = None if not reader["requested"] else {"state": "pending", "options": reader["options"], "approved_credits": credits}
        if store.count_active() >= MAX_QUEUED + 1:
            raise ApiError(429, "queue_full", t("job.queue_full", limit=MAX_QUEUED))
        config = crawl_config(engine, {**plan, "verification": plan["document"].get("ownership")}, Path(CRAWL_DB), resume=False).snapshot()
        audit, created = store.create_audit(plan, approved, config, use, current_language(), flags)
        if created:
            if body.message:
                store.add_message(audit["id"], "user", "text", {"text": body.message})
            store.add_message(audit["id"], "assistant", "plan", {"plan_id": plan["id"]})
            store.add_message(audit["id"], "assistant", "audit", {"audit_id": audit["id"]})
            runner.emit(audit["id"], "state", {"state": "queued"})
            runner.submit()
            response.status_code = 201
        return audit_view(store.audit(audit["id"]))

    @api.get('/analyses', summary='Separately processed saved evidence; never new crawls')
    def list_analyses():
        return {'analyses': [a['analysis'] for a in analysis_registry.list()]}

    @api.get('/analyses/{analysis_id}')
    def analysis_identity(analysis_id: str):
        audit = analysis_registry.get(analysis_id)
        if audit is None:
            raise ApiError(404, 'audit_not_found', t('error.audit_not_found'))
        return {**audit['analysis'], 'result_url': '/api/v1/audits/'+analysis_id+'/summary'}

    @api.get("/audits", summary="History, newest first")
    def list_audits(q: str = Query(default="", max_length=200), domain: str = Query(default="", max_length=253),
                    status: str = Query(default="", pattern="^(|queued|running|stopping|stopped|interrupted|finished|failed)$"),
                    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100_000)) -> dict[str, Any]:
        rows, total = store.audits(query=q, domain=domain.lower().removeprefix("www."), status=status, limit=limit, offset=offset)
        return {"total": total, "limit": limit, "offset": offset, "audits": [
            {"id": a["id"], "project_id": a["project_id"], "url": a["url"], "host": urlsplit(a["url"]).hostname, "mode": a["mode"],
             "state": a["state"], "state_label": t(f"job.state.{a['state']}"), "active": is_active(a),
             "outcome": a["outcome"], "outcome_label": summary.outcome_label(a["outcome"], a.get("outcome_reason")),
             "pages_checked": a["progress"].get("pages_checked", 0), "created_at": a["created_at"],
             "finished_at": a["finished_at"]} for a in rows]}

    @api.get("/audits/{audit_id}", summary="One audit: lifecycle, outcome, steps, counters")
    def get_audit(audit_id: str) -> dict[str, Any]:
        return audit_view(need_audit(audit_id))

    @api.delete("/audits/{audit_id}", summary="Remove an audit and its saved files from this computer")
    def delete_audit(audit_id: str) -> dict[str, Any]:
        audit = need_audit(audit_id)
        if is_active(audit):
            raise ApiError(409, "audit_running", t("job.delete_running"))
        store.delete_audit(audit["id"])
        left = _remove_tree(store.audit_folder(audit["id"]))
        # A file another program holds open (Windows) stays on disk: said, never reported as deleted (D-20).
        return {"deleted": audit["id"], **({"files_left": left, "note": t("job.delete_left", count=left)} if left else {})}

    def stream(audit_id: str, last_id: int | None) -> Iterator[str]:
        yield "retry: 2000\n\n"
        audit = store.audit(audit_id)
        cursor = store.last_event_id(audit_id) if last_id is None else last_id
        # Always a snapshot first: the truth as of now, whatever was missed or trimmed. Then what follows `cursor`.
        yield _sse(cursor, "snapshot", {"v": 1, "audit": audit_view(audit)})
        quiet = 0.0
        while not runner.closing:
            rows = store.events(audit_id, after=cursor, limit=200)
            for row in rows:
                cursor = row["id"]
                yield _sse(cursor, row["type"], {"v": row["version"], "ts": row["ts"], **row["data"]})
            audit = store.audit(audit_id)
            if audit is None:
                return
            if not rows:
                if audit["state"] not in ACTIVE:
                    yield _sse(cursor, "end", {"v": 1, "audit": audit_view(audit)})
                    return
                time.sleep(0.25)
                quiet += 0.25
                if quiet >= heartbeat_s:
                    quiet = 0.0
                    yield ": heartbeat\n\n"
            else:
                quiet = 0.0

    app.state.stream = stream

    @api.get("/audits/{audit_id}/events", summary="Progress as server-sent events, with replay after Last-Event-ID",
             response_class=StreamingResponse)
    def events(audit_id: str, request: Request) -> StreamingResponse:
        audit = need_audit(audit_id)
        if audit.get('analysis'):
            return StreamingResponse(iter([_sse(0, 'end', {'audit': audit_view(audit)})]), media_type='text/event-stream')
        raw = request.headers.get("last-event-id", "")
        last_id = int(raw) if raw.isascii() and raw.isdigit() and len(raw) < 18 else None
        return StreamingResponse(stream(audit_id, last_id), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @api.post("/audits/{audit_id}/stop", summary="Ask the audit to stop before its next request")
    def stop_audit(audit_id: str) -> dict[str, Any]:
        audit = need_audit(audit_id)
        if runner.stop(audit["id"]) is None:
            raise ApiError(409, "audit_not_running", t("job.not_running"))
        note = t("job.stop.paid_note") if audit["progress"].get("step") == "backlinks" else t("job.stop.note")
        return {**audit_view(store.audit(audit["id"])), "note": note}

    def resume_plan_view(audit: dict[str, Any]) -> dict[str, Any]:
        resumable = audit["state"] in RESUMABLE
        cap = MODES[audit["mode"]]
        saved = pages_saved(runner.state_folder(audit["id"]) / CRAWL_DB)
        cost: dict[str, Any] = {"pending": False, "needs_confirmation": False, "total_usd": 0.0, "calls": [], "blocked": None,
                                "note": t("paid.resume.none")}
        if audit["backlinks"]:
            if audit["paid_state"] == "pending":
                priced = paid.price(audit["url"], engine.paid, requested=True,
                                    options=((store.plan(audit["plan_id"]) or {}).get("document") or {}).get("paid_options"))
                cost = {"pending": True, "needs_confirmation": priced["needs_confirmation"], "total_usd": priced["total_usd"],
                        "calls": priced["calls"], "blocked": priced["blocked"], "budget": priced["budget"],
                        "note": t("paid.resume.pending", total=usd(priced["total_usd"])) if priced["needs_confirmation"]
                        else t("paid.resume.cached") if not priced["blocked"] else priced["blocked"]["message"]}
            elif audit["paid_state"] == "attempted":
                cost["note"] = t("paid.unavailable.interrupted")
            else:
                cost["note"] = t("paid.resume.done")
        reader: dict[str, Any] = {"pending": False, "needs_confirmation": False, "max_credits": 0, "blocked": None,
                                  "note": t("fc.resume.none")}
        use = audit["firecrawl"]
        if use.get("state") == "pending":
            shown = fc.plan(engine.firecrawl, use["options"], cap, True)
            reader = {"pending": True, "needs_confirmation": shown["needs_confirmation"], "max_credits": shown["max_credits"],
                      "max_usd": shown["max_usd"], "blocked": shown["blocked"],
                      "note": shown["blocked"]["message"] if shown["blocked"] else t("fc.resume.pending", credits=shown["max_credits"])}
        elif use.get("state"):
            reader["note"] = t("fc.resume.done")
        return {"audit_id": audit["id"], "resumable": resumable, "state": audit["state"], "firecrawl": reader,
                "reason": None if resumable else t("job.not_resumable"),
                "pages_saved": saved, "page_cap": cap, "pages_left": max(0, cap - saved),
                "continues_from_saved_crawl": saved > 0,
                "repeats": [t("resume.repeats.robots"), t("resume.repeats.checks")],
                "keeps": [t("resume.keeps.pages", count=saved), t("resume.keeps.settings")],
                "paid": cost}

    @api.post("/audits/{audit_id}/resume-plan", summary="What a resume would do, and whether it needs a new approval")
    def resume_plan(audit_id: str) -> dict[str, Any]:
        return resume_plan_view(need_audit(audit_id))

    @api.post("/audits/{audit_id}/resume", summary="Continue a stopped or interrupted audit from its saved crawl")
    def resume_audit(audit_id: str, body: ResumeIn) -> dict[str, Any]:
        audit = need_audit(audit_id)
        plan = resume_plan_view(audit)
        if not plan["resumable"]:
            raise ApiError(409, "audit_not_resumable", t("job.not_resumable"))
        approved = 0.0
        if plan["paid"]["needs_confirmation"]:
            total = plan["paid"]["total_usd"]
            if body.approved_max_usd is None or round(body.approved_max_usd, 6) != round(total, 6):
                raise ApiError(402, "confirmation_required", t("paid.need_confirmation", total=usd(total)), total_usd=total)
            approved = total
        elif plan["paid"]["pending"] and not plan["paid"].get("blocked"):
            approved = plan["paid"]["total_usd"]  # within the per-audit threshold
        reader = plan["firecrawl"]
        if reader["pending"]:
            # An approval is for one run. A resume that may still spend credits is approved again, to the exact number.
            if reader["blocked"]:
                raise ApiError(409, reader["blocked"]["code"], reader["blocked"]["message"])
            if reader["needs_confirmation"] and (body.approved_max_credits is None or round(body.approved_max_credits, 6) != round(reader["max_credits"], 6)):
                raise ApiError(402, "confirmation_required", t("fc.need_confirmation", credits=reader["max_credits"]),
                               max_credits=reader["max_credits"])
        if store.count_active() >= MAX_QUEUED + 1:
            raise ApiError(429, "queue_full", t("job.queue_full", limit=MAX_QUEUED))
        if reader["pending"]:
            store.update_audit(audit["id"], firecrawl={**audit["firecrawl"], "approved_credits": reader["max_credits"]})
        if not runner.resume(audit["id"], approved):
            raise ApiError(409, "audit_not_resumable", t("job.not_resumable"))
        return audit_view(store.audit(audit["id"]))

    def read_through_firecrawl(audit: dict[str, Any], body: FirecrawlReadIn, only: str | None = None) -> dict[str, Any]:
        """Start the Firecrawl step on a finished, blocked audit. Every tick and the exact maximum are checked here."""
        report = load_report(audit) if audit["state"] == "finished" and report_path(audit["id"]).is_file() else None
        kind = None if report is None else fc.offer_kind(report.get("firecrawl"), audit["firecrawl"], summary.blocked(report) is not None)
        if only and kind != only:
            raise ApiError(409, "no_decision_waiting", t("fc.zdr.nothing_waiting"))
        if kind not in ("not_requested", "zero_data_retention", "also_blocked"):
            raise ApiError(409, "firecrawl_not_offered", t("fc.offer.none"))
        use = audit["firecrawl"]
        allowed = fc.STRONGER if kind == "also_blocked" else ((use.get("options") or {}).get("proxy") or "basic",)
        if body.proxy not in allowed:
            raise ApiError(422, "firecrawl_options", t("fc.offer.wrong_proxy", proxies=", ".join(allowed)))
        if body.proxy != "basic" and not body.owner_approved_bypass:
            raise ApiError(422, "owner_approval_required", t("fc.offer.must_approve"))
        options = fc.continuation_options(kind, use, body.proxy, body.owner_approved_bypass)
        if options["allow_without_zero_data_retention"] and not body.accept_content_may_be_stored:
            raise ApiError(422, "storage_not_accepted", t("fc.zdr.must_accept"))
        shown = fc.plan(engine.firecrawl, options, MODES[audit["mode"]], False)
        if shown["blocked"]:
            raise ApiError(409, shown["blocked"]["code"], shown["blocked"]["message"])
        if round(body.approved_max_credits, 6) != round(shown["max_credits"], 6):
            raise ApiError(402, "confirmation_required", t("fc.need_confirmation", credits=shown["max_credits"]),
                           max_credits=shown["max_credits"])
        if store.count_active() >= MAX_QUEUED + 1:
            raise ApiError(429, "queue_full", t("job.queue_full", limit=MAX_QUEUED))
        stamps = {key: use[key] for key in ("zero_data_retention_waived_at", "owner_approved_at", "attempts", "switched_on_at") if key in use}
        if kind == "zero_data_retention":
            stamps["zero_data_retention_waived_at"] = now()
        if kind == "not_requested":
            stamps["switched_on_at"] = now()
        if options["owner_approved_bypass"]:
            stamps["owner_approved_at"] = now()
        store.update_audit(audit["id"], firecrawl={**stamps, "state": "pending", "options": shown["options"],
                                                   "approved_credits": shown["max_credits"], "continue": True})
        if not runner.resume(audit["id"], 0.0, also_finished=True):
            raise ApiError(409, "audit_not_resumable", t("job.not_resumable"))
        return audit_view(store.audit(audit["id"]))

    @api.post("/audits/{audit_id}/firecrawl/read",
              summary="On a finished audit the site blocked: read its content through Firecrawl now, with every tick and the exact credits confirmed")
    def firecrawl_read(audit_id: str, body: FirecrawlReadIn) -> dict[str, Any]:
        return read_through_firecrawl(need_audit(audit_id), body)

    @api.post("/audits/{audit_id}/firecrawl/without-zero-data-retention",
              summary="After Firecrawl refused zero data retention: the person's explicit decision to proceed without it, for this audit")
    def without_retention(audit_id: str, body: WithoutRetentionIn) -> dict[str, Any]:
        audit = need_audit(audit_id)
        proxy = ((audit["firecrawl"].get("options") or {}).get("proxy")) or "basic"
        return read_through_firecrawl(audit, FirecrawlReadIn(
            proxy=proxy, owner_approved_bypass=bool((audit["firecrawl"].get("options") or {}).get("owner_approved_bypass")),
            accept_content_may_be_stored=body.accept_content_may_be_stored, approved_max_credits=body.approved_max_credits),
            only="zero_data_retention")

    @api.get("/audits/{audit_id}/result", summary="The saved report itself: the authoritative, versioned record")
    def result(audit_id: str) -> Response:
        audit = need_audit(audit_id)
        load_report(audit)  # refuses an unreadable or unsupported file before it is served
        return FileResponse(report_path(audit["id"]), media_type="application/json")

    @api.get("/audits/{audit_id}/summary", summary="The results card, built from the saved report")
    def result_summary(audit_id: str) -> dict[str, Any]:
        return result_view(need_audit(audit_id))

    @api.get("/audits/{audit_id}/practical", summary="The practical report as data: executive summary, scorecard, timeline, every issue with its fix, every page, sources")
    def practical_report(audit_id: str) -> dict[str, Any]:
        return practical_view(need_audit(audit_id))

    @api.get("/audits/{audit_id}/action-plan", summary="Fix now, fix next, improve later. Optionally for one role")
    def action_plan(audit_id: str, role: str = Query(default="", pattern="^(|developer|content|seo)$")) -> dict[str, Any]:
        audit = need_audit(audit_id)
        result = summary.action_plan(load_report(audit), role or None)
        if audit.get('analysis'):
            result['analysis'] = audit['analysis']
        return result

    @api.get("/audits/{audit_id}/findings", summary="Filter and page through findings. Changes none of them")
    def list_findings(audit_id: str, severity: str = Query(default="", pattern="^((S1|S2|S3|S4|Info)(,(S1|S2|S3|S4|Info))*)?$"),
                      check_id: str = Query(default="", pattern="^([A-Za-z]{2,5}-[0-9]{1,2})?$"),
                      area: str = Query(default="", pattern="^(|ACC|IDX|RND|STR|TSEO|PRF|other)$"),
                      owner: str = Query(default="", pattern="^(|developer|content|seo)$"), q: str = Query(default="", max_length=200),
                      limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100_000)) -> dict[str, Any]:
        report = load_report(need_audit(audit_id))
        return summary.search(report, severity=severity.split(",") if severity else None, check_id=check_id.upper(),
                              area=area, owner=owner, query=q, offset=offset, limit=limit)

    def need_finding(report: dict[str, Any], finding_id: str) -> dict[str, Any]:
        found = summary.detail(report, finding_id) if len(finding_id) <= 80 else None
        if found is None:
            raise ApiError(404, "finding_not_found", t("error.finding_not_found"))
        return found

    @api.get("/audits/{audit_id}/findings/{finding_id}/pages", summary="Every page a finding affects, searchable, in pages")
    def finding_pages(audit_id: str, finding_id: str, q: str = Query(default="", max_length=200),
                      limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=1_000_000)) -> dict[str, Any]:
        audit = need_audit(audit_id)
        found = need_finding(load_report(audit), finding_id)
        scope = found["record"].get("scope") or {}
        full = affected(audit["id"]).get(finding_id)
        urls = full if full is not None else list(scope.get("urls") or [])
        needle = q.strip().casefold()
        kept = [url for url in urls if needle in url.casefold()] if needle else urls
        return {"finding_id": finding_id, "total": len(kept), "all_pages": scope.get("count") or len(urls),
                "complete": full is not None or len(urls) >= (scope.get("count") or 0),
                "offset": offset, "limit": limit, "pages": kept[offset:offset + limit]}

    @api.get("/audits/{audit_id}/evidence/{evidence_id}", summary="Evidence for a finding, or one saved page record")
    def evidence(audit_id: str, evidence_id: str) -> dict[str, Any]:
        audit = need_audit(audit_id)
        report = load_report(audit)
        page = re.fullmatch(r"page-(\d{1,4})", evidence_id)
        if not page:
            found = need_finding(report, evidence_id)
            return {"evidence_id": evidence_id, "kind": found["kind"], "check": found["check"], "row": found["row"],
                    "record": found["record"]}
        # A saved page: only a file the evidence index lists, opened inside the evidence folder, never through a link.
        folder = artifact_folder(audit["id"]) / "evidence"
        index_path = folder / "index.json"
        listed = json.loads(index_path.read_text(encoding="utf-8"))["pages"] if index_path.is_file() else []
        number = int(page.group(1))
        if not 1 <= number <= len(listed):
            raise ApiError(404, "evidence_not_found", t("error.evidence_not_found"))
        entry = listed[number - 1]
        path = folder / str(entry["file"])
        if (path.name != entry["file"] or path.is_symlink() or not path.is_file()
                or path.resolve().parent != folder.resolve()):
            raise ApiError(404, "evidence_not_found", t("error.evidence_not_found"))
        return {"evidence_id": evidence_id, "kind": "page", "url": entry["url"], "status": entry["status"],
                "record": json.loads(path.read_text(encoding="utf-8"))}

    def download_name(audit: dict[str, Any], extension: str) -> str:
        host = re.sub(r"[^a-z0-9.-]+", "-", (urlsplit(audit["url"]).hostname or "site").lower()).strip("-.") or "site"
        if audit.get('analysis'):
            return f"maya-audit-{host[:60]}-{audit['id']}.{extension}"
        return f"maya-audit-{host[:60]}-{(audit['finished_at'] or audit['created_at'])[:10]}.{extension}"

    def companion_files(audit: dict[str, Any]) -> dict[str, str]:
        """The files that travel with a printed report, by the names they download under. A client reads a file name;
        a link into this app (127.0.0.1) works only on the owner's computer, so the report never prints one (D-08)."""
        return {"json": download_name(audit, "json"), "evidence": download_name(audit, "zip").replace(".zip", "-evidence.zip"),
                "markdown": download_name(audit, "md")}

    def report_language(audit: dict[str, Any], lang: str | None) -> str:
        """The language a printed report or PDF is written in: an explicit `?lang=` first, then the language the audit
        was started in (audits.language), then the reader's cookie for a row that has none. The report goes to a
        client, so the downloading browser's interface choice no longer decides it (C61, D-09)."""
        chosen = lang if lang in STRINGS else audit.get("language") if audit.get("language") in STRINGS else current_language()
        return set_language(chosen)

    def gate_decision(report: dict[str, Any]) -> str | None:
        """The saved gate's decision; a report saved before the gate existed is gated now."""
        saved = report.get("release_gate")
        return saved.get("decision") if isinstance(saved, dict) else final.from_report(report).decision

    def publishable(audit: dict[str, Any], draft: bool = False) -> final.FinalAuditResult:
        """The saved report as one final result and the release gate's decision on it (DECISIONS 280). A blocked
        report is refused unless the caller asked for a draft; a report saved before the gate existed is gated now."""
        sealed = final.from_report(load_report(audit), affected(audit["id"]))
        if sealed.decision == release_gate.BLOCKED and not draft:
            hard = [v for v in sealed.gate.get("violations") or [] if v.get("hard")]
            raise ApiError(409, "release_blocked", t("error.release_blocked", count=len(hard)), decision=sealed.decision,
                           rules=sorted({str(v.get("rule")) for v in hard}), draft=True)
        return sealed

    def printable_html(audit: dict[str, Any], *, full: bool = False) -> tuple[str, dict[str, Any]]:
        report = load_report(audit)
        view = result_view(audit, report)
        rows = summary.search(report, limit=100_000)["items"]
        return pdf.render_html(view, rows=rows, plan=summary.action_plan(report), generated_at=now(), demo=engine.demo,
                               practical=practical_view(audit, view), concise=not full, companions=companion_files(audit)), view

    @api.get("/audits/{audit_id}/print", summary="The report as one printable page: compact unless full=true", response_class=HTMLResponse)
    def printable(audit_id: str, full: bool = False, lang: str | None = Query(default=None, pattern="^[a-z]{2}$")) -> Response:
        audit = need_audit(audit_id)
        report_language(audit, lang)
        html, _ = printable_html(audit, full=full)
        if publishable(audit, draft=True).decision == release_gate.BLOCKED:
            html = pdf.draft_banner(html)  # a view may be read; it says it is not for delivery
        return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    def evidence_zip(audit: dict[str, Any]) -> bytes:
        folder = artifact_folder(audit["id"])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            names = [(AFFECTED_JSON, folder / AFFECTED_JSON)]
            # Maya's own crawl, and apart from it whatever a third-party reader fetched for this audit.
            for kept in ("evidence", "evidence-firecrawl"):
                index_path = folder / kept / "index.json"
                names.append((f"{kept}/index.json", index_path))
                if index_path.is_file() and not index_path.is_symlink():
                    for entry in json.loads(index_path.read_text(encoding="utf-8"))["pages"]:
                        names.append((f"{kept}/{Path(str(entry['file'])).name}", folder / kept / Path(str(entry["file"])).name))
            for name, path in names:
                if path.is_file() and not path.is_symlink() and folder.resolve() in path.resolve().parents:
                    if name.endswith("/index.json"):
                        archive.writestr(name, _without_local_folder(path))
                    else:
                        archive.write(path, name)
        return buffer.getvalue()

    @api.get("/audits/{audit_id}/downloads/{format}", summary="pdf, markdown, json, or evidence (a zip)")
    def download(audit_id: str, format: str, full: bool = False, lang: str | None = Query(default=None, pattern="^[a-z]{2}$"),
                 draft: bool = False) -> Response:
        audit = need_audit(audit_id)
        if format not in DOWNLOAD_NAMES:  # a fixed list: the value never becomes part of a path
            raise ApiError(404, "download_not_found", t("error.download_not_found"))
        extension, media_type = DOWNLOAD_NAMES[format]
        name = download_name(audit, extension)
        load_report(audit)
        gate: dict[str, str] = {}
        blocked = False
        if format != "evidence":  # the raw evidence is not a report; every report form passes the release gate
            sealed = publishable(audit, draft)
            blocked = sealed.decision == release_gate.BLOCKED
            gate = {"X-Maya-Release-Gate": str(sealed.decision)}
            if blocked:
                stem, dot, ext = name.rpartition(".")
                name = f"{stem}-draft{dot}{ext}"
        if format == "pdf":
            report_language(audit, lang)
            html, view = printable_html(audit, full=full)
            if blocked:
                html = pdf.draft_banner(html)
            try:
                content = pdf.to_pdf(html, footer_title=("DRAFT · " if blocked else "") + f"{t('app.title')} · {view['host']}",
                                     max_pages=None if full else 50)
            except pdf.PdfPageLimit as exc:
                raise ApiError(422, "pdf_page_limit", str(exc)) from None
            except pdf.PdfUnavailable:
                raise ApiError(503, "pdf_unavailable", t("result.pdf_unavailable"),
                               print_url=f"/api/v1/audits/{audit['id']}/print") from None
            return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', **gate})
        if format == "evidence":
            return Response(evidence_zip(audit), media_type=media_type,
                            headers={"Content-Disposition": f'attachment; filename="{name.replace(".zip", "-evidence.zip")}"'})
        path = artifact_folder(audit["id"]) / (REPORT_JSON if format == "json" else REPORT_MD)
        if not path.is_file() or path.is_symlink():
            raise ApiError(409, "report_not_ready", t("chat.no_report"))
        if blocked and format != "json":  # the JSON is the evidence record and carries the gate's decision itself
            text = f"> **{t('pdf.draft_banner')}**\n\n" + path.read_text(encoding="utf-8")
            return Response(text, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', **gate})
        return FileResponse(path, media_type=media_type, filename=name, headers=gate)

    def compare_with(audit: dict[str, Any], other_id: str | None) -> dict[str, Any] | None:
        other = need_audit(other_id) if other_id else (None if audit.get("analysis") else store.previous_audit(audit))
        if other is None:
            return None
        if other["id"] == audit["id"] or other["project_id"] != audit["project_id"]:
            raise ApiError(409, "not_comparable", t("compare.other_site"))
        result = comparison.compare(load_report(audit), load_report(other), new_affected=affected(audit["id"]),
                                    old_affected=affected(other["id"]), caps=(MODES[audit["mode"]], MODES[other["mode"]]))
        return {"audit_id": audit["id"], "compared_with": other["id"], **result}

    @api.get("/audits/{audit_id}/comparison", summary="Against the previous audit of the same site, or one you name")
    def compare(audit_id: str, with_: str = Query(default="", alias="with", max_length=32)) -> dict[str, Any]:
        result = compare_with(need_audit(audit_id), with_ or None)
        if result is None:
            raise ApiError(404, "no_previous_audit", t("follow.compare.none"))
        return result

    def message_view(message: dict[str, Any]) -> dict[str, Any]:
        out = dict(message)
        if message["kind"] == "plan":
            plan = store.plan(message["body"].get("plan_id", ""))
            out["plan"] = plan_view(plan) if plan else None
        return out

    @api.get("/audits/{audit_id}/conversation", summary="The saved messages and cards of one audit")
    def conversation(audit_id: str) -> dict[str, Any]:
        audit = need_audit(audit_id)
        return {"audit": audit_view(audit), "messages": ([{"role":"assistant", "kind":"audit", "body":{}}] if audit.get("analysis") else [message_view(m) for m in store.messages(audit["id"])])}

    @api.post("/audits/{audit_id}/messages", status_code=201, summary="Ask a supported question about this audit")
    def say(audit_id: str, body: MessageIn) -> dict[str, Any]:
        audit = need_audit(audit_id)
        text = body.text.strip()
        asked = store.add_message(audit["id"], "user", "text", {"text": text})
        if is_active(audit):
            reply = {"intent": "running", "text": t("chat.job_running", url=audit["url"],
                                                    pages=audit["progress"].get("pages_checked", 0)), "items": []}
        elif not report_path(audit["id"]).is_file():
            reply = {"intent": "no_report", "text": t("chat.no_report"), "items": []}
        else:
            report = load_report(audit)
            context = followups.AssistantContext(
                view=result_view(audit, report), report=report, compare=lambda: compare_with(audit, None),
                affected=lambda finding_id: affected(audit["id"]).get(finding_id) or [])
            reply = assistant.answer(text, context)
        answered = store.add_message(audit["id"], "assistant", "answer", reply)
        return {"messages": [asked, answered]}

    # -- client reports: editable sidecar, never a replacement for saved audit evidence ------------

    def client_workspace(audit_id: str):
        audit = need_audit(audit_id)
        if is_active(audit):
            raise ApiError(409, "audit_active", "Wait until the audit finishes / Denetimin bitmesini bekleyin.")
        return audit, client_reports.Workspace(artifact_folder(audit_id), load_report(audit), audit_id)

    def client_call(action):
        """The workspace's own messages reach the page; an operating-system error's text (which can name a file on this
        computer, with the user's name in its path) goes only to the server log (D-18)."""
        def said(exc: Exception, fallback: str) -> str:
            if isinstance(exc, OSError) and (exc.filename is not None or exc.errno is not None):
                logging.getLogger("maya_audit_web").warning("client report: %r", exc)
                return fallback
            return str(exc)
        try:
            return action()
        except client_reports.Conflict as exc:
            raise ApiError(409, "client_report_conflict", str(exc)) from None
        except FileNotFoundError as exc:
            raise ApiError(404, "client_report_missing", said(exc, "Generate a client draft first / Önce müşteri taslağını oluşturun.")) from None
        except ValueError as exc:
            raise ApiError(422, "client_report_invalid", str(exc)) from None

    @api.post("/audits/{audit_id}/client-report", summary="Create an evidence-only client draft; no paid requests")
    def create_client_report(audit_id: str):
        audit, workspace = client_workspace(audit_id)
        def create():
            if workspace.path.exists():
                return client_reports.public(workspace.load())
            previous = None if audit.get("analysis") else store.previous_audit(audit)
            previous_report = None
            if previous and report_path(previous['id']).is_file() and not is_active(previous):
                previous_report = load_report(previous)
            # Existing read-only panel shaping; this path never calls the providers.
            report = workspace.report
            work = workspace.create(previous=previous_report, affected=affected(audit_id),
                performance={"backlinks": report.get("dataforseo"),
                             "crux": summary.speed_view(report.get("crux") or crux.unavailable())})
            return client_reports.public(work)
        return client_call(create)

    @api.get("/audits/{audit_id}/client-report")
    def get_client_report(audit_id: str):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.public(workspace.load()))

    @api.put("/audits/{audit_id}/client-report/summary")
    def edit_client_summary(audit_id: str, body: ClientSummaryIn):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.public(workspace.update(body.revision,
            lambda w: client_reports.edit(w, summary=body.model_dump(exclude={'revision'})))))

    @api.put("/audits/{audit_id}/client-report/cards/{card_id}")
    def edit_client_card(audit_id: str, card_id: str, body: ClientCardIn):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.public(workspace.update(body.revision,
            lambda w: client_reports.edit(w, card_id=card_id, fields=body.model_dump(exclude={'revision'})))))

    @api.put("/audits/{audit_id}/client-report/notes")
    def edit_client_notes(audit_id: str, body: ClientNotesIn):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.public(workspace.update(body.revision,
            lambda w: client_reports.edit_notes(w, body.model_dump(exclude={'revision'})))))

    @api.post("/audits/{audit_id}/client-report/review")
    def review_client_report(audit_id: str, body: ClientReviewIn):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.public(workspace.update(body.revision,
            lambda w: client_reports.review(w, body.reviewer, body.reason))))

    @api.post("/audits/{audit_id}/client-report/validate")
    def validate_client_report(audit_id: str):
        _, workspace = client_workspace(audit_id)
        return client_call(lambda: client_reports.validation(workspace.load()))

    @api.get("/audits/{audit_id}/client-report/preview", response_class=HTMLResponse)
    def preview_client_report(audit_id: str):
        _, workspace = client_workspace(audit_id)
        html = client_call(lambda: client_reports.html(workspace.load(), draft=True))
        return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @api.get("/audits/{audit_id}/client-report/export/{format}")
    def export_client_report(audit_id: str, format: str, mode: str = Query(default="draft", pattern="^(draft|final)$"), full: bool = False):
        if format not in ('html', 'pdf', 'json'):
            raise ApiError(404, "not_found", "Choose HTML, PDF or evidence JSON.")
        audit, workspace = client_workspace(audit_id)
        if mode == "final":  # a client report built on a blocked audit report is never delivered as final (DECISIONS 280)
            publishable(audit)
        work = client_call(workspace.load)
        if format == 'json':
            return JSONResponse(client_reports.public(work), headers={"Content-Disposition": f'attachment; filename="maya-client-{audit_id}-evidence.json"'})
        html = client_call(lambda: client_reports.html(work, draft=mode == "draft", full=full))
        if format == 'pdf':
            try:
                content = pdf.to_pdf(html, footer_title="Maya · " + ("TASLAK / DRAFT" if mode == 'draft' else "İncelenmiş / Reviewed"), max_pages=None if full else 50)
            except pdf.PdfUnavailable as exc:
                # The page-limit message is the app's own; the browser's first line can name its install folder, so it
                # goes to the server log only (D-18).
                logging.getLogger("maya_audit_web").warning("client PDF unavailable: %s", exc)
                said = str(exc) if isinstance(exc, pdf.PdfPageLimit) else t("result.pdf_unavailable")
                raise ApiError(503, "pdf_unavailable", said + " Please use HTML (compact) and companion JSON; exhaustive evidence is available with full=true / HTML ve JSON ekini kullanın.") from None
        else:
            content = html
        return Response(content, media_type='application/pdf' if format == 'pdf' else 'text/html; charset=utf-8',
            headers={"Content-Disposition": f'attachment; filename="maya-client-{audit_id}-{mode}{"-full-evidence" if full else ""}.{format}"',
                     "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    # -- projects --------------------------------------------------------------------------------

    def need_project(project_id: str) -> str:
        project_id = project_id.lower()
        if not _PROJECT_ID.fullmatch(project_id) or "." not in project_id:
            raise ApiError(404, "project_not_found", t("error.project_not_found"))
        return project_id

    @api.get("/projects/{project_id}/profile", summary="What the person confirmed about this business")
    def get_profile(project_id: str) -> dict[str, Any]:
        return profile_of(need_project(project_id))

    @api.put("/projects/{project_id}/profile", summary="Save the confirmed business context and important pages")
    def put_profile(project_id: str, body: ProfileIn) -> dict[str, Any]:
        project_id = need_project(project_id)
        scheme = "http" if engine.allow_loopback and chat.is_loopback_host(project_id) else "https"
        try:
            key_pages = chat.key_page_urls(f"{scheme}://{project_id}/", body.key_pages, MAX_KEY_PAGES)
        except ValueError as exc:
            raise ApiError(422, "invalid_key_pages", str(exc)) from None
        clean = lambda values: [v.strip()[:80] for v in values if v.strip()]  # noqa: E731
        family = (brand_family(body.brand_family_domains) if body.brand_family_domains is not None
                  else brand_family(profile_of(project_id).get("brand_family_domains")))
        store.save_profile(project_id, {"brand_name": body.brand_name.strip(), "industry": body.industry.strip(),
                                        "goals": clean(body.goals), "countries": clean(body.countries),
                                        "languages": clean(body.languages), "key_pages": key_pages,
                                        "brand_family_domains": family,
                                        **{key: (list(dict.fromkeys(v.strip() for v in getattr(body, key) if v.strip())) if getattr(body, key) is not None else profile_of(project_id).get(key, []))
                                           for key in ("brand_aliases", "related_organizations")
                                           if getattr(body, key) is not None or key in profile_of(project_id)}})
        return profile_of(project_id)

    # -- the page --------------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> Response:
        response = FileResponse(STATIC / "index.html", media_type="text/html; charset=utf-8",
                                headers={"Cache-Control": "no-store"})
        guard.set_cookie(response)
        return response

    app.include_router(api)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


__all__ = ["create_app", "Engine"]
