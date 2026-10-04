"""Onboarding from a company's name alone: find which company it is, and read its own pages through
search when its site turns our reader away (WEB.md "Onboarding"). One metered web-search call each,
on the measured model's search tool; nothing here is a measurement of anything.

Many sites never reach the plain fetch in fetching.py: perplexity.ai answers every automated reader
with Cloudflare's "verify you are human" check (a real Chrome window gets it too, so a headless
browser would not help), and an app-only landing page has no text until script runs. The search
engine behind the web_search tool has read those pages, and `live.INCLUDE` hands us the text it
saved: a search copy, the company's own words as saved on the date the result gives.

What counts as the company's own words is decided here, in code, never by the model:
  * only a URL that came back in a search result is used; the model's own list of URLs is not
  * an own page is on the confirmed domain or a subdomain of it AND its text names the company.
    The second test matters: perplexity.ai also hosts other companies' SEC filings.
  * a page in another language is skipped (quotes are matched as written, and answers are English)
  * anything else that names the company is third-party: shown to the user apart, never extracted
"""
import re
from typing import Callable, Optional
from urllib.parse import urlparse

import fetching
from agents.evaluator_model import json_object
from providers import live
from schemas import Evidence, ReadResult
from scoring import domain_matches

TIMEOUT = 90
MAX_CANDIDATES = 3
MAX_OTHERS = 5
# "Published: 3 weeks ago; Crawled: 2 days ago; " opens a result's text; it is not the page's words
PREFACE = re.compile(r"^\s*(?:(?:Published|Crawled): [^;\n]*;\s*)+")
# A path segment naming another language ("/es/", "/es-MX/", "/help-center/nl/…"). A list, not any
# two letters: "/ai" is a page, not a language.
LANGUAGES = {"es", "fr", "de", "it", "pt", "nl", "ja", "ko", "zh", "ru", "pl", "sv", "da", "fi", "nb",
             "tr", "ar", "he", "hi", "th", "vi", "cs", "uk", "ro", "hu", "el"}
LEGAL = re.compile(r",?\s+(?:inc|llc|ltd|limited|plc|gmbh|corp|corporation|co)\.?$", re.I)

FIND_PROMPT = """Someone wants to measure how AI describes the company named: {name}
{hint}
Use web search to find which real company this is and its official website. If several companies
share this name, list up to 3, most likely first. List only a domain that appeared in a search result.
Return ONLY JSON: {{"candidates": [{{"name": string, "domain": string, "what": string}}]}}
name: the company's full name. domain: its official website's domain, like "example.com".
what: what the company does, in under 15 plain words."""

GATHER_PROMPT = """Use web search to find the pages that {name} publishes about itself on {domain} and
its subdomains: about and company pages, product and platform pages, enterprise, pricing, newsroom or
press, blog, docs and help centre. Search with site:{domain} as well as without it.
Then list the URLs you found, one per line."""


class SearchFailed(RuntimeError):
    """The search could not be made or read; the message is shown to the user as is."""


# forced search, metered and charged to the pass; a prompt string is a valid input
default_transport = live.default_transport


def _search(prompt: str, transport: Optional[Callable]):
    # the model and search tool the last preflight proved, not the configured pair it stepped down from
    tool = live.search_tool()
    if tool is None:
        raise SearchFailed(f"Web search is not available right now: {live.fallback_reason()}")
    try:
        return (transport or default_transport)(prompt, live.model_name(), TIMEOUT, tool)
    except Exception as e:  # a model or network failure; a spending refusal (BaseException) goes up
        raise SearchFailed(f"Web search is not available right now ({live.safe_error(e)}).") from e


def clean(url: str) -> Optional[str]:
    """The page's address without its query string or fragment: "?trk=…" tracking came back on
    several links, and the same page twice would count its claims twice."""
    u = urlparse(url)
    if u.scheme not in fetching.ALLOWED_SCHEMES or not u.hostname:
        return None
    return f"{u.scheme}://{u.hostname}{u.path.rstrip('/')}"


def _key(url: str) -> str:
    u = urlparse(url)
    return f"{(u.hostname or '').removeprefix('www.')}{u.path.rstrip('/')}"


def results(response) -> list[ReadResult]:
    """Every page the search handed the model, in order, once each, text as given."""
    out: dict[str, ReadResult] = {}
    for step in live.reading_of(response, cap=None) or []:
        for r in step.results:
            url = clean(r.url)
            if url and _key(url) not in out:
                out[_key(url)] = r.model_copy(update={"url": url, "text": PREFACE.sub("", r.text).strip()})
    return list(out.values())


