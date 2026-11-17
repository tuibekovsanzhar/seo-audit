from __future__ import annotations

import ipaddress
import re
import socket
from collections import defaultdict
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


class UnsafeTargetError(ValueError):
    """Raised when a URL resolves to a non-public address."""


class UnresolvedHostError(UnsafeTargetError):
    """The host's address could not be looked up at all (a DNS failure or timeout). Nothing is known to be unsafe
    about it; nothing was connected to either. Kept a subclass so every existing refusal still refuses."""


class LocalDnsError(UnresolvedHostError):
    """Nothing could be looked up from this computer: the system resolver failed and no public resolver could be
    reached. A statement about this computer's network, never about the website."""


class HostNotFoundError(UnresolvedHostError):
    """A resolver answered that the name has no address (a spelling mistake, most often)."""


# IPv6 ranges that carry an IPv4 address inside them (A7). On a network with NAT64, 64:ff9b::a9fe:a9fe reaches
# 169.254.169.254; Python calls such addresses global. The well-known prefix (RFC 6052) embeds the IPv4 address in its
# last 32 bits; the local-use prefix (RFC 8215) may place it anywhere, so an address there is refused outright.
_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL_USE = ipaddress.IPv6Network("64:ff9b:1::/48")


def _checked_address(address):
    """The address to judge for safety: the IPv4 address inside an IPv4-mapped, 6to4 or NAT64 IPv6 address, else the
    address itself. None for an address that cannot be judged (NAT64 local-use). The connection is still made to the
    address as resolved; only the judgement looks inside it."""
    if address.version != 6:
        return address
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address in _NAT64_WELL_KNOWN:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address in _NAT64_LOCAL_USE:
        return None
    return address


def public_addresses(url: str, *, allow_loopback: bool = True) -> list[str]:
    """Resolve once, reject mixed/private answers, and return addresses safe to connect to."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        raise UnsafeTargetError("expected an http(s) URL without credentials")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        # The system resolver, then DNS over HTTPS (maya_audit.resolver). Whoever answers, the addresses are checked
        # below and the connection is made to exactly those addresses (maya_audit.network).
        from . import resolver
        try:
            found = resolver.resolve(host, parts.port or (443 if parts.scheme == "https" else 80))
            addresses = [ipaddress.ip_address(item.split("%", 1)[0]) for item in found.addresses]
        except resolver.LookupFailed as exc:
            kind = {"local": LocalDnsError, "not_found": HostNotFoundError}.get(exc.kind, UnresolvedHostError)
            raise kind(exc.detail) from exc
        except ValueError as exc:
            raise UnresolvedHostError(f"{host} resolved to something that is not an address") from exc
    if not addresses:
        raise UnsafeTargetError(f"host did not resolve to an address: {host}")
    checked = [(a, _checked_address(a)) for a in addresses]
    unsafe = [a for a, inner in checked if inner is None or not (inner.is_global or (allow_loopback and inner.is_loopback))]
    if unsafe:
        raise UnsafeTargetError(f"refusing non-public destination {host}")
    return list(dict.fromkeys(map(str, addresses)))


def validate_public_target(url: str, *, allow_loopback: bool = True) -> None:
    """Validate all resolved addresses; PublicTransport pins the actual connection too."""
    public_addresses(url, allow_loopback=allow_loopback)


def remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4: `/a/../b` is `/b`. The HTTP client sends the resolved path, so the URL judged
    against robots.txt, keyed in the frontier and logged must be the resolved one too."""
    if "." not in path:
        return path
    out: list[str] = []
    segments = path.split("/")
    for i, segment in enumerate(segments):
        if segment == ".":
            if i == len(segments) - 1:
                out.append("")
            continue
        if segment == "..":
            if len(out) > 1:
                out.pop()
            if i == len(segments) - 1:
                out.append("")
            continue
        out.append(segment)
    resolved = "/".join(out)
    return resolved if resolved.startswith("/") else "/" + resolved


def _sendable(url: str) -> bool:
    """Whether the HTTP client can send this URL at all. A control character, a bad IDN label or a lone surrogate
    makes httpx raise before any request; such a link is one bad link, never a reason to stop the crawl."""
    import httpx

    try:
        httpx.URL(url)
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return False
    return True


def normalize_url(href: str, base: str | None = None) -> str | None:
    """Resolve `href` against `base` and normalize it; None if not http(s) or not sendable."""
    href = href.strip()
    if not href:
        return None
    absolute = urljoin(base, href) if base else href
    try:
        parts = urlsplit(absolute)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    if not host:
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = upper_escapes(remove_dot_segments(parts.path or "/"))
    normalized = urlunsplit((scheme, netloc, path, upper_escapes(parts.query), ""))
    return normalized if _sendable(normalized) else None


