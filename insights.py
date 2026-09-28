"""Report panels read off a saved run: which sites AI cites (and beside which brands), share of
voice, and what AI searched. No model calls.

Sources and share of voice count only baseline answers that count toward the scores
(`scoring.eligible`), so an excluded or exploratory answer can never move them. Searches is not a
score and reads every buyer answer that came back. Every empty panel carries the reason it is empty.
"""
import re
from collections import Counter
from urllib.parse import urlparse

from schemas import Run
from scoring import domain_matches, eligible

RIVALS = 3      # competitors shown beside the brand


def _counted(run: Run, kind: str):
    ans = {a.probe_id: a for a in run.answers}
    ev = {e.probe_id: e for e in run.evaluations}
    for p in run.probes:
        if p.kind == kind and p.phase == "baseline" and p.id in ans and p.id in ev \
                and eligible(ans[p.id], ev[p.id])[0]:
            yield ans[p.id], ev[p.id]


PLACEHOLDER_HOSTS = {"example.com", "example.net", "example.org"}  # RFC 2606; the fixtures' fictional sources


def _host(url: str) -> str:
    """The site a citation points at. A placeholder host keeps its path: the fixtures write each
    fictional source as example.com/demo-source-N, and collapsing them would rank one fake site."""
    parts = urlparse(url if "://" in url else "//" + url)
    host = (parts.hostname or "").lower().rstrip(".").removeprefix("www.")
    return host + parts.path.rstrip("/") if host in PLACEHOLDER_HOSTS else host


# ponytail: a short list of well-known sites plus host heuristics; unknown sites fall to "other".
REVIEW_SITES = {"g2.com", "capterra.com", "trustradius.com", "getapp.com", "softwareadvice.com",
                "trustpilot.com", "gartner.com", "producthunt.com", "alternativeto.net",
                "sourceforge.net", "saasworthy.com", "pcmag.com", "techradar.com", "zapier.com"}
COMMUNITY_SITES = {"reddit.com", "quora.com", "news.ycombinator.com", "stackoverflow.com",
                   "stackexchange.com", "discord.com", "linkedin.com", "x.com", "twitter.com",
                   "facebook.com", "github.com"}
MEDIA_SITES = {"medium.com", "substack.com", "forbes.com", "techcrunch.com", "theverge.com",
               "wired.com", "zdnet.com", "businessinsider.com", "nytimes.com", "cnbc.com",
               "youtube.com", "hbr.org", "fastcompany.com", "venturebeat.com", "wikipedia.org"}


def _key(name: str) -> str:
    """'Otter.ai' -> 'otter', 'monday.com' -> 'monday': a product name as it would sit in its domain."""
    return re.sub(r"[^a-z0-9]", "", name.lower().split(".")[0])


# First words that name a kind of business, not one company: "Specialty Pharmacy X" is not specialty.com.
GENERIC_FIRST = {"the", "global", "national", "american", "united", "general", "international", "specialty",
                 "biologics", "first", "new"}
# Last words that name a line of business, not the company: "Johnson & Johnson Innovative Medicine".
GENERIC_LAST = {"medicine", "medicines", "pharmacy", "pharmaceuticals", "pharmaceutical", "pharma",
                "distribution", "specialty", "health", "group", "company", "inc", "co", "corp",
                "corporation", "labs", "solutions", "services", "systems", "technologies", "software"}


