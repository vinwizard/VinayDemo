"""Two report panels read off a saved run: which sites AI cites, and share of voice. No model calls.

Both count only baseline answers that count toward the scores (`scoring.eligible`), so an excluded
or exploratory answer can never move them, and every empty panel carries the reason it is empty.
"""
from collections import Counter
from urllib.parse import urlparse

from schemas import Run
from scoring import domain_matches, eligible

TARGET_MIN = 2  # a third-party site cited in this many answers is worth a presence; once is chance
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


def cited_sources(run: Run) -> dict:
    """Every site cited in a counted buyer or brand answer, ranked by how many answers cite it."""
    tally: dict[str, dict] = {}
    n = cited = 0
    for kind, key in (("blind", "buyer"), ("named", "brand")):
        for a, _ in _counted(run, kind):
            n += 1
            hosts = {_host(u): u for u in a.citations if _host(u)}
            cited += bool(hosts)
            for host, url in hosts.items():
                row = tally.setdefault(host, dict(domain=host, answers=0, buyer=0, brand=0,
                                                  owned=domain_matches(url, run.profile.all_domains())))
                row["answers"] += 1
                row[key] += 1
    rows = sorted(tally.values(), key=lambda r: -r["answers"])  # stable: ties keep first-seen order
    for r in rows:
        r["target"] = not r["owned"] and r["answers"] >= TARGET_MIN
    reason = None
    if not n:
        reason = "No answer counted toward the scores, so there were no citations to read."
    elif not rows:
        reason = f"None of the {n} answers that count cited a source."
    return dict(answers=n, cited_answers=cited, sources=rows, reason=reason)


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
                reason=reason)


def insights(run: Run) -> dict:
    return dict(sources=cited_sources(run), voice=share_of_voice(run))
