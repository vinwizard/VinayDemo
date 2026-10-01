"""Safe public-URL fetcher for onboarding (.claude/skills/product-workflow).

Fetching a URL a user supplies is an SSRF primitive: without care it can be pointed at
127.0.0.1, a private LAN host, or a cloud metadata endpoint. Protections here:

  * only http/https, no other scheme
  * the hostname is resolved ONCE, every resolved address is checked, and the connection is made
    to that validated address — so a name that re-resolves to 127.0.0.1 between the check and the
    connect (DNS rebinding) cannot win
  * private, loopback, link-local, reserved, multicast and CGNAT ranges are refused, which covers
    169.254.169.254 and friends
  * each redirect target is validated again, at most two hops
  * 10s timeout, 1 MiB body cap, 12,000 characters of extracted text

Fetched page text is untrusted DATA. It is stored as an evidence excerpt and never treated as
instructions to anything downstream.
"""
import contextlib
import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

TIMEOUT = 10
MAX_BYTES = 1024 * 1024
MAX_CHARS = 12_000
MAX_REDIRECTS = 2
USER_AGENT = "OffMessage/0.1 (+research; contact via repository)"
ALLOWED_SCHEMES = ("http", "https")
HTML = "text/html,application/xhtml+xml"
EMPTY = "{url} shows no text until script runs in a browser, so there is nothing to read"


class UnsafeURL(ValueError):
    pass


class FetchError(RuntimeError):
    """A page that could not be read, said in plain words: the message is shown to the user as is."""


def _check_ip(raw: str) -> ipaddress._BaseAddress:
    ip = ipaddress.ip_address(raw)
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise UnsafeURL(f"refusing non-public address {raw}")
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):  # CGNAT
        raise UnsafeURL(f"refusing carrier-grade NAT address {raw}")
    return ip


def resolve_public(host: str, port: int) -> str:
    """-> one validated public IP. Raises if ANY resolved address is non-public.

    Checking every answer, not just the first, stops a name that returns both a public and a
    private address from sneaking through.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FetchError(f"there is no website at {host} (its name cannot resolve)") from e
    if not infos:
        raise FetchError(f"there is no website at {host} (its name cannot resolve)")
    addrs = [info[4][0] for info in infos]
    for a in addrs:
        _check_ip(a)
    return addrs[0]


def validate(url: str) -> tuple[str, str, int, str]:
    """-> (scheme, host, port, path_with_query). Raises UnsafeURL on anything not publicly routable."""
    u = urlparse(url if "://" in url else "https://" + url)
    if u.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"scheme {u.scheme!r} is not allowed")
    if not u.hostname:
        raise UnsafeURL("no hostname")
    host = u.hostname
    if "." not in host:
        raise UnsafeURL(f"refusing hostname without a dot: {host!r}")
    try:                                    # a literal IP is checked directly
        _check_ip(host)
    except ValueError as e:
        if isinstance(e, UnsafeURL):
            raise
    port = u.port or (443 if u.scheme == "https" else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    return u.scheme, host, port, path


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    # tags that start a new block of text: headings and paragraphs split passages (retrieval.py)
    BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "section", "article", "br", "tr",
             "blockquote", "header", "footer", "nav", "main", "aside", "dd", "dt", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _parts(html: str) -> list[str]:
    p = _Text()
    with contextlib.suppress(Exception):    # malformed markup: keep whatever parsed
        p.feed(html)
    return p.parts


def extract_text(html: str) -> str:
    return re.sub(r"\s+", " ", " ".join(_parts(html))).strip()[:MAX_CHARS]


def extract_blocks(html: str, max_chars: int = 3 * MAX_CHARS) -> list[str]:
    """The page's readable text as blocks — one per heading, paragraph or list item — in order."""
    blocks, total = [], 0
    for b in " ".join(_parts(html)).split("\n"):
        b = re.sub(r"\s+", " ", b).strip()
        if b and total < max_chars:
            blocks.append(b)
            total += len(b)
    return blocks