def domain_keys(name: str) -> set[str]:
    """The labels a company's own domain may carry, read off its name: the whole name
    ("merck" for Merck, "cardinalhealth" from "Cardinal Health Specialty…"), its first and last
    words ("walmart" for Walmart Pharmacy, "lilly" for Eli Lilly) and its initials, "&" read as "n" ("jnj" and "jj" for Johnson &
    Johnson, "bms" for Bristol Myers Squibb). Johnson & Johnson's own sites, jnj.com and
    innovativemedicine.jnj.com, used to be filed as somebody else's page to get onto.
    ponytail: spelling heuristics only; a rival whose domain shares nothing with its name (Caremark
    for CVS) stays "other" — a per-rival domain list is the upgrade if that matters."""
    words = re.findall(r"[a-z0-9]+|&", re.sub(r"\([^()]*\)", " ", name.lower()))
    letters = [w for w in words if w != "&"]
    keys = {_key(name), "".join(letters[:2])}
    if letters and len(letters[0]) >= 4 and letters[0] not in GENERIC_FIRST:
        keys.add(letters[0])
    if len(letters) >= 2 and len(letters[-1]) >= 5 and letters[-1] not in GENERIC_LAST:
        keys.add(letters[-1])                   # "lilly" for Eli Lilly, "roche" for Genentech/Roche
    if len(words) >= 2:
        keys |= {k for k in ("".join("n" if w == "&" else w[0] for w in words),
                             "".join(w[0] for w in letters)) if len(k) >= 3}
    return {k for k in keys if k}


def source_kind(host: str, owned: bool, rivals: set[str]) -> str:
    """owned, rival, review, community, media or other. `rivals` holds the domain_keys of each named rival."""
    if owned:
        return "owned"
    bare = host.split("/")[0]
    labels = bare.split(".")
    on = lambda sites: any(bare == d or bare.endswith("." + d) for d in sites)  # noqa: E731
    if bare not in PLACEHOLDER_HOSTS and len(labels) > 1 and labels[-2] in rivals:
        return "rival"
    if on(REVIEW_SITES):
        return "review"
    if on(COMMUNITY_SITES) or labels[0] in ("community", "forum", "forums"):
        return "community"
    if on(MEDIA_SITES) or labels[0] in ("blog", "news") or ".substack." in f".{bare}.":
        return "media"
    return "other"


def cited_sources(run: Run) -> dict:
    """Every site cited in a counted buyer or brand answer, ranked by how many answers cite it.

    On buyer answers each site also records which brands it was cited beside: the rivals the answer
    named, and how many of those answers mentioned the brand. A third-party site cited beside rivals in
    buyer answers that never mention the brand is a `rival_only` source: the page to get onto."""
    tally: dict[str, dict] = {}
    n = cited = 0
    for kind, key in (("blind", "buyer"), ("named", "brand")):
        for a, e in _counted(run, kind):
            n += 1
            hosts = {_host(u): u for u in a.citations if _host(u)}
            cited += bool(hosts)
            for host, url in hosts.items():
                row = tally.setdefault(host, dict(domain=host, url=url, answers=0, buyer=0, brand=0,
                                                  owned=domain_matches(url, run.profile.all_domains()),
                                                  with_brand=0, rivals=Counter(), probes=[]))
                row["answers"] += 1
                row[key] += 1
                if kind == "blind":
                    row["with_brand"] += e.mentioned
                    row["rivals"].update({c.lower(): c for c in e.competitor_recommendations}.values())
                    row["probes"].append(a.probe_id)
    rows = sorted(tally.values(), key=lambda r: -r["answers"])  # stable: ties keep first-seen order
    brand = set().union(*(domain_keys(n) for n in run.profile.names()))
    named = {}
    for name in (name for r in rows for name in r["rivals"]):
        for k in domain_keys(name) - brand:
            named.setdefault(k, set()).add(name)
    owner = {k: min(ns, key=lambda n: (_key(n) != k, len(n), n)) for k, ns in named.items()}
    for r in rows:
        r["kind"] = source_kind(r["domain"], r["owned"], set(owner))
        labels = r["domain"].split("/")[0].split(".")
        r["rival"] = owner.get(labels[-2]) if r["kind"] == "rival" else None   # whose site it is
        r["rivals"] = [dict(name=k, count=c) for k, c in r["rivals"].most_common()]
    rival_only = sorted((r for r in rows if r["rivals"] and not r["with_brand"] and r["kind"] not in ("owned", "rival")),
                        key=lambda r: (-r["buyer"], -len(r["rivals"])))
    reason = None
    if not n:
        reason = "No answer counted toward the scores, so there were no citations to read."
    elif not rows:
        reason = f"None of the {n} answers that count cited a source."
    return dict(answers=n, cited_answers=cited, sources=rows, reason=reason,
                rival_only=[r["domain"] for r in rival_only])


