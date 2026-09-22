"""Buyer questions grounded in real demand: what people actually type, not what a model imagines.

For one category (a buyer front's), harvest real search phrasings, keep the ones that carry buying
intent, group them by meaning and ask one representative per group, heaviest group first. A scrappy
answer to "are these even real questions?", not a volume estimate.

  * Sources: Google autocomplete (the public suggestqueries endpoint, one short GET per seed below)
    and Reddit's public search JSON, which refuses unauthenticated clients from many networks (it
    returned 403 while this was built); a refusal is stated, never worked around. "People also ask"
    is skipped: it exists only inside Google's result pages, and getting it means scraping them.
  * Clean in code: a phrasing that names the brand or addresses the vendor is dropped, as any
    buyer question is (agents/ana.py); so is one off the category or with no buying intent.
  * Group with embeddings (text-embedding-3-small, metered through access.py) and average-link
    clustering at a cosine threshold; the most central member stands for its group, and a group's
    weight is how many real phrasings it holds, autocomplete rank breaking ties.
  * The representative phrase is asked exactly as people typed it; no model rewords it.

Harvests are cached on disk per category for a week. Anything that fails leaves the front on the
questions onboarding wrote, with the reason stated in the run.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Callable

import reports
from agents.ana import brand_leaks, vendor_address
from agents.evaluation import content_words
from fetching import USER_AGENT
from schemas import CompanyProfile, Demand, DemandPhrase

TIMEOUT = 4
CACHE_S = 7 * 24 * 3600
AUTOCOMPLETE = "https://suggestqueries.google.com/complete/search?client=firefox&hl=en&q="
REDDIT = "https://www.reddit.com/search.json?sort=relevance&t=year&limit=25&q="
SEEDS = ("{c}", "best {c}", "how to choose {c}", "which {c}", "{c} vs", "alternatives to {c}", "{c} for")
EMBED_MODEL = "text-embedding-3-small"
MAX_PHRASES = 60
# ponytail: one fixed cosine for "same question"; tune it against saved harvests if groups come out
# too coarse (everything merges) or too fine (every phrase alone).
SAME_GROUP = 0.85
QUESTION = re.compile(r"^(what|which|who|how|is|are|should|can|does|do|any|where|why|looking for|recommend)\b|\?$",
                      re.I)
INTENT = re.compile(r"\b(best|top|free|cheap|cheapest|vs|versus|alternatives?|compare|comparison|"
                    r"recommend\w*|reviews?|for|easiest|simple|pricing)\b", re.I)


def _fetch_json(url: str):
    """The one line that reaches the network. Tests replace it."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _cache(category: str):
    return reports.DATA / "demand" / (re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")[:80] + ".json")


def harvest(category: str) -> tuple[list[dict], list[str]]:
    """-> (phrases [{text, source, rank}], one note per source that gave nothing)."""
    path = _cache(category)
    try:
        cached = json.loads(path.read_text())
        if time.time() - cached["at"] < CACHE_S:
            return cached["phrases"], cached["notes"]
    except (OSError, ValueError, KeyError):
        pass
    phrases, notes, failed = [], [], 0
    for seed in SEEDS:
        try:
            got = _fetch_json(AUTOCOMPLETE + urllib.parse.quote(seed.format(c=category)))[1]
            phrases += [dict(text=t, source="autocomplete", rank=i) for i, t in enumerate(got) if isinstance(t, str)]
        except Exception:
            failed += 1
    if failed == len(SEEDS):
        notes.append("Google autocomplete could not be reached")
    try:
        posts = _fetch_json(REDDIT + urllib.parse.quote(category))["data"]["children"]
        phrases += [dict(text=p["data"]["title"], source="reddit", rank=i) for i, p in enumerate(posts)]
    except Exception as e:
        code = getattr(e, "code", None)
        notes.append(f"Reddit refused the search (HTTP {code})" if code else "Reddit could not be reached")
    if phrases:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(at=time.time(), phrases=phrases, notes=notes)))
    return phrases, notes