def robots_allow(url: str, timeout: float = TIMEOUT) -> bool:
    """Whether the site's robots.txt lets this fetcher read `url`. No robots.txt (a 4xx) allows
    everything; one that cannot be read raises, and the caller skips the page."""
    u = urlparse(url)
    try:
        _, body = fetch_raw(f"{u.scheme}://{u.netloc}/robots.txt", timeout)
    except FetchError as e:
        if re.search(r"HTTP 4\d\d", str(e)):
            return True
        raise
    rules = RobotFileParser()
    rules.parse(body.splitlines())
    return rules.can_fetch(USER_AGENT, url)


def _plain(e: Exception, host: str, timeout: float) -> FetchError:
    """A connection failure in words a user can act on. Uncaught, a timeout or a bad certificate
    reached the page as "Onboarding failed: TimeoutError"."""
    if isinstance(e, ssl.SSLCertVerificationError):
        return FetchError(f"{host} has a security certificate that is not valid ({e.verify_message})")
    if isinstance(e, ssl.SSLError):
        return FetchError(f"{host} could not set up a secure connection")
    if isinstance(e, TimeoutError):
        return FetchError(f"{host} did not answer within {timeout:g} seconds")
    if isinstance(e, http.client.HTTPException):
        return FetchError(f"{host} sent a reply that is not a web page")
    return FetchError(f"could not connect to {host}")


def _get(scheme: str, host: str, port: int, path: str, timeout: float = TIMEOUT,
         accept: str = HTML) -> tuple[int, dict, bytes]:
    ip = resolve_public(host, port)          # validated, and we connect to THIS address
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except OSError as e:
        raise _plain(e, host, timeout) from e
    try:
        if scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)   # SNI + cert check use the name
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        conn.request("GET", path, headers={"Host": host, "User-Agent": USER_AGENT, "Accept": accept})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read(MAX_BYTES)
    except (OSError, http.client.HTTPException) as e:
        raise _plain(e, host, timeout) from e
    finally:
        with contextlib.suppress(Exception):
            sock.close()


