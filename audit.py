"""Could AI even read your site, and where else does it learn about you? No model calls.

Retrievability: for every claim onboarding kept, every page that still states it is checked the
way an AI crawler meets it. The claim is checked on the first of them AI can read (robots.txt lets
the AI crawlers in and the page is not mostly script) — are the claim's words in the plain HTML,
does the page carry schema.org structured data, a main heading and subheadings, and does it load in
time; every other page that states it but is blocked or script-only is listed as advice. Site-wide:
an llms.txt, and pages that are mostly script.

The onboarding crawler (fetching.py) already reads raw HTML and never runs JavaScript, so every quote
it verified was in the no-JS HTML by construction. The JavaScript check therefore asks whether the
words are still there now, and flags pages whose visible text is thin next to their script.

Entity grounding: Wikidata and Wikipedia through their public APIs (searched by brand name, tied to
the company only by Wikidata's official-website link to its domain), plus the Crunchbase, G2 and
LinkedIn pages the site itself links to. Addresses are never guessed, and a source whose robots.txt
turns automated tools away is reported as not checked.

Every fetch is SSRF-guarded (fetching.request), short, honours robots.txt for our own agent on the
company's site, and a failure becomes an "unknown" line with its reason, never a guess.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import quote, urlencode, urlparse
from urllib.robotparser import RobotFileParser

import fetching
from schemas import AuditCheck, ClaimAudit, Company, EntitySource, SiteAudit

TIMEOUT = 5
SLOW_SECONDS = 3.0
THIN_TEXT = 500          # visible characters below which a script-heavy page reads as empty
AI_CRAWLERS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "ClaudeBot", "Google-Extended")
OUR_AGENT = fetching.USER_AGENT.split("/")[0]
WIKIDATA = "https://www.wikidata.org/w/api.php?"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php?"
PROFILES = {
    "Crunchbase": r"crunchbase\.com/organization/[\w-]+",
    "G2": r"g2\.com/products/[\w-]+",
    "LinkedIn": r"linkedin\.com/company/[\w%-]+",
}


def get(url: str, accept: str = fetching.HTML) -> tuple[str, int, str, str]:
    """The one network call. Tests replace it with recorded responses."""
    return fetching.request(url, timeout=TIMEOUT, accept=accept)


def _fetch(url: str, accept: str = fetching.HTML) -> Optional[tuple[int, str, str, float]]:
    """-> (status, content_type, body, seconds), or None when it could not be reached at all."""
    start = time.monotonic()
    try:
        _, status, ctype, body = get(url, accept)
    except Exception:                        # refused, unresolvable, timed out, TLS: all "could not check"
        return None
    return status, ctype, body, time.monotonic() - start


def robots_for(origin: str) -> Optional[tuple[RobotFileParser, bool]]:
    """-> (rules, whether a robots.txt exists), or None when it could not be read.

    A 4xx means there is no robots.txt and everything is allowed (RFC 9309). A 5xx or no answer
    means we do not know, and we do not read the site on a guess.
    """
    r = _fetch(origin + "/robots.txt", "text/plain")
    if r is None or r[0] >= 500:
        return None
    rp = RobotFileParser()
    # ponytail: urllib.robotparser applies the first matching rule, not Google's longest match;
    # a robots.txt that relies on the longest-match rule may read slightly differently here.
    rp.parse(r[2].splitlines() if r[0] == 200 else [])
    return rp, r[0] == 200


class _Markup(HTMLParser):
    """Headings, JSON-LD blocks, how much inline script a page carries and how many scripts it loads."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0
        self.subheads: list[str] = []
        self.ld: list[str] = []
        self.script = 0
        self.external = 0
        self._open: Optional[tuple[str, str]] = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("src"):
            self.external += 1
        if tag in ("h1", "h2", "h3", "script") and not self._open:
            self._open, self._buf = (tag, (dict(attrs).get("type") or "").lower()), []

    def handle_endtag(self, tag):
        if not self._open or tag != self._open[0]:
            return
        (kind, typ), text = self._open, " ".join("".join(self._buf).split())
        self._open = None
        if kind == "h1" and text:
            self.h1 += 1
        elif kind in ("h2", "h3") and text:
            self.subheads.append(text)
        elif kind == "script":
            if typ == "application/ld+json":
                self.ld.append(text)
            else:
                self.script += len(text)

    def handle_data(self, data):
        if self._open:
            self._buf.append(data)


