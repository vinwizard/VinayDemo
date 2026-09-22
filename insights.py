"""Two report panels read off a saved run: which sites AI cites (and beside which brands), and share
of voice. No model calls.

Both count only baseline answers that count toward the scores (`scoring.eligible`), so an excluded
or exploratory answer can never move them, and every empty panel carries the reason it is empty.
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


def source_kind(host: str, owned: bool, rivals: set[str]) -> str:
    """owned, rival, review, community, media or other. `rivals` holds the _key of each named rival."""
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
    named, and how many of those answers mentioned the brand. A site cited beside rivals in buyer
    answers that never mention the brand is a `rival_only` source: the page to get onto."""
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
    rival_keys = {_key(name) for r in rows for name in r["rivals"]} - {_key(run.profile.name), ""}
    for r in rows:
        r["kind"] = source_kind(r["domain"], r["owned"], rival_keys)
        r["rivals"] = [dict(name=k, count=c) for k, c in r["rivals"].most_common()]
    rival_only = sorted((r for r in rows if r["rivals"] and not r["with_brand"] and r["kind"] != "owned"),
                        key=lambda r: (-r["buyer"], -len(r["rivals"])))
    reason = None
    if not n:
        reason = "No answer counted toward the scores, so there were no citations to read."
    elif not rows:
        reason = f"None of the {n} answers that count cited a source."
    return dict(answers=n, cited_answers=cited, sources=rows, reason=reason,
                rival_only=[r["domain"] for r in rival_only])


def share_of_voice(run: Run) -> dict:
    """On the counted buyer questions: answers recommending the brand vs answers recommending each competitor."""
    rows = list(_counted(run, "blind"))
    rivals: Counter = Counter()
    spelled: dict[str, str] = {}
    for _, e in rows:
        for key, name in {c.lower(): c for c in e.competitor_recommendations}.items():
            rivals[key] += 1
            spelled.setdefault(key, name)
    reason = None
    if not rows:
        reason = "No buyer question produced an answer that counts, so there is no voice to share."
    elif not rivals:
        reason = f"No competitor was recommended in any of the {len(rows)} buyer answers that count."
    return dict(questions=len(rows), brand=run.profile.name,
                brand_recommended=sum(e.recommended for _, e in rows),
                rivals=[dict(name=spelled[k], count=c) for k, c in rivals.most_common(RIVALS)],
                tied_top=sum(c == max(rivals.values()) for c in rivals.values()) if rivals else 0,
                reason=reason)


def insights(run: Run) -> dict:
    return dict(sources=cited_sources(run), voice=share_of_voice(run))