def request(url: str, timeout: float = TIMEOUT, accept: str = HTML) -> tuple[str, int, str, str]:
    """-> (final_url, status, content_type, body). Follows at most MAX_REDIRECTS, revalidating every
    hop. Any final status comes back rather than raising: a 404 robots.txt is an answer, not a failure."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = validate(current)
        status, headers, body = _get(scheme, host, port, path, timeout, accept)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("Location") or headers.get("location")
            if not location:
                raise FetchError(f"{status} with no Location header")
            current = urljoin(current, location)   # revalidated at the top of the next iteration
            continue
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        return current, status, ctype, body.decode("utf-8", errors="replace")
    raise FetchError(f"too many redirects from {url}")


def status_problem(status: int, url: str) -> str:
    """Why a page that answered did not count, keeping "HTTP <status>" in it (robots_allow reads it).
    A 403 is almost always a bot wall (Cloudflare's "verify you are human"), not a missing page."""
    if status in (401, 403, 429):
        return f"{urlparse(url).hostname} turns automated readers away (HTTP {status} for {url})"
    if status in (404, 410):
        return f"there is no page at {url} (HTTP {status})"
    return f"{url} answered HTTP {status}"


def fetch_raw(url: str, timeout: float = TIMEOUT, types: tuple[str, ...] = ("html", "text")) -> tuple[str, str]:
    """-> (final_url, raw_html). `types`: what the content type must contain. Any text by default,
    for robots.txt; a page of the company's site passes ("html",), since text/css is text too."""
    final, status, ctype, html = request(url, timeout)
    if status != 200:
        raise FetchError(status_problem(status, final))
    if not any(t in ctype for t in types):
        raise FetchError(f"{final} is not a web page (unsupported content type {ctype!r})")
    return final, html


def fetch(url: str) -> tuple[str, str]:
    """-> (final_url, extracted_text). HTML only: a stylesheet or script is not a page."""
    final, html = fetch_raw(url, types=("html",))
    text = extract_text(html)
    if not text:
        raise FetchError(EMPTY.format(url=final))
    return final, text


class _Links(HTMLParser):
    """Links a reader clicks, with the words on them: <a href> only. A <link rel="stylesheet"> is
    not a page, and a data-href is not a link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._open: Optional[list] = None

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href") if tag == "a" else None
        if href:
            self._open = [href, []]
            self.links.append(("", ""))           # filled at </a>, in document order

    def handle_data(self, data):
        if self._open:
            self._open[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._open:
            self.links[-1] = (self._open[0], " ".join(" ".join(self._open[1]).split()))
            self._open = None


def _links(html_text: str) -> list[tuple[str, str]]:
    p = _Links()
    with contextlib.suppress(Exception):    # malformed markup: keep whatever parsed
        p.feed(html_text)
    return [(h, t) for h, t in p.links if h]


# What a page is, read from its path and the words on the link to it, most important first: where a
# company says who it is and what it offers. Matching is on whole words, and a word must name the
# page, not appear somewhere in a story's slug: "why" in /stories/…/why-mrbeast-…-joined-forces sent
# the amgen.com crawl to a press story, and "ai" inside "CorporateAffairs" once sent it to stylesheets.
PAGE_KINDS = (
    ("about", {"about", "company", "who", "overview", "story"}),
    ("mission", {"mission", "values", "purpose", "vision"}),
    ("offer", {"products", "product", "solutions", "solution", "platform", "services", "what",
               "features", "medicines", "therapies", "capabilities"}),
    ("why", {"why"}),
    ("newsroom", {"newsroom", "press", "media", "news"}),
    ("customers", {"customers", "customer", "case"}),
    ("pricing", {"pricing", "plans"}),
    ("enterprise", {"enterprise"}),
    ("ai", {"ai"}),
)
RANK = {kind: i for i, (kind, _) in enumerate(PAGE_KINDS)}
# Pages about something other than the company itself: articles, campaigns, jobs, legal, accounts.
SKIP = {"stories", "blog", "blogs", "article", "articles", "post", "posts", "events", "event",
        "webinar", "webinars", "campaign", "campaigns", "careers", "career", "jobs", "legal", "privacy",
        "terms", "cookies", "cookie", "login", "signin", "signup", "register", "contact", "support",
        "help", "docs", "search", "cart", "account", "tag", "tags", "category", "author", "investors",
        "podcast", "podcasts", "videos", "video", "releases", "release", "downloads", "download"}
MAX_DEPTH = 2
YEAR = re.compile(r"(?:19|20)\d\d")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def page_kind(path: str, link_text: str = "") -> Optional[str]:
    """The kind of page a same-site path is, from PAGE_KINDS, or None when it is not one worth
    reading. The deepest segment decides first ("/about/mission-and-values" is the mission page);
    the link's own words decide when the path says nothing ("/company/leadership" labelled
    "Our purpose"). A newsroom counts only as the section's own page, never one of its stories."""
    segments = [x for x in path.lower().strip("/").split("/") if x]
    if not segments or len(segments) > MAX_DEPTH or any(YEAR.search(x) for x in segments) \
            or segments[-1].endswith((".xml", ".pdf", ".css", ".js")) \
            or any(set(_words(x)) & SKIP for x in segments):
        return None
    if len(_words(segments[-1])) > 5:          # a sentence for a slug is an article, whatever it sits under
        return None
    for words in [_words(x) for x in reversed(segments)] + [_words(link_text)]:
        for kind, keys in PAGE_KINDS:
            if kind == "newsroom" and len(segments) > 1:
                continue
            if kind in ("why", "ai") and (len(segments) > 1 or words[:1] != [next(iter(keys))]):
                continue                        # "/why-linear" and "/ai" are pages; "…-why-…" is not
            if set(words) & keys:
                return kind
    return None