def _types(node) -> list[str]:
    """Every schema.org @type in a JSON-LD value, nested and @graph included."""
    if isinstance(node, list):
        return [t for n in node for t in _types(n)]
    if not isinstance(node, dict):
        return []
    own = node.get("@type")
    own = [own] if isinstance(own, str) else [t for t in own or [] if isinstance(t, str)]
    return own + [t for k, v in node.items() if k != "@type" for t in _types(v)]


@dataclass
class Page:
    url: str
    html: Optional[str] = None
    seconds: Optional[float] = None
    error: Optional[str] = None      # why it was not read, as a clause: "it answered HTTP 500"

    def __post_init__(self):
        self.text = fetching.extract_text(self.html) if self.html else ""
        self.markup = _Markup()
        try:
            self.markup.feed(self.html or "")
        except Exception:
            pass                             # malformed markup: keep whatever parsed

    @property
    def thin(self) -> bool:
        return (self.html is not None and len(self.text) < THIN_TEXT
                and (self.markup.script > len(self.text) or self.markup.external > 0))


def read_page(url: str, robots) -> Page:
    if robots is None:
        return Page(url, error="its robots.txt did not load, so we did not read it again")
    if not robots[0].can_fetch(OUR_AGENT, url):
        return Page(url, error="its robots.txt asks automated tools like ours not to read it")
    r = _fetch(url)
    if r is None:
        return Page(url, error="it did not load")
    if r[0] != 200:
        return Page(url, error=f"it answered HTTP {r[0]}")
    return Page(url, html=r[2], seconds=r[3])


def _path(url: str) -> str:
    return urlparse(url).path or "/"


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def blocked_for(url: str, robots) -> list[str]:
    return [b for b in AI_CRAWLERS if not robots[0].can_fetch(b, url)] if robots else []


def crawler_check(url: str, robots) -> AuditCheck:
    if robots is None:
        return AuditCheck(key="crawlers", status="unknown",
                          detail="The site's robots.txt did not load, so we cannot tell which AI crawlers may read this page.")
    if blocked := blocked_for(url, robots):
        return AuditCheck(key="crawlers", status="fail",
                          detail=f"robots.txt blocks {_join(blocked)} from this page, so those AIs cannot read it.")
    return AuditCheck(key="crawlers", status="pass",
                      detail="robots.txt lets every major AI crawler read this page." if robots[1]
                      else "There is no robots.txt, so every AI crawler may read this page.")


def page_checks(page: Page) -> list[AuditCheck]:
    """Markup, headings and speed of the page that states a claim."""
    m, out = page.markup, []
    types = list(dict.fromkeys(t for block in m.ld for t in _types(_parse_json(block))))
    if types:
        out.append(AuditCheck(key="markup", status="pass",
                              detail=f"Structured data (schema.org) tells AI what this page is: {', '.join(types[:4])}."))
    elif m.ld:
        out.append(AuditCheck(key="markup", status="fail",
                              detail="The page has structured data, but it does not parse, so AI cannot use it."))
    else:
        out.append(AuditCheck(key="markup", status="fail",
                              detail="No schema.org structured data, so AI has to guess what this page is: a "
                                     "product, a company, an FAQ."))
    if not m.h1:
        out.append(AuditCheck(key="headings", status="fail",
                              detail="No main heading (H1), so the page's topic is left to guesswork."))
    elif not m.subheads:
        out.append(AuditCheck(key="headings", status="fail",
                              detail="A main heading but no subheadings, so AI cannot tell where one passage "
                                     "ends and the next begins."))
    else:
        n = len(m.subheads)
        out.append(AuditCheck(key="headings", status="pass",
                              detail=f"A main heading and {n} subheading{'' if n == 1 else 's'}, such as "
                                     f"“{m.subheads[0]}”, that split the page into passages AI can quote."))
    slow = page.seconds > SLOW_SECONDS
    out.append(AuditCheck(key="speed", status="fail" if slow else "pass",
                          detail=f"Loaded in {page.seconds:.1f} s, measured once from our server"
                                 + ("; AI crawlers give up on slow pages." if slow else ".")))
    return out