def clean(phrases: list[dict], category: str, profile: CompanyProfile) -> list[dict]:
    """On the category, carrying buying intent, never naming the brand or the vendor, once each."""
    words = content_words(category)
    kept, seen = [], set()
    for p in phrases:
        text = " ".join(p["text"].split())
        key = text.lower().rstrip("?")
        if key in seen or key == category.lower() or brand_leaks(text, profile) or vendor_address(text):
            continue
        if p["source"] == "autocomplete":
            relevant = category.lower() in key and bool(INTENT.search(text) or QUESTION.search(text))
        else:  # a thread title: a question about the category, not news or a show-and-tell
            relevant = words <= content_words(text) and bool(QUESTION.search(text)) and len(text) <= 160
        if relevant:
            seen.add(key)
            kept.append({**p, "text": text})
    return kept[:MAX_PHRASES]


def _unit(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** .5 or 1.0
    return [x / n for x in v]


def cluster(vectors: list[list[float]], threshold: float = SAME_GROUP) -> tuple[list[list[int]], list[list[float]]]:
    """Average-link agglomerative clustering on cosine similarity. -> (groups of indices, similarity matrix)."""
    u = [_unit(v) for v in vectors]
    sim = [[sum(a * b for a, b in zip(x, y)) for y in u] for x in u]
    groups = [[i] for i in range(len(u))]
    link = lambda a, b: sum(sim[i][j] for i in a for j in b) / (len(a) * len(b))
    while len(groups) > 1:
        s, x, y = max((link(a, b), x, y) for x, a in enumerate(groups) for y, b in enumerate(groups) if x < y)
        if s < threshold:
            break
        groups[x] += groups.pop(y)
    return groups, sim


def embed(texts: list[str]) -> list[list[float]]:
    import access  # metered: refused at a pass's cap, charged to it after
    r = access.openai_embedding(30, model=EMBED_MODEL, input=texts, dimensions=256)
    return [d.embedding for d in r.data]


def ground(category: str, profile: CompanyProfile, n: int, embed: Callable = embed
           ) -> tuple[list[tuple[str, Demand]], str]:
    """-> (up to n (question, where it came from), heaviest group first; one sentence for the report).

    Never raises: a failure returns no questions and a sentence saying why."""
    fallback = f"so the buyer questions about {category} were written by AI"
    try:
        raw, notes = harvest(category)
        phrases = clean(raw, category, profile)
        if len(phrases) < 2:
            why = "; ".join(notes) or "no real search about it carried buying intent"
            return [], f"No real searches were found for {category} ({why}), {fallback}."
        groups, sim = cluster(embed([p["text"] for p in phrases]))
    except Exception as e:     # refused by the pass (access.Refused) is a BaseException and passes up
        return [], f"Real searches for {category} could not be grouped by meaning ({type(e).__name__}), {fallback}."
    rank = lambda g: (-len(g), min(phrases[i]["rank"] if phrases[i]["source"] == "autocomplete" else 99 for i in g))
    out = []
    for g in sorted(groups, key=rank)[:n]:
        g = sorted(g, key=lambda i: -sum(sim[i][j] for j in g))      # most central first
        out.append((phrases[g[0]]["text"], Demand(
            phrase=phrases[g[0]]["text"], source=phrases[g[0]]["source"],
            phrasings=[DemandPhrase(text=phrases[i]["text"], source=phrases[i]["source"]) for i in g])))
    sources = sorted({p["source"] for p in phrases})
    said = " and ".join("Google autocomplete" if s == "autocomplete" else "Reddit" for s in sources)
    note = (f"{len(out)} buyer questions about {category} are real searches from {said}: "
            f"{len(phrases)} phrasings grouped into {len(groups)} by meaning, the most common groups asked.")
    return out, note + (f" {'; '.join(notes)}." if notes else "")