def positioning_links(base_url: str, html_text: str, limit: int = 2,
                      extra: Iterable[str] = ()) -> list[str]:
    """Same-site pages most likely to say how the company positions itself, most important first:
    about, mission and values, what it offers, "why us", the newsroom's own page, then customers,
    pricing, enterprise. One of each kind before a second of any. `extra` are more candidate URLs
    (a sitemap's), considered after the homepage's own links."""
    base = urlparse(base_url if "://" in base_url else "https://" + base_url)
    seen, found = {base.path.rstrip("/") or "/"}, []
    for n, (href, text) in enumerate([*_links(html_text), *((u, "") for u in extra)]):
        target = urlparse(urljoin(f"{base.scheme}://{base.netloc}", href))
        if target.netloc != base.netloc or target.scheme not in ALLOWED_SCHEMES:
            continue
        path = target.path.rstrip("/") or "/"
        if path in seen or not (kind := page_kind(path, text)):
            continue
        seen.add(path)
        found.append((kind, path.count("/"), n, f"{target.scheme}://{target.netloc}{path}"))
    per_kind: dict[str, int] = {}
    ordered = []
    for kind, depth, n, url in sorted(found, key=lambda f: (RANK[f[0]], f[1], f[2])):
        per_kind[kind] = per_kind.get(kind, 0) + 1
        ordered.append((per_kind[kind], RANK[kind], depth, n, url))
    return [f[-1] for f in sorted(ordered)][:limit]


SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def sitemap_urls(origin: str) -> list[str]:
    """The page URLs a site's /sitemap.xml lists, or [] when it has none or it cannot be read. A
    sitemap index lists more sitemaps, not pages; page_kind skips those."""
    try:
        _, body = fetch_raw(f"{origin}/sitemap.xml", types=("xml", "text"))
    except (UnsafeURL, FetchError):
        return []
    return SITEMAP_LOC.findall(body)[:5000]


class _Icons(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[set[str], str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("href"):
            self.links.append((set((a.get("rel") or "").lower().split()), a["href"]))


def icon_url(base_url: str, html_text: str) -> Optional[str]:
    """The site's own icon: apple-touch-icon, then any icon link, then /favicon.ico.

    Only an absolute http(s) URL is returned — the browser loads it as an <img>, so a data:,
    javascript: or relative href never reaches the page as-is.
    """
    parser = _Icons()
    parser.feed(html_text)
    hrefs = ([h for rel, h in parser.links if "apple-touch-icon" in rel]
             + [h for rel, h in parser.links if "icon" in rel] + ["/favicon.ico"])
    for href in hrefs:
        u = urljoin(base_url, href.strip())
        if urlparse(u).scheme in ALLOWED_SCHEMES:
            return u
    return None


def fetch_site(url: str, max_pages: int = 3) -> tuple[list[tuple[str, str]], Optional[str]]:
    """-> (pages, icon URL). The homepage plus up to max_pages - 1 same-site pages that say how the
    company positions itself (positioning_links); individual page failures are skipped, not fatal.
    The icon comes from the homepage HTML already fetched — no extra request."""
    final, html = fetch_raw(url, types=("html",))  # one request; HTML reused for text, links AND the icon
    text = extract_text(html)
    if not text:
        raise FetchError(EMPTY.format(url=final))
    pages = [(final, text)]
    links = positioning_links(final, html, limit=max_pages - 1)
    if len(links) < max_pages - 1:            # the homepage links too few: read what the sitemap lists
        u = urlparse(final)
        links = positioning_links(final, html, limit=max_pages - 1,
                                  extra=sitemap_urls(f"{u.scheme}://{u.netloc}"))
    for link in links:
        try:
            pages.append(fetch(link))
        except (UnsafeURL, FetchError):
            continue                          # a missing sub-page is not fatal to onboarding
    return pages, icon_url(final, html)
