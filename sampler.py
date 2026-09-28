"""Sampler-lite: how many buyer questions a front needs for a stated margin, and when it may stop.

A buyer question gives the same answer almost every time it is asked again: on the Amgen run, 35 of
36 re-asks agreed (intraclass correlation 0.90, 2026-09-28). What a front's number does not know
yet is the questions it has not asked, not the wobble of one, so every call asks a FRESH question
from the front's frozen pool and each front is sized for a stated margin at 95%:

  look 1  ask LOOK1 questions. If the interval of "named you" is already within ±margin — a front
          where AI almost never, or almost always, names the company — stop there.
  look 2  otherwise ask the rest of the pool, sized so even a 50% rate meets the margin.

The 5% error is split 1% at look 1 and 4% at look 2, so the reported interval holds the true rate
with at least 95% whichever look a front stopped at, and look 2 is the known most a front can cost.
Simulated on cells fitted to that run: the stop is correct at 96.5–97%, a front AI never names stops
at look 1, and a mid-range front costs look 2. A bandit or a Bayesian allocator saved nothing there,
so neither is here. One re-ask per front (WOBBLE_AUDIT) keeps the wobble visible in the report.
"""
from typing import Optional

from config import setting
from schemas import FrontSample, Probe, Run, SamplerReport
from scoring import eligible, wilson, z_for

MARGIN_ENV = "TARGET_MARGIN"         # points of "named you", ± at 95%
DEFAULT_MARGIN = 20
MIN_MARGIN, MAX_MARGIN = 5, 50
BUDGET_ENV = "RUN_BUDGET_USD"        # the most one run's measured calls may spend; unset: look 2's size is the cap
WOBBLE_ENV = "WOBBLE_AUDIT"          # re-asks per front, of one of its look-1 questions
DEFAULT_WOBBLE = 1
ALPHA1, ALPHA2 = 0.01, 0.04


def margin() -> int:
    return min(MAX_MARGIN, setting(MARGIN_ENV, DEFAULT_MARGIN, floor=MIN_MARGIN))


def wobble_audit() -> int:
    return setting(WOBBLE_ENV, DEFAULT_WOBBLE)


def run_budget() -> Optional[float]:
    import os
    try:
        v = float(os.environ.get(BUDGET_ENV) or 0)
    except ValueError:
        return None
    return v if v > 0 else None


def half_width(k: int, n: int, z: float) -> float:
    lo, hi = wilson(k, n, z)
    return (hi - lo) / 2


def looks(points: Optional[int] = None) -> tuple[int, int]:
    """-> (look 1, look 2) questions a front asks for ±points at 95%: look 1 is the fewest where a
    front AI never names the company already meets it; look 2 the fewest where a 50% rate does."""
    eps = (points or margin()) / 100
    z1, z2 = z_for(ALPHA1), z_for(ALPHA2)
    n1 = next(n for n in range(1, 2000) if half_width(0, n, z1) <= eps)
    n2 = next(n for n in range(n1, 4000) if half_width(n // 2, n, z2) <= eps)
    return n1, n2


# ---------------------------------------------------------------- one run
def front_of(run: Run) -> dict[str, str]:
    """buyer probe id -> its front, for fronted baseline questions only."""
    topic = {t.id: t.front for t in run.topics}
    return {p.id: topic[p.topic_id] for p in run.probes
            if p.kind == "blind" and p.phase == "baseline" and topic.get(p.topic_id)}


def start(run: Run) -> SamplerReport:
    """At freeze: every front's pool asks its first look-1 questions; the rest wait for look 2.
    The wobble audit re-asks the first question of each front."""
    n1, n2 = looks()
    fronts = front_of(run)
    report = SamplerReport(margin=margin(), looks=[n1, n2], budget_usd=run_budget())
    for front in dict.fromkeys(fronts.values()):
        pool = [p for p in run.probes if fronts.get(p.id) == front]
        report.held += [p.id for p in pool[n1:]]
        report.wobble += [p.id for p in pool[:1]] * bool(wobble_audit())
        report.fronts.append(FrontSample(front=front, pool=len(pool), asked=min(n1, len(pool))))
    return report


def rate(run: Run, ids: set[str]) -> tuple[int, int]:
    """(named, judged) over the FIRST ask of each question: fresh questions, one vote each."""
    answers = {a.probe_id: a for a in run.answers}
    k = n = 0
    for e in run.evaluations:
        a = answers.get(e.probe_id)
        if e.probe_id in ids and a is not None and eligible(a, e)[0]:
            n += 1
            k += e.mentioned
    return k, n


def decide(run: Run, spent: float = 0.0) -> list[str]:
    """After look 1: which fronts stop, which go on to look 2. -> the probe ids released for look 2.
    A front whose look 2 would take the run past its budget stops, its margin not met."""
    report = run.sampler
    fronts = front_of(run)
    released, asked = [], sum(f.asked for f in report.fronts)
    per_call = spent / asked if asked else 0.0
    for f in report.fronts:
        ids = {pid for pid, fr in fronts.items() if fr == f.front and pid not in report.held}
        k, n = rate(run, ids)
        waiting = [pid for pid in report.held if fronts.get(pid) == f.front]
        if not waiting or half_width(k, n, z_for(ALPHA1)) * 100 <= report.margin:
            f.stopped_early = bool(waiting)
            continue
        if report.budget_usd and spent + per_call * (len(released) + len(waiting)) > report.budget_usd:
            f.note = (f"Look 2 would take the run past its ${report.budget_usd:.2f} budget, so this front "
                      f"stopped at {f.asked} questions and its margin is wider than ±{report.margin}.")
            continue
        released += waiting
        f.look, f.asked = 2, f.pool
    report.held = [pid for pid in report.held if pid not in set(released)]
    report.decided = True
    return released


def drop_unasked(run: Run) -> None:
    """The questions a front never needed leave the run's probes (and any topic left empty) for
    `unasked`, so every reader of the run sees only what was asked; the frozen hash covers both."""
    report = run.sampler
    held = set(report.held)
    report.unasked += [p for p in run.probes if p.id in held]
    run.probes = [p for p in run.probes if p.id not in held]
    kept = {p.topic_id for p in run.probes}
    run.topics = [t for t in run.topics if t.id in kept or t.kind != "buyer"]
    report.held = []


def finish(run: Run) -> None:
    """Each front's rate of "named you" with its interval, at the look it stopped at."""
    report = run.sampler
    fronts = front_of(run)
    for f in report.fronts:
        ids = {pid for pid, fr in fronts.items() if fr == f.front}
        k, n = rate(run, ids)
        lo, hi = wilson(k, n, z_for(ALPHA2 if f.look == 2 else ALPHA1))
        f.named, f.judged = k, n
        f.rate = round(100 * k / n, 1) if n else None
        f.interval = [round(100 * lo, 1), round(100 * hi, 1)] if n else None
        f.margin_met = bool(n) and (hi - lo) * 50 <= report.margin + 1e-9


def frozen(run: Run) -> list[Probe]:
    """The pool as frozen: what was asked plus what was not needed, in id order."""
    return sorted([*run.probes, *(run.sampler.unasked if run.sampler else [])], key=lambda p: p.id)


if __name__ == "__main__":
    assert looks(20) == (10, 23) and looks(15) == (16, 43)   # the design review's numbers
    assert looks(50)[0] <= looks(50)[1] < looks(20)[1]
    print("ok")