def names_of(name: str, domain: str = "") -> list[str]:
    """The words that name the company on its own pages: the name, without "Inc." and the like, and
    the first label of its domain ("perplexity" for perplexity.ai)."""
    base = LEGAL.sub("", name.strip())
    return [n for n in dict.fromkeys([name.strip(), base, domain.split(".")[0]]) if len(n) > 1]


def names_company(text: str, names: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I) for n in names)


def foreign(url: str) -> bool:
    return any(seg in LANGUAGES or (re.fullmatch(r"[a-z]{2}-(?:[a-z]{2}|hans|hant)", seg) and seg[:2] != "en")
               for seg in urlparse(url).path.lower().split("/"))


def rank(url: str) -> int:
    """Where a page says who the company is comes first, as in the crawl (fetching.PAGE_KINDS): the
    homepage, about, mission, what it offers … then everything else in the order search gave it."""
    path = urlparse(url).path.rstrip("/")
    kind = fetching.page_kind(path) if path else None
    return -1 if not path else fetching.RANK.get(kind, len(fetching.RANK))


def domain_of(raw: str) -> Optional[str]:
    """"https://www.Example.com/about" -> "example.com", or None when it is not a public web address."""
    raw = (raw or "").strip()
    try:
        host = fetching.validate(raw)[1].lower().removeprefix("www.")
    except fetching.UnsafeURL:
        return None
    return host


def find(name: str, hint: Optional[str] = None, transport: Optional[Callable] = None) -> dict:
    """-> {"candidates": [{name, domain, what, exact}], "exact": bool}. A candidate is kept only when
    its domain came back in a search result. `exact` says whether its name is the name searched for:
    asked about a made-up name, the model returned three confident near-misses rather than "none"."""
    hint_line = f"The user adds: {hint.strip()}" if hint and hint.strip() else ""
    response = _search(FIND_PROMPT.format(name=name.strip(), hint=hint_line), transport)
    text, _, _ = live.parse_response(response)
    seen = [r.url for r in results(response)]
    try:
        raw = json_object(text, "the search").get("candidates") or []
    except (ValueError, AttributeError):
        raw = []
    candidates = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        domain = domain_of(str(c.get("domain") or ""))
        full = " ".join(str(c.get("name") or "").split())
        if (not domain or not full or domain in [x["domain"] for x in candidates]
                or not any(domain_matches(u, [domain]) for u in seen)):
            continue
        candidates.append(dict(name=full, domain=domain, what=" ".join(str(c.get("what") or "").split()),
                               exact=names_company(full, names_of(name))))
        if len(candidates) == MAX_CANDIDATES:
            break
    return dict(candidates=candidates, exact=any(c["exact"] for c in candidates))


def gather(name: str, domain: str, limit: int, have: list[str] = (), transport: Optional[Callable] = None,
           fetch: Optional[Callable] = None) -> tuple[list[tuple[str, str]], list[dict], list[Evidence]]:
    """-> (own pages, what each one is, third-party pages): up to `limit` of the company's own pages
    that search found, beyond the ones already read (`have`). Each own page is read directly when it
    lets us (a subdomain often does when the main site will not), else its search copy is used."""
    response = _search(GATHER_PROMPT.format(name=name.strip(), domain=domain), transport)
    names = names_of(name, domain)
    done = {_key(u) for u in have}
    turned_away: set[str] = set()   # one refusal per host is enough: the rest would only time out too
    pages, meta, others, own = [], [], [], []
    for r in results(response):
        if not r.text or not names_company(r.text, names) or _key(r.url) in done:
            continue
        if domain_matches(r.url, [domain]):
            if not foreign(r.url):
                own.append(r)
        elif len(others) < MAX_OTHERS:
            others.append(Evidence(id=f"tp{len(others) + 1}", url=r.url, excerpt=r.text[:600],
                                   source_type="third_party", title=r.title))
    for r in sorted(own, key=lambda r: rank(r.url))[:limit]:
        host, direct = urlparse(r.url).hostname, None
        if host not in turned_away:
            try:
                direct = (fetch or fetching.fetch)(r.url)[1]
            except (fetching.UnsafeURL, fetching.FetchError):
                turned_away.add(host)
        if direct and names_company(direct, names):
            pages.append((r.url, direct))
            meta.append({})
        else:
            pages.append((r.url, r.text))
            meta.append(dict(source_type="search_copy", saved=r.crawled, title=r.title))
    return pages, meta, others
