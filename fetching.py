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
import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

TIMEOUT = 10
MAX_BYTES = 1024 * 1024
MAX_CHARS = 12_000
MAX_REDIRECTS = 2
USER_AGENT = "PositioningDrift/0.1 (+research; contact via repository)"
ALLOWED_SCHEMES = ("http", "https")


class UnsafeURL(ValueError):
    pass


class FetchError(RuntimeError):
    pass


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
        raise FetchError(f"cannot resolve {host}: {e}") from e
    if not infos:
        raise FetchError(f"cannot resolve {host}")
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

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def extract_text(html: str) -> str:
    p = _Text()
    try:
        p.feed(html)
    except Exception:
        pass                                # malformed markup: keep whatever parsed
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()[:MAX_CHARS]


def _get(scheme: str, host: str, port: int, path: str) -> tuple[int, dict, bytes]:
    ip = resolve_public(host, port)          # validated, and we connect to THIS address
    sock = socket.create_connection((ip, port), timeout=TIMEOUT)
    try:
        if scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)   # SNI + cert check use the name
        conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
        conn.sock = sock
        conn.request("GET", path, headers={"Host": host, "User-Agent": USER_AGENT,
                                           "Accept": "text/html,application/xhtml+xml"})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read(MAX_BYTES)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def fetch_raw(url: str) -> tuple[str, str]:
    """-> (final_url, raw_html). Follows at most MAX_REDIRECTS, revalidating every hop."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, path = validate(current)
        status, headers, body = _get(scheme, host, port, path)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("Location") or headers.get("location")
            if not location:
                raise FetchError(f"{status} with no Location header")
            current = urljoin(current, location)   # revalidated at the top of the next iteration
            continue
        if status != 200:
            raise FetchError(f"HTTP {status} for {current}")
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            raise FetchError(f"unsupported content type {ctype!r}")
        return current, body.decode("utf-8", errors="replace")
    raise FetchError(f"too many redirects from {url}")


def fetch(url: str) -> tuple[str, str]:
    """-> (final_url, extracted_text)."""
    final, html = fetch_raw(url)
    text = extract_text(html)
    if not text:
        raise FetchError(f"no extractable text at {final}")
    return final, text


LINK = re.compile(r'href=["\']([^"\']+)["\']', re.I)
USEFUL = ("product", "features", "platform", "solutions", "why", "about", "enterprise",
          "pricing", "customers", "use-case", "usecase", "ai")


def same_origin_links(base_url: str, html_text: str, limit: int = 2) -> list[str]:
    """Pick a couple of same-origin pages likely to carry positioning copy."""
    base = urlparse(base_url if "://" in base_url else "https://" + base_url)
    out, seen = [], {base.path.rstrip("/") or "/"}
    for href in LINK.findall(html_text):
        target = urlparse(urljoin(f"{base.scheme}://{base.netloc}", href))
        if target.netloc != base.netloc or target.scheme not in ALLOWED_SCHEMES:
            continue
        path = target.path.rstrip("/") or "/"
        if path in seen or not any(k in path.lower() for k in USEFUL):
            continue
        seen.add(path)
        out.append(f"{target.scheme}://{target.netloc}{path}")
        if len(out) >= limit:
            break
    return out


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
    """-> (pages, icon URL). Homepage plus up to two same-origin pages; individual page failures are
    skipped, not fatal. The icon comes from the homepage HTML already fetched — no extra request."""
    final, html = fetch_raw(url)             # one request; HTML reused for text, links AND the icon
    text = extract_text(html)
    if not text:
        raise FetchError(f"no extractable text at {final}")
    pages = [(final, text)]
    for link in same_origin_links(final, html, limit=max_pages - 1):
        try:
            pages.append(fetch(link))
        except (UnsafeURL, FetchError):
            continue                          # a missing sub-page is not fatal to onboarding
    return pages, icon_url(final, html)
