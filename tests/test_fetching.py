"""SSRF and parsing checks for the onboarding fetcher. No network: resolution is stubbed."""
import socket

import pytest

import fetching
from fetching import FetchError, UnsafeURL


def stub_resolve(monkeypatch, addr: str):
    monkeypatch.setattr(fetching.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM,
                                          socket.IPPROTO_TCP, "", (addr, 443))])


# --- scheme and shape --------------------------------------------------------
@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "gopher://example.com",
])
def test_non_http_schemes_refused(url):
    with pytest.raises(UnsafeURL, match="scheme"):
        fetching.validate(url)


def test_hostname_without_a_dot_refused():
    """Blocks 'localhost', container names and other internal short names."""
    with pytest.raises(UnsafeURL, match="without a dot"):
        fetching.validate("http://localhost/")
    with pytest.raises(UnsafeURL, match="without a dot"):
        fetching.validate("http://metadata/")


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
def test_hostname_resolving_to_loopback_refused(monkeypatch):
    """The classic bypass: a public-looking name pointed at 127.0.0.1."""
    stub_resolve(monkeypatch, "127.0.0.1")
    with pytest.raises(UnsafeURL, match="non-public"):
        fetching.resolve_public("evil.example.com", 443)


def test_hostname_resolving_to_metadata_ip_refused(monkeypatch):
    stub_resolve(monkeypatch, "169.254.169.254")
    with pytest.raises(UnsafeURL, match="non-public"):
        fetching.resolve_public("metadata.example.com", 443)


def test_every_resolved_address_is_checked(monkeypatch):
    """A name answering with one public and one private address must be refused outright."""
    monkeypatch.setattr(fetching.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", 443)),
    ])
    with pytest.raises(UnsafeURL, match="non-public"):
        fetching.resolve_public("split.example.com", 443)


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

    def fake_get(scheme, host, port, path):
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


def test_non_html_content_type_refused(monkeypatch):
    monkeypatch.setattr(fetching, "_get",
                        lambda *a: (200, {"Content-Type": "application/zip"}, b"PK\x03\x04"))
    stub_resolve(monkeypatch, "93.184.216.34")
    with pytest.raises(FetchError, match="unsupported content type"):
        fetching.fetch_raw("https://example.com/")


# --- text extraction ---------------------------------------------------------
def test_script_and_style_are_stripped():
    html = ("<html><head><style>body{color:red}</style></head><body>"
            "<script>alert('x')</script><h1>Connected workspace</h1>"
            "<p>Docs and databases in one place.</p></body></html>")
    text = fetching.extract_text(html)
    assert "Connected workspace" in text and "Docs and databases in one place." in text
    assert "alert" not in text and "color:red" not in text


def test_extracted_text_is_capped():
    assert len(fetching.extract_text("<p>" + ("word " * 20_000) + "</p>")) <= fetching.MAX_CHARS


def test_malformed_html_still_yields_text():
    assert "Hello" in fetching.extract_text("<div><p>Hello<div><span>")


# --- link discovery ----------------------------------------------------------
def test_only_same_origin_useful_links_are_followed():
    html = ('<a href="/product/ai">ai</a>'
            '<a href="https://other.example.com/product">off-site</a>'
            '<a href="/careers">careers</a>'
            '<a href="/enterprise">enterprise</a>')
    links = fetching.same_origin_links("https://example.com/", html, limit=5)
    assert links == ["https://example.com/product/ai", "https://example.com/enterprise"]
    assert not any("other.example.com" in l for l in links)
    assert not any("careers" in l for l in links)


def test_icon_prefers_apple_touch_then_icon_then_favicon_and_only_http():
    base = "https://acme.example/home"
    both = '<link rel="icon" href="/f.ico"><link href="/touch.png" rel="apple-touch-icon">'
    assert fetching.icon_url(base, both) == "https://acme.example/touch.png"
    assert fetching.icon_url(base, '<link rel="shortcut icon" href="//cdn.example/i.png">') \
        == "https://cdn.example/i.png"
    assert fetching.icon_url(base, '<link rel="icon" href="javascript:alert(1)">') \
        == "https://acme.example/favicon.ico"
    assert fetching.icon_url(base, "<p>no links</p>") == "https://acme.example/favicon.ico"
