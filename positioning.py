"""The positioning map: where AI places the brand, where its rivals sit, and where the brand aims to be.

Each point is the mean embedding of the sentences it is built from: the brand as AI describes it (its
brand answers), each rival as AI describes it (the buyer-answer sentences that name it), and the aim:
where the customer wants to be (the claims they weighted, by weight) or, with no weights, where the
site aims (its positioning points). Each axis IS one of the company's own claims, so it always has a
name: across is how strongly a dot's sentences talk about the claim weighted highest, up how strongly
they talk about the claim the dots differ on most once the first is taken out.

It used to be PCA, with an axis named only when claims sat at both of its ends. A company's claims
all describe the company, so they sit together at one end: Amgen, Notion and Profound all got maps
with no axis names.

A similarity picture, never a measurement: it runs after every score exists and moves none of them.
"""
import math
import re
from collections import Counter
from typing import Callable, Optional

import embeddings
from schemas import MapPoint, PositioningMap, Run

MAX_RIVALS = 6         # rivals drawn, most-named first; more crowd a phone screen
MAX_SENTENCES = 20     # per point


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 3]


def _mean(vs: list[list[float]], ws: Optional[list[float]] = None) -> list[float]:
    ws = ws or [1.0] * len(vs)
    return [sum(w * x for w, x in zip(ws, c)) / sum(ws) for c in zip(*vs)]


def _text(a) -> str:
    return f"{a.label}: {a.description}" if a.description else a.label


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(_dot(v, v))
    return [x / n for x in v] if n > 1e-12 else [0.0] * len(v)


def claim_axes(means: list[list[float]], claims: list, vecs: list[list[float]]
               ) -> tuple[list[tuple[float, float]], int, int, float]:
    """-> (2D coordinates per point, x claim index, y claim index, share of the spread shown).

    Across: the claim weighted highest, or with no weights the one the points spread along most.
    Up: of the rest, the one the points spread along most once the across direction is taken out,
    so the two axes never measure the same thing twice."""
    centre = _mean(means)
    x = [[a - c for a, c in zip(p, centre)] for p in means]
    dirs = [_unit([a - c for a, c in zip(v, centre)]) for v in vecs]
    spread = lambda d: sum(_dot(p, d) ** 2 for p in x)  # noqa: E731
    weighted = [i for i, c in enumerate(claims) if c.intended_weight]
    ix = (max(weighted, key=lambda i: claims[i].intended_weight) if weighted
          else max(range(len(claims)), key=lambda i: spread(dirs[i])))
    ux = dirs[ix]
    rest = {i: _unit([a - _dot(d, ux) * b for a, b in zip(d, ux)]) for i, d in enumerate(dirs) if i != ix}
    iy = max(rest, key=lambda i: spread(rest[i]))
    uy = rest[iy]
    total = sum(_dot(p, p) for p in x) or 1.0
    return [(_dot(p, ux), _dot(p, uy)) for p in x], ix, iy, (spread(ux) + spread(uy)) / total


def build(run: Run, embed: Optional[Callable] = None) -> PositioningMap:
    embed = embed or embeddings.embed
    brand = run.profile.name
    by_id = {p.id: p for p in run.probes}
    ok = [a for a in [*run.answers, *run.repeat_answers] if a.status == "ok" and a.probe_id in by_id]
    seen = list(dict.fromkeys(s for a in ok if by_id[a.probe_id].kind == "named"
                              and by_id[a.probe_id].phase == "baseline" for s in _sentences(a.text)))
    wanted = [a for a in run.attributes if a.label and a.intended_weight]
    aim = "intended" if wanted else "site"
    intended = [_text(a) for a in wanted] or [p.text for p in run.profile.positioning_points] \
        or [q for a in run.attributes for q in a.claim_quotes]
    blind = {pid for pid, p in by_id.items() if p.kind == "blind" and p.phase == "baseline"}
    buyer = list(dict.fromkeys(s for a in ok if a.probe_id in blind for s in _sentences(a.text)))
    named = Counter()
    spelled: dict[str, str] = {}
    for e in [*run.evaluations, *run.repeat_evaluations]:
        if e.probe_id in blind:
            for c in {c.lower(): c for c in e.competitor_recommendations if c.lower() != brand.lower()}.items():
                named[c[0]] += 1
                spelled.setdefault(*c)
    notes, rivals = [], {}
    for key, _ in named.most_common():
        said = [s for s in buyer if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", s, re.I)]
        if said and len(rivals) < MAX_RIVALS:
            rivals[spelled[key]] = said[:MAX_SENTENCES]
    if len(named) > len(rivals):
        notes.append(f"{len(named) - len(rivals)} less-named rivals were left off "
                     f"(at most {MAX_RIVALS}, and only rivals a buyer answer describes in a sentence).")
    claims = [a for a in run.attributes if a.label and not a.discovered]
    reason = ("No brand answer came back, so there is nothing AI said about the brand to place." if not seen
              else "The site gave no positioning to place." if not intended
              else "Fewer than two of the company's own claims, so there is nothing to name the axes by."
              if len(claims) < 2
              else "No buyer answer named a rival, so there is nothing to place the brand against."
              if not named
              else "Buyer answers named rivals but never described one in a sentence, so there is nothing "
                   "to place the brand against." if not rivals else None)
    if reason:
        return PositioningMap(provenance="live_api", aim=aim, reason=reason, notes=notes)

    groups = [(brand, "seen", seen[:MAX_SENTENCES]), (brand, "intended", intended[:MAX_SENTENCES]),
              *((name, "rival", ss) for name, ss in rivals.items())]
    texts = list(dict.fromkeys([*(s for _, _, ss in groups for s in ss), *(_text(a) for a in claims)]))
    vec = dict(zip(texts, embed(texts)))
    weights = {1: [a.intended_weight for a in wanted][:MAX_SENTENCES]} if wanted else {}
    means = [_mean([vec[s] for s in ss], weights.get(i)) for i, (_, _, ss) in enumerate(groups)]
    coords, ix, iy, shown = claim_axes(means, claims, [vec[_text(a)] for a in claims])
    # the claim the aim lies furthest beyond AI's picture along, if it lies beyond it on either
    drift = [(coords[1][k] - coords[0][k], claims[i].label) for k, i in enumerate((ix, iy))]
    toward = max(drift)[1] if max(drift)[0] > 0 else None

    points = [MapPoint(name=name, kind=kind, x=round(c[0], 4), y=round(c[1], 4), sentences=ss,
                       similarity=None if i == 0 else round(embeddings.cosine(m, means[0]), 2))
              for i, ((name, kind, ss), c, m) in enumerate(zip(groups, coords, means))]
    closest = [p.name for p in sorted((p for p in points if p.kind == "rival"), key=lambda p: -p.similarity)][:2]
    return PositioningMap(provenance="live_api", model=embeddings.MODEL, aim=aim, points=points,
                          x_axis=[claims[ix].label], y_axis=[claims[iy].label], explained=round(shown, 2),
                          closest=closest, toward=toward, notes=notes)