def share_of_voice(run: Run) -> dict:
    """On the counted unbranded questions: answers recommending the brand vs answers recommending each competitor."""
    rows = list(_counted(run, "blind"))
    rivals: Counter = Counter()
    spelled: dict[str, str] = {}
    for _, e in rows:
        for key, name in {c.lower(): c for c in e.competitor_recommendations}.items():
            rivals[key] += 1
            spelled.setdefault(key, name)
    reason = None
    if not rows:
        reason = "No unbranded question produced an answer that counts, so there is no voice to share."
    elif not rivals:
        reason = f"No competitor was recommended in any of the {len(rows)} buyer answers that count."
    return dict(questions=len(rows), brand=run.profile.name,
                brand_recommended=sum(e.recommended for _, e in rows),
                rivals=[dict(name=spelled[k], count=c) for k, c in rivals.most_common(RIVALS)],
                tied_top=sum(c == max(rivals.values()) for c in rivals.values()) if rivals else 0,
                reason=reason)


def _same_search(q: str) -> str:
    """Near-duplicate searches share a key: case, years and punctuation ignored."""
    return " ".join(re.sub(r"[^\w\s]|\b(?:19|20)\d\d\b", " ", q.lower()).split())


def searches(run: Run) -> dict:
    """The web searches the model ran for the buyer questions (every try), near-duplicates grouped.

    Not a score: every buyer answer that came back is read, counted or not. The Responses API does
    not say which search found which page, so a group's pages are the ones cited in the answers that
    ran it, and `owned_pages` are those on the brand's own site.
    """
    buyer = {p.id for p in run.probes if p.kind == "blind" and p.phase == "baseline"}
    got = [a for a in [*run.answers, *run.repeat_answers] if a.probe_id in buyer and a.status == "ok"]
    recorded = [a for a in got if a.searches is not None]
    domains = run.profile.all_domains()
    groups: dict[str, dict] = {}
    questions: dict[str, list[dict]] = {}  # probe id -> each try's searches and cited pages
    for a in sorted(recorded, key=lambda a: a.try_no):
        owned = [u for u in a.citations if domain_matches(u, domains)]
        questions.setdefault(a.probe_id, []).append(dict(try_no=a.try_no, searches=a.searches,
                                                         pages=a.citations, owned_pages=owned))
        spellings: dict[str, list[str]] = {}
        for q in a.searches:
            if _same_search(q):
                spellings.setdefault(_same_search(q), []).append(q)
        for key, qs in spellings.items():
            g = groups.setdefault(key, dict(query=qs[0], variants=[], answers=0, questions=[], pages=[],
                                            owned_pages=[]))
            g["answers"] += 1
            for field, items in (("variants", qs), ("questions", [a.probe_id]), ("pages", a.citations),
                                 ("owned_pages", owned)):
                g[field] += [x for x in items if x not in g[field]]
    rows = sorted(groups.values(), key=lambda g: -g["answers"])  # stable: ties keep first-seen order
    for g in rows:
        g["variants"].remove(g["query"])
    reason = None
    if not got:
        reason = "No unbranded question was answered, so there were no searches to read."
    elif not recorded:
        reason = "Which searches the AI ran was not recorded for this run."
    elif not rows:
        reason = f"The AI answered all {len(recorded)} buyer answers without searching the web."
    return dict(answers=len(recorded), searched_answers=sum(bool(a.searches) for a in recorded),
                runs=sum(len(a.searches or []) for a in recorded), searches=rows, questions=questions,
                owned=sum(bool(g["owned_pages"]) for g in rows), reason=reason)


def insights(run: Run) -> dict:
    return dict(sources=cited_sources(run), voice=share_of_voice(run), searches=searches(run))