_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")


def upper_escapes(text: str) -> str:
    """Percent-escapes in upper case (RFC 3986 6.2.2.1): `%cc%87` and `%CC%87` are the same octets, so one address
    for page identity, grouping and importance (DECISIONS 305). Nothing else in the address changes."""
    return _ESCAPE.sub(lambda m: m.group(0).upper(), text or "")


# What an address that is not a web page is, by its path: checked before a reader is asked for it, and wherever a
# report lists "pages" (a sitemap file or a PDF is not one).
_IMAGE_ENDINGS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp")
_MEDIA_ENDINGS = (".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".oga", ".ogv", ".webm", ".mov", ".avi", ".flac", ".aac")
_DOCUMENT_ENDINGS = (".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".rar", ".gz", ".xml")


def non_page_kind(url: str) -> str | None:
    """"sitemap", "robots", "document" or "image" for an address that is a file rather than a page; None for a page.

    Judged from the path alone (no request): robots.txt, an .xml file with "sitemap" in its name (also .xml.gz), an
    image file, or a document (PDF, an archive, an office file, any other .xml such as a feed)."""
    path = urlsplit(url or "").path.lower()
    name = path.rsplit("/", 1)[-1]
    if path == "/robots.txt":
        return "robots"
    if name.endswith((".xml", ".xml.gz")) and "sitemap" in name:
        return "sitemap"
    if name.endswith(_IMAGE_ENDINGS):
        return "image"
    if name.endswith(_MEDIA_ENDINGS):
        return "media"
    if name.endswith(_DOCUMENT_ENDINGS):
        return "document"
    return None


# Query parameters that only track a visit or carry a session (A2). Two links that differ only in these lead to the
# same page; the crawl asks for it once. The report keeps each link as the page wrote it.
_TRACKING_PARAMETERS = frozenset({"gclid", "fbclid", "jsessionid", "msclkid", "dclid", "yclid", "mc_cid", "mc_eid"})
_PATH_SESSION = re.compile(r";jsessionid=[^/?#]*", re.I)


def _tracking(key: str) -> bool:
    key = key.lower()
    return key.startswith("utm_") or key in _TRACKING_PARAMETERS or "sessid" in key


# DECISIONS 351 (isbank: /?efl--edit=1, a CMS edit-mode address of the homepage, was read as a page of its own): query
# parameters that open a page in a CMS's edit or preview mode. The address is the clean page, not another page.
EDIT_PREVIEW_PARAMETERS = frozenset({
    "edit", "editmode", "preview", "preview_id", "preview_nonce", "preview_theme_id", "_preview", "preview_mode",
    "elementor-preview", "vc_editable", "et_fb", "fl_builder", "customize_changeset_uuid", "customize_theme",
    "wcmmode", "designmode", "pb-preview", "sitecore_mode", "sc_mode", "_storyblok", "cms_preview", "draft"})


def _edit_key(key: str) -> bool:
    key = key.lower()
    return key in EDIT_PREVIEW_PARAMETERS or key.endswith("--edit") or key.endswith("-preview")


def edit_preview(url: str | None) -> bool:
    """True for an address with a CMS edit or preview parameter (?efl--edit=1, ?preview=true, ?preview_theme_id=)."""
    try:
        query = urlsplit(url or "").query
    except ValueError:
        return False
    return any(_edit_key(pair.split("=", 1)[0]) for pair in query.split("&") if pair)


def without_edit_preview(url: str) -> str:
    """The address with its edit and preview parameters taken off (the clean page)."""
    parts = urlsplit(url)
    pairs = [pair for pair in parts.query.split("&") if pair and not _edit_key(pair.split("=", 1)[0])]
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "&".join(pairs), ""))


def crawl_identity(url: str) -> str:
    """The key under which the crawl counts `url` as already seen (A2): tracking and session parameters taken off
    (`utm_*`, gclid, fbclid, `*sessid*`, `;jsessionid=` in the path) and the rest put in a fixed order. Never sent: the
    address that is asked for, and reported, is the one the page wrote."""
    parts = urlsplit(url)
    path = _PATH_SESSION.sub("", parts.path)
    pairs = [pair for pair in parts.query.split("&") if pair and not _tracking(pair.split("=", 1)[0])]
    return urlunsplit((parts.scheme, parts.netloc, path, "&".join(sorted(pairs)), ""))