def _parse_json(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return None


def claim_audit(attr, pages: list[Page], robots) -> ClaimAudit:
    read = [p for p in pages if p.html is not None]
    stating = [p for p in read if any(q in p.text for q in attr.claim_quotes)]
    page = next((p for p in stating if not blocked_for(p.url, robots) and not p.thin), stating[0] if stating else None)
    out = ClaimAudit(attribute_id=attr.id, label=attr.label, page_url=page.url if page else None)
    if page:
        for p in stating:
            if p is not page and (bots := blocked_for(p.url, robots)):
                out.advice.append(f"It is also on {_path(p.url)}, but robots.txt blocks {_join(bots)} there.")
            if p is not page and p.thin:
                out.advice.append(f"It is also on {_path(p.url)}, but that page is mostly script, so AI "
                                  "crawlers that skip scripts see little else on it.")
        if page.markup.h1 and page.markup.subheads and not any(h.endswith("?") for h in page.markup.subheads):
            out.advice.append("Try phrasing a subheading as the question a buyer would ask, like “How does it "
                              "work?”: AI answers questions, and a question-shaped heading marks the passage "
                              "that answers it.")
        note = " Most of that page is script, though, so little else on it reaches AI." if page.thin else ""
        out.checks = [crawler_check(page.url, robots),
                      AuditCheck(key="raw_text", status="pass",
                                 detail="Its words are in the page's plain HTML, so AI that does not run "
                                        "JavaScript still reads them." + note),
                      *page_checks(page)]
        return out
    if not read:
        why = "; ".join(sorted({p.error for p in pages if p.error})) or "no page was read"
        raw = AuditCheck(key="raw_text", status="unknown", detail=f"We could not read its pages again: {why}.")
    elif thin := [p for p in read if p.thin]:
        raw = AuditCheck(key="raw_text", status="fail",
                         detail=f"Its words are no longer in the plain HTML of any page we read, and "
                                f"{_join([_path(p.url) for p in thin])} is mostly script, so the copy may now "
                                "appear only after JavaScript runs, which most AI crawlers never do.")
    else:
        raw = AuditCheck(key="raw_text", status="fail",
                         detail="Its words are no longer on any page we read, so the copy has changed since "
                                "onboarding and AI has nothing to quote.")
    rest = [AuditCheck(key=k, status="unknown", detail="No page states it now, so there is no page to check.")
            for k in ("crawlers", "markup", "headings", "speed")]
    out.checks = [rest[0], raw, *rest[1:]]
    return out


def llms_check(origin: str, robots) -> AuditCheck:
    url = origin + "/llms.txt"
    if robots is None or not robots[0].can_fetch(OUR_AGENT, url):
        return AuditCheck(key="llms_txt", status="unknown",
                          detail="We could not check for an llms.txt: robots.txt did not load or asks us not to.")
    r = _fetch(url, "text/plain")
    if r is None:
        return AuditCheck(key="llms_txt", status="unknown", detail=f"{url} did not load, so we could not check.")
    if r[0] == 200 and "html" not in r[1] and r[2].strip():
        return AuditCheck(key="llms_txt", status="pass",
                          detail="The site has an llms.txt, a plain-text guide to its pages written for AI.")
    return AuditCheck(key="llms_txt", status="fail",
                      detail="No llms.txt at the root. It is a new, optional plain-text guide to a site "
                             "for AI; few AI tools read it yet, so treat it as cheap insurance.")


def no_js_check(pages: list[Page]) -> AuditCheck:
    read = [p for p in pages if p.html is not None]
    if not read:
        return AuditCheck(key="no_js", status="unknown", detail="No page could be read again.")
    if thin := [p for p in read if p.thin]:
        return AuditCheck(key="no_js", status="fail",
                          detail=f"{_join([_path(p.url) for p in thin])} shows under {THIN_TEXT} characters of "
                                 "text without JavaScript, next to more script than text; AI crawlers that "
                                 "skip scripts see a near-empty page.")
    return AuditCheck(key="no_js", status="pass",
                      detail=f"All {len(read)} page{'' if len(read) == 1 else 's'} we read show their text "
                             "without JavaScript.")


def _json(url: str):
    r = _fetch(url, "application/json")
    return _parse_json(r[2]) if r and r[0] == 200 else None


def _on_domain(url, domain: str) -> bool:
    host = (urlparse(url).hostname or "").removeprefix("www.") if isinstance(url, str) else ""
    return host == domain or host.endswith("." + domain)


def wiki_sources(name: str, domain: str) -> list[EntitySource]:
    """Wikidata and Wikipedia: candidates by name from both searches, kept only when the Wikidata
    entry's official website (P856) is on the company's domain."""
    def unchecked(why: str) -> list[EntitySource]:
        return [EntitySource(source=s, status="not_checked", summary=why) for s in ("Wikipedia", "Wikidata")]

    wd = _json(WIKIDATA + urlencode(dict(action="wbsearchentities", search=name, language="en",
                                         type="item", limit=7, format="json")))
    wp = _json(WIKIPEDIA + urlencode(dict(action="query", format="json", generator="search", gsrsearch=name,
                                          gsrlimit=5, prop="pageprops", ppprop="wikibase_item")))
    if not isinstance(wd, dict) or not isinstance(wp, dict):
        return unchecked("Wikipedia or Wikidata did not answer, so we could not check.")
    ids = [h.get("id") for h in wd.get("search", [])]
    ids += [p.get("pageprops", {}).get("wikibase_item") for p in (wp.get("query") or {}).get("pages", {}).values()]
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, str)][:12]
    ents = _json(WIKIDATA + urlencode(dict(action="wbgetentities", ids="|".join(ids), format="json",
                                           props="claims|descriptions|sitelinks", languages="en",
                                           sitefilter="enwiki"))) if ids else {"entities": {}}
    if not isinstance(ents, dict):
        return unchecked("Wikidata did not answer, so we could not check.")
    match = next((e for e in (ents.get("entities") or {}).values()
                  if any(_on_domain(c.get("mainsnak", {}).get("datavalue", {}).get("value"), domain)
                         for c in e.get("claims", {}).get("P856", []))), None)
    if match is None:
        return [
            EntitySource(source="Wikipedia", status="missing",
                         summary=f"No English Wikipedia article we could tie to {domain}. Without one, AI has "
                                 "no neutral summary of you to repeat."),
            EntitySource(source="Wikidata", status="missing",
                         summary=f"No Wikidata entry for “{name}” lists {domain} as its website. AI models use "
                                 "Wikidata to tell companies apart, so a missing entry often explains why "
                                 "they do not know one."),
        ]
    qid = match.get("id", "")
    data = EntitySource(source="Wikidata", status="found", url=f"https://www.wikidata.org/wiki/{qid}",
                        says=(match.get("descriptions", {}).get("en") or {}).get("value"),
                        summary=f"Wikidata has an entry that lists {domain} as its website.")
    title = (match.get("sitelinks", {}).get("enwiki") or {}).get("title")
    if not title:
        return [EntitySource(source="Wikipedia", status="missing",
                             summary="Your Wikidata entry has no English Wikipedia article linked to it."), data]
    slug = quote(title.replace(" ", "_"))
    page = _json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}") or {}
    first = re.split(r"(?<=\.)\s", page.get("extract") or "", maxsplit=1)[0] or page.get("description")
    return [EntitySource(source="Wikipedia", status="found", says=first or None,
                         url=f"https://en.wikipedia.org/wiki/{slug}",
                         summary=f"Wikipedia has an article, “{title}”, linked to your Wikidata entry."), data]


