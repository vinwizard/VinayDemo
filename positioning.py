"""The positioning map: where AI places the brand, where its rivals sit, and where the brand aims to be.

Each point is the mean embedding of the sentences it is built from: the brand as AI describes it (its
brand answers), each rival as AI describes it (the buyer-answer sentences that name it), and the aim:
where the customer wants to be (the claims they weighted, by weight) or, with no weights, where the
site aims (its positioning points). The points are projected to 2D by PCA, and
each axis is named by the claim whose embedding lines up with it best, or left unnamed when none does.

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
AXIS_MIN = 0.2         # a claim names an axis end only if its cosine with the axis is at least this


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 3]


def _mean(vs: list[list[float]], ws: Optional[list[float]] = None) -> list[float]:
    ws = ws or [1.0] * len(vs)
    return [sum(w * x for w, x in zip(ws, c)) / sum(ws) for c in zip(*vs)]


def _text(a) -> str:
    return f"{a.label}: {a.description}" if a.description else a.label


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def pca2(points: list[list[float]]) -> tuple[list[tuple[float, float]], list[list[float]], float]:
    """-> (2D coordinates per point, the two unit axis directions, share of the spread they show).

    Power iteration on the n x n Gram matrix of the centred points: n is a handful, the vectors are
    long, so this is small and needs no numpy."""
    n, mean = len(points), _mean(points)
    x = [[a - m for a, m in zip(p, mean)] for p in points]
    g = [[_dot(a, b) for b in x] for a in x]
    total = sum(g[i][i] for i in range(n)) or 1.0
    coords, axes, shown = [[0.0, 0.0] for _ in range(n)], [], 0.0
    for k in range(2):
        u = [1.0 + i for i in range(n)]  # deterministic start
        lam = 0.0
        for _ in range(300):
            w = [_dot(row, u) for row in g]
            norm = math.sqrt(_dot(w, w))
            if norm < 1e-12:
                break
            u, lam = [a / norm for a in w], norm
        if lam < 1e-12:
            axes.append([0.0] * len(mean))
            continue
        shown += lam
        s = math.sqrt(lam)
        for i in range(n):
            coords[i][k] = u[i] * s
        axes.append([sum(u[i] * x[i][j] for i in range(n)) / s for j in range(len(mean))])
        g = [[g[i][j] - lam * u[i] * u[j] for j in range(n)] for i in range(n)]  # deflate
    return [tuple(c) for c in coords], axes, shown / total


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
    reason = ("No brand answer came back, so there is nothing AI said about the brand to place." if not seen
              else "The site gave no positioning to place." if not intended
              else "No buyer answer named a rival, so there is nothing to place the brand against."
              if not named
              else "Buyer answers named rivals but never described one in a sentence, so there is nothing "
                   "to place the brand against." if not rivals else None)
    if reason:
        return PositioningMap(provenance="live_api", aim=aim, reason=reason, notes=notes)

    groups = [(brand, "seen", seen[:MAX_SENTENCES]), (brand, "intended", intended[:MAX_SENTENCES]),
              *((name, "rival", ss) for name, ss in rivals.items())]
    candidates = [a for a in run.attributes if a.label]
    ends = [_text(a) for a in candidates]
    texts = list(dict.fromkeys([*(s for _, _, ss in groups for s in ss), *ends]))
    vec = dict(zip(texts, embed(texts)))
    weights = {1: [a.intended_weight for a in wanted][:MAX_SENTENCES]} if wanted else {}
    means = [_mean([vec[s] for s in ss], weights.get(i)) for i, (_, _, ss) in enumerate(groups)]
    coords, axes, shown = pca2(means)

    # PCA signs are arbitrary: orient each axis so the aim sits at or beyond where AI places it.
    flip = [-1 if coords[1][k] < coords[0][k] else 1 for k in range(2)]
    centre = _mean(means)
    labels = []
    for k, axis in enumerate(axes):
        scored = sorted((flip[k] * embeddings.cosine([v - c for v, c in zip(vec[t], centre)], axis), a.label)
                        for t, a in zip(ends, candidates))
        ok_ends = len(scored) > 1 and scored[0][0] <= -AXIS_MIN and scored[-1][0] >= AXIS_MIN
        labels.append([scored[0][1], scored[-1][1]] if ok_ends else [])
    drift = [abs(coords[1][k] - coords[0][k]) for k in range(2)]
    k = max(range(2), key=lambda i: drift[i])
    toward = labels[k][1] if labels[k] and drift[k] > 0 else None

    points = [MapPoint(name=name, kind=kind, x=round(flip[0] * c[0], 4), y=round(flip[1] * c[1], 4),
                       sentences=ss, similarity=None if i == 0 else round(embeddings.cosine(m, means[0]), 2))
              for i, ((name, kind, ss), c, m) in enumerate(zip(groups, coords, means))]
    closest = [p.name for p in sorted((p for p in points if p.kind == "rival"), key=lambda p: -p.similarity)][:2]
    return PositioningMap(provenance="live_api", model=embeddings.MODEL, aim=aim, points=points, x_axis=labels[0],
                          y_axis=labels[1], explained=round(shown, 2), closest=closest, toward=toward,
                          notes=notes)
