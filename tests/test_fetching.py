"""SSRF and parsing checks for the onboarding fetcher. No network: resolution is stubbed."""
import socket

import pytest

import fetching
from fetching import FetchError, UnsafeURL


def stub_resolve(monkeypatch, *addrs: str):
    monkeypatch.setattr(fetching.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM,
                                          socket.IPPROTO_TCP, "", (addr, 443)) for addr in addrs])


# --- scheme and shape --------------------------------------------------------
@pytest.mark.parametrize("url,why", [
    ("file:///etc/passwd", "scheme"),
    ("ftp://example.com/x", "scheme"),
    ("gopher://example.com", "scheme"),
    ("http://localhost/", "without a dot"),   # localhost, container names and other internal short names
    ("http://metadata/", "without a dot"),
])
def test_non_http_schemes_and_dotless_hosts_refused(url, why):
    with pytest.raises(UnsafeURL, match=why):
        fetching.validate(url)


# --- literal addresses -------------------------------------------------------
@pytest.mark.parametrize("host", [
    "127.0.0.1",            # loopback
    "10.0.0.5",             # private
    "192.168.1.1",          # private
    "172.16.0.1",           # private
    "169.254.169.254",      # cloud metadata
    "100.64.0.1",           # CGNAT
    "0.0.0.0",              # unspecified
    "[::1]",                # IPv6 loopback
])
def test_non_public_literal_addresses_refused(host):
    with pytest.raises(UnsafeURL):
        fetching.validate(f"http://{host}/")


def test_public_literal_address_allowed():
    assert fetching.validate("https://93.184.216.34/x")[1] == "93.184.216.34"


# --- DNS results -------------------------------------------------------------
@pytest.mark.parametrize("addrs", [
    ["127.0.0.1"],                    # the classic bypass: a public-looking name pointed at loopback
    ["169.254.169.254"],              # cloud metadata
    ["93.184.216.34", "10.1.2.3"],    # one public and one private: every address is checked
])
def test_hostname_resolving_to_a_non_public_address_refused(monkeypatch, addrs):
    stub_resolve(monkeypatch, *addrs)
    with pytest.raises(UnsafeURL, match="non-public"):
        fetching.resolve_public("evil.example.com", 443)


def test_public_resolution_returns_the_address_used(monkeypatch):
    """The connection targets the validated IP, which is what defeats DNS rebinding."""
    stub_resolve(monkeypatch, "93.184.216.34")
    assert fetching.resolve_public("example.com", 443) == "93.184.216.34"