def profile_source(source: str, html: str) -> EntitySource:
    """A profile page counts only when the company's own pages link to it: we never guess addresses."""
    m = re.search(r"https?://(?:[a-z]{2,3}\.)?" + PROFILES[source], html, re.I)
    if not m:
        return EntitySource(source=source, status="not_checked",
                            summary=f"Your pages do not link to a {source} page, and we do not guess addresses.")
    url = m.group(0)
    robots = robots_for(f"https://{urlparse(url).hostname}")
    if robots is None:
        return EntitySource(source=source, status="not_checked", url=url,
                            summary=f"Your site links to one, but {source} did not answer, so we could not check it.")
    if not robots[0].can_fetch(OUR_AGENT, url):
        return EntitySource(source=source, status="not_checked", url=url,
                            summary=f"Your site links to one, but {source} does not allow automated checks, "
                                    "so we did not open it.")
    r = _fetch(url)
    if r and r[0] == 200:
        return EntitySource(source=source, status="found", url=url, summary="Your site links to it, and it is there.")
    if r and r[0] in (404, 410):
        return EntitySource(source=source, status="missing", url=url,
                            summary=f"Your site links to a {source} page that no longer exists.")
    return EntitySource(source=source, status="not_checked", url=url,
                        summary=f"Your site links to one, but {source} turned our automated check away.")


def run(company: Company) -> SiteAudit:
    """Fetch everything, then check. Never raises: what cannot be reached becomes 'could not check'."""
    domain = company.profile.domain
    first = urlparse(company.pages[0] if company.pages else f"https://{domain}")
    origin = f"{first.scheme}://{first.netloc}"
    robots = robots_for(origin)
    with ThreadPoolExecutor(8) as pool:
        pages_f = [pool.submit(read_page, u, robots) for u in company.pages]
        llms_f = pool.submit(llms_check, origin, robots)
        wiki_f = pool.submit(wiki_sources, company.profile.name, domain)
        pages = [f.result() for f in pages_f]
        html = "\n".join(p.html or "" for p in pages)
        profiles = list(pool.map(lambda s: profile_source(s, html), PROFILES))
        return SiteAudit(site=[llms_f.result(), no_js_check(pages)],
                         claims=[claim_audit(a, pages, robots) for a in company.attributes if a.claim_quotes],
                         entities=[*wiki_f.result(), *profiles])