def lock_key(url: str) -> str:
    """The site an audit locks against another audit of it (A12): the host without "www.", with a port that is not the
    default. http://e.com and https://www.e.com are one site (the start redirect moves between them), but two subdomains,
    or two loopback servers on two ports, are not."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".").removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port and port != _DEFAULT_PORTS.get(parts.scheme) else host


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def same_origin(a: str, b: str) -> bool:
    return origin_of(a) == origin_of(b)


def request_target(url: str) -> str:
    """Path plus query, the part robots.txt rules are matched against."""
    parts = urlsplit(url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def is_loopback_host(host: str) -> bool:
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):  # RFC 6761: *.localhost is loopback
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Multi-label public suffixes, so "example.com.tr" is read as a registrable domain and
# "user.github.io" is not. Not the full Public Suffix List: the common country-code pairs plus the
# multi-tenant hosts a site is most likely to be published on.
MULTI_LABEL_SUFFIXES = frozenset({
    "com.tr", "net.tr", "org.tr", "gov.tr", "edu.tr", "bel.tr", "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.jp", "com.au", "net.au", "org.au", "co.nz", "com.br", "com.mx", "com.ar", "co.za", "com.sg",
    "co.in", "com.cn", "co.kr", "com.es", "com.pl", "com.ua", "co.il", "com.sa", "com.hk",
})
HOSTING_SUFFIXES = frozenset({
    "github.io", "gitlab.io", "netlify.app", "vercel.app", "pages.dev", "web.app", "firebaseapp.com",
    "herokuapp.com", "azurewebsites.net", "appspot.com", "onrender.com", "fly.dev", "surge.sh",
    "blogspot.com", "wordpress.com", "myshopify.com", "webflow.io", "squarespace.com", "wixsite.com",
})


def is_registrable_domain(host: str) -> bool:
    """True for "example.com" or "example.com.tr"; False for "blog.example.com" or "user.github.io".

    A `www.` counterpart only means something for the domain a person would type or link. For a host
    that is already a subdomain, "www.<that host>" is not an address anyone uses, and a certificate
    covering `*.github.io` cannot cover it either (wildcards match one label), so checking it produces
    a failure that is true and meaningless.
    """
    host = host.strip("[]").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2:
        return False
    if ".".join(labels[-2:]) in HOSTING_SUFFIXES:
        return False  # user.github.io: the registrable domain belongs to the host, not the site
    suffix_labels = 2 if ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES else 1
    return len(labels) == suffix_labels + 1


def registrable_domain(host: str) -> str:
    """Reduce a host to the name someone registers: "blog.example.com.tr" -> "example.com.tr".

    Shares the suffix tables with `is_registrable_domain` so the two can never disagree about
    where a site's boundary is. A hosting suffix keeps three labels, because on those hosts the
    site boundary is the user's own label ("user.github.io"), not the platform's domain — two
    unrelated projects on github.io are not the same site.

    Returns the host unchanged when it is an IP address or a single label; callers treat that as
    "cannot be reduced" rather than as an error.
    """
    host = host.strip("[]").lower().rstrip(".")
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2:
        return host
    last_two = ".".join(labels[-2:])
    keep = 3 if last_two in HOSTING_SUFFIXES or last_two in MULTI_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:]) if len(labels) >= keep else host


def host_allowed(url: str, allowed_live_hosts: frozenset[str]) -> bool:
    """Loopback is always allowed; live hosts only when explicitly listed.

    A listed host also allows its `www.` counterpart, since apex <-> www
    redirects are routine.
    """
    host = (urlsplit(url).hostname or "").lower()
    if is_loopback_host(host):
        return True
    allowed = {h.lower() for h in allowed_live_hosts}
    bare = host.removeprefix("www.")
    return host in allowed or bare in allowed or f"www.{bare}" in allowed


def is_allowed_origin_move(old: str, new: str) -> bool:
    """Start-URL redirects that may re-anchor the crawl origin.

    Allowed: http -> https on the same host, and apex <-> www without leaving https (A8): a move from https to http
    would send every later request unencrypted.
    """
    o, n = urlsplit(old), urlsplit(new)
    old_host, new_host = (o.hostname or ""), (n.hostname or "")
    same_host = old_host == new_host
    www_pair = old_host.removeprefix("www.") == new_host.removeprefix("www.")
    if same_host:
        return o.scheme == "http" and n.scheme == "https"
    return www_pair and not (o.scheme == "https" and n.scheme == "http")


_VARIABLE_SEGMENT = re.compile(
    r"""^(
        \d+                                        # numeric id
      | [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}  # uuid
      | [0-9a-f]{16,}                              # long hex id
      | .*\d.*                                     # any segment containing a digit
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


_PAGE_PARAMETERS = frozenset({"page", "sayfa", "p", "pg", "paged", "pagenum", "pagenumber", "page_no", "pageno", "sf",
                              "offset", "start", "skip"})
_PAGE_PATH = re.compile(r"/(?:page|sayfa|p)/\d+/?$", re.I)


def is_pagination(url: str) -> bool:
    """Page 2, 3, ... of a list: `?sayfa=2`, `?page=3`, `/page/4/`. The same template as page 1 with other rows."""
    parts = urlsplit(url)
    if _PAGE_PATH.search(parts.path):
        return True
    for pair in parts.query.split("&"):
        key, _, value = pair.partition("=")
        if key.lower() in _PAGE_PARAMETERS and value.isdigit():
            return True
    return False


def listing_view_of(url: str, target: str) -> str | None:
    """How `url` is a view of the list at `target`, or None (review G01): "parameters" when both share host and path and
    the target's query is empty or a subset of the page's (a filter, sort, facet or session parameter added to the list:
    `/blog/?filter=best` -> `/blog/`, `/kadin?renk=siyah&sort=price` -> `/kadin?renk=siyah`); "pagination" when `url`
    is page 2+ (`is_pagination`) and the target is page 1 of the same list (`/blog/page/2/` -> `/blog/`,
    `/c?page=2` -> `/c`). A canonical from such a view to its list is ordinary consolidation, not a page handing its
    own content to another. Trailing slashes are ignored; another path is never a view."""
    try:
        page, list_ = urlsplit(url), urlsplit(target)
        same_server = (page.hostname or "").lower() == (list_.hostname or "").lower() and page.port == list_.port
    except ValueError:
        return None
    if not same_server:
        return None
    page_path, list_path = page.path.rstrip("/") or "/", list_.path.rstrip("/") or "/"
    page_query = set(parse_qsl(page.query, keep_blank_values=True))
    list_query = set(parse_qsl(list_.query, keep_blank_values=True))
    if is_pagination(url):
        first_page = _PAGE_PATH.sub("", page.path).rstrip("/") or "/"
        unpaged = {(k, v) for k, v in page_query if not (k.lower() in _PAGE_PARAMETERS and v.isdigit())}
        return "pagination" if list_path in (page_path, first_page) and list_query <= unpaged else None
    if page_path == list_path and list_query < page_query:
        return "parameters"
    return None


def section_key(url: str) -> str:
    """A rough "which part of the site is this" key for one URL, used to spread a capped crawl.

    Unlike `detect_templates` it needs no other URLs: a segment containing a digit becomes `{id}`,
    and the last segment of a path two or more levels deep becomes `*`. So `/tr/a-blog-post/` and
    `/tr/another/` share `/tr/*`, `/tr/services/x/` is `/tr/services/*`, and `/pricing` is itself.
    """
    segments = [s for s in urlsplit(url).path.split("/") if s]
    out = ["{id}" if _VARIABLE_SEGMENT.match(seg) else seg for seg in segments]
    if len(out) >= 2 and out[-1] != "{id}":
        out[-1] = "*"
    return "/" + "/".join(out)


def detect_templates(urls: list[str], min_siblings: int = 2) -> dict[str, list[str]]:
    """Group URLs into path templates. The grouping is an Estimate (spec §8 F8).

    A segment becomes a placeholder when it looks like an id (contains a digit,
    uuid, long hex), or when it is the last segment and its parent path has at
    least `min_siblings` distinct children.
    """
    split = {u: [s for s in urlsplit(u).path.split("/") if s] for u in urls}
    children: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for segments in split.values():
        if segments:
            children[tuple(segments[:-1])].add(segments[-1])

    groups: dict[str, list[str]] = defaultdict(list)
    for url, segments in split.items():
        out = []
        for i, seg in enumerate(segments):
            is_last = i == len(segments) - 1
            if _VARIABLE_SEGMENT.match(seg):
                out.append("{id}")
            elif is_last and len(children[tuple(segments[:-1])]) >= min_siblings and i > 0:
                out.append("{slug}")
            else:
                out.append(seg)
        groups["/" + "/".join(out)].append(url)
    return dict(groups)


_HOSTNAME = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")


def clean_hostname(text: str) -> str | None:
    """A domain name as a person may type it ("Example.com", "www.example.com."), lower-cased, or None when the text
    is anything else: an address with a scheme, a path, a port, spaces, an IP address or markup is refused, not
    repaired. Used for the brand-family domains (the command line and the web app's plan card)."""
    host = (text or "").strip().rstrip(".").lower()
    return host if _HOSTNAME.fullmatch(host) else None


def in_domain_family(host: str, domains) -> bool:
    """Whether `host` is one of `domains`, a subdomain of one, or shares its registrable domain with one."""
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    site = registrable_domain(host)
    for domain in domains or ():
        domain = (domain or "").lower().rstrip(".").removeprefix("www.")
        if domain and (host == domain or host.endswith("." + domain) or site == registrable_domain(domain)):
            return True
    return False