def test_unresolvable_host_is_a_fetch_error_not_a_crash(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(fetching.socket, "getaddrinfo", boom)
    with pytest.raises(FetchError, match="cannot resolve"):
        fetching.resolve_public("nx.example.com", 443)


# --- redirects ---------------------------------------------------------------
def test_redirect_to_a_private_address_is_refused(monkeypatch):
    """An allowed public page must not be able to bounce us onto the LAN."""
    calls = {"n": 0}

    def fake_get(scheme, host, port, path, *_):
        calls["n"] += 1
        return 302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""

    monkeypatch.setattr(fetching, "_get", fake_get)
    stub_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(UnsafeURL):
        fetching.fetch_raw("https://example.com/")
    assert calls["n"] == 1    # refused before the second request was made


def test_redirect_limit_enforced(monkeypatch):
    monkeypatch.setattr(fetching, "_get",
                        lambda *a: (302, {"Location": "https://example.com/next"}, b""))
    stub_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(FetchError, match="too many redirects"):
        fetching.fetch_raw("https://example.com/")


# --- text extraction ---------------------------------------------------------
def test_extracted_text_is_capped():
    assert len(fetching.extract_text("<p>" + ("word " * 20_000) + "</p>")) <= fetching.MAX_CHARS


def test_malformed_html_still_yields_text():
    assert "Hello" in fetching.extract_text("<div><p>Hello<div><span>")


# --- link discovery ----------------------------------------------------------
def test_only_same_origin_positioning_pages_are_followed():
    html = ('<a href="/product/ai">ai</a>'
            '<a href="https://other.example.com/product">off-site</a>'
            '<a href="/careers">careers</a>'
            '<a href="/enterprise">enterprise</a>')
    links = fetching.positioning_links("https://example.com/", html, limit=5)
    assert links == ["https://example.com/product/ai", "https://example.com/enterprise"]


def test_stylesheets_are_not_pages_and_keywords_match_whole_words():
    # amgen.com, 22 Sep 2026: all five "pages" read were <link> stylesheets, because every href
    # counted and "ai" matched inside "CorporateAffairs". Its real /about/ pages were never read.
    html = ('<link rel="stylesheet" href="/-/media/Themes/CorporateAffairs/amgen-com/styles/main.css">'
            '<a data-href="/about/ignored" href="/-/media/Themes/CorporateAffairs/brochure">brochure</a>'
            '<a class="nav" href="/about/therapy-areas">Therapy areas</a>'
            '<a href="/ai-and-data-science">AI</a>')
    assert fetching.positioning_links("https://www.amgen.com/", html, limit=5) == [
        "https://www.amgen.com/about/therapy-areas", "https://www.amgen.com/ai-and-data-science"]


def test_one_page_of_each_kind_before_a_second_of_any():
    # amgen.com's first five matching links were all under /about/, so the page listing its
    # medicines (/products) was never read and its own products could not count as mentions.
    html = "".join(f'<a href="/about/{p}">x</a>' for p in ("history", "leadership", "partners"))
    html += '<a href="/products">Products</a><a href="/about/awards">x</a><a href="/about/mission-and-values">x</a>'
    assert fetching.positioning_links("https://www.amgen.com/", html, limit=4) == [
        "https://www.amgen.com/about/history", "https://www.amgen.com/about/mission-and-values",
        "https://www.amgen.com/products", "https://www.amgen.com/about/leadership"]


# amgen.com, 22 Sep 2026: a URL keyword ("why") sent the six-page crawl to a MrBeast press story and a
# deep R&D page, while its mission and newsroom pages went unread.
AMGEN_NAV = ('<a href="/about">About</a><a href="/about/amgen-history">Amgen History</a>'
             '<a href="/about/mission-and-values">Mission and Values</a>'
             '<a href="/science/research-and-development-strategy/ai-in-research-and-development">AI in R&amp;D</a>'
             '<a href="/products">Products</a>'
             '<a href="/stories/2026/07/why-mrbeast-stand-up-to-cancer-and-amgen-joined-forces-to-support-'
             'pediatric-cancer-research">Why MrBeast joined forces</a>'
             '<a href="/newsroom">Newsroom</a><a href="/newsroom/press-releases/2026/08/amgen-q2">Q2</a>'
             '<a href="/careers">Careers</a><a href="/privacy-statement">Privacy</a>')


def test_pages_are_picked_by_what_they_are_not_by_a_word_in_their_url():
    links = fetching.positioning_links("https://www.amgen.com/", AMGEN_NAV, limit=7)
    assert links == ["https://www.amgen.com/about", "https://www.amgen.com/about/mission-and-values",
                     "https://www.amgen.com/products", "https://www.amgen.com/newsroom",
                     "https://www.amgen.com/about/amgen-history"]
    assert not any(x in u for u in links for x in ("stories", "press-releases", "careers", "science"))


@pytest.mark.parametrize("path,text,kind", [
    ("/why-linear", "", "why"), ("/ai", "", "ai"), ("/our-story", "", "about"),
    ("/what-we-do", "", "offer"), ("/company/leadership", "Our purpose", "about"),
    ("/team/charter", "Our mission", "mission"), ("/blog/why-we-built", "", None),
    ("/changelog/2026-09-14-loops", "", None), ("/newsroom/amgen-wins", "", None),
])
def test_page_kind(path, text, kind):
    assert fetching.page_kind(path, text) == kind


def test_a_homepage_with_too_few_links_is_topped_up_from_the_sitemap(monkeypatch):
    home = '<html><body><p>Acme makes contracts searchable.</p><a href="/about">About</a></body></html>'
    sitemap = ("<urlset><url><loc>https://acme.example/blog/2026/launch</loc></url>"
               "<url><loc>https://acme.example/products</loc></url>"
               "<url><loc>https://acme.example/mission</loc></url></urlset>")
    fetched = []

    def raw(url, timeout=10, types=("html", "text")):
        fetched.append(url)
        return url, sitemap if url.endswith("sitemap.xml") else home
    monkeypatch.setattr(fetching, "fetch_raw", raw)
    monkeypatch.setattr(fetching, "fetch", lambda url: (url, "Acme page text."))
    pages, _ = fetching.fetch_site("https://acme.example/", max_pages=8)
    assert [u for u, _ in pages] == ["https://acme.example/", "https://acme.example/about",
                                     "https://acme.example/mission", "https://acme.example/products"]
    assert "https://acme.example/sitemap.xml" in fetched


def test_a_page_must_be_html_though_robots_txt_may_be_plain_text(monkeypatch):
    stub_resolve(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(fetching, "_get", lambda *a: (200, {"Content-Type": "text/css"}, b"body{color:red}"))
    with pytest.raises(FetchError, match="unsupported content type"):
        fetching.fetch("https://example.com/main.css")
    monkeypatch.setattr(fetching, "_get", lambda *a: (200, {"Content-Type": "text/plain"}, b"User-agent: *"))
    assert fetching.fetch_raw("https://example.com/robots.txt")[1] == "User-agent: *"


def test_icon_prefers_apple_touch_then_icon_then_favicon_and_only_http():
    base = "https://acme.example/home"
    both = '<link rel="icon" href="/f.ico"><link href="/touch.png" rel="apple-touch-icon">'
    assert fetching.icon_url(base, both) == "https://acme.example/touch.png"
    assert fetching.icon_url(base, '<link rel="shortcut icon" href="//cdn.example/i.png">') \
        == "https://cdn.example/i.png"
    assert fetching.icon_url(base, '<link rel="icon" href="javascript:alert(1)">') \
        == "https://acme.example/favicon.ico"
    assert fetching.icon_url(base, "<p>no links</p>") == "https://acme.example/favicon.ico"


# --- passages and robots.txt (retrieval.py) ---------------------------------------------------------

def test_blocks_follow_headings_and_paragraphs():
    html = ("<style>body{color:red}</style><h2>Pricing</h2><p>Free for <b>small</b> teams.</p>"
            "<ul><li>One</li><li>Two</li></ul><script>alert('x')</script>")
    assert fetching.extract_blocks(html) == ["Pricing", "Free for small teams.", "One", "Two"]
    assert fetching.extract_text(html) == "Pricing Free for small teams. One Two"


def test_robots_txt_is_respected_and_a_missing_one_allows(monkeypatch):
    robots = "User-agent: *\nDisallow: /private/\n"
    monkeypatch.setattr(fetching, "fetch_raw", lambda url, timeout=10: (url, robots))
    assert fetching.robots_allow("https://example.com/blog/post")
    assert not fetching.robots_allow("https://example.com/private/page")

    def missing(url, timeout=10):
        raise FetchError(f"HTTP 404 for {url}")
    monkeypatch.setattr(fetching, "fetch_raw", missing)
    assert fetching.robots_allow("https://example.com/private/page")

    def down(url, timeout=10):
        raise FetchError(f"HTTP 503 for {url}")
    monkeypatch.setattr(fetching, "fetch_raw", down)
    with pytest.raises(FetchError):
        fetching.robots_allow("https://example.com/")


# --- plain failures (reproduced 2026-09-28: a user saw "Onboarding failed: TimeoutError") ---------
class _Conn:
    """A socket stand-in for create_connection; the failure comes from the TLS or HTTP step."""
    def close(self):
        pass


@pytest.mark.parametrize("error,words", [
    (TimeoutError("timed out"), "did not answer within 10 seconds"),
    (ConnectionRefusedError(61, "refused"), "could not connect to example.com"),
])
def test_a_connection_failure_is_a_plain_fetch_error(monkeypatch, error, words):
    stub_resolve(monkeypatch, "93.184.216.34")

    def fail(*a, **k):
        raise error
    monkeypatch.setattr(fetching.socket, "create_connection", fail)
    with pytest.raises(FetchError, match=words):
        fetching.fetch_raw("https://example.com/")


def test_a_bad_certificate_is_a_plain_fetch_error(monkeypatch):
    import ssl
    stub_resolve(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(fetching.socket, "create_connection", lambda *a, **k: _Conn())
    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_message = "certificate has expired"

    class Ctx:
        def wrap_socket(self, sock, server_hostname):
            raise err
    monkeypatch.setattr(fetching.ssl, "create_default_context", lambda: Ctx())
    with pytest.raises(FetchError, match="security certificate that is not valid .certificate has expired"):
        fetching.fetch_raw("https://example.com/")


@pytest.mark.parametrize("status,words", [
    (403, "www.example.com turns automated readers away .HTTP 403"),
    (404, "there is no page at https://www.example.com/ .HTTP 404"),
    (500, "answered HTTP 500"),
])
def test_a_status_says_what_it_means_and_keeps_its_number(monkeypatch, status, words):
    """A 403 is a bot wall (perplexity.ai's Cloudflare check), not a missing page. The number stays
    in the message: robots_allow reads "HTTP 4xx" out of it."""
    monkeypatch.setattr(fetching, "_get", lambda *a: (status, {"Content-Type": "text/html"}, b"Just a moment..."))
    stub_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(FetchError, match=words):
        fetching.fetch_raw("https://www.example.com/")


def test_a_page_built_only_by_script_says_so(monkeypatch):
    """character.ai: 327 KB of HTML and not one visible word."""
    monkeypatch.setattr(fetching, "_get", lambda *a: (200, {"Content-Type": "text/html"},
                                                      b"<html><head><script>app()</script></head><body><div id=root></div></body></html>"))
    stub_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(FetchError, match="shows no text until script runs"):
        fetching.fetch_site("https://example.com/")
