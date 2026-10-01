"""Orchestrator: ordinary code owning LangGraph state, routing, budgets and validation."""
import uuid
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import access
import dispatch
import drift
import sampler
from agents import ana, evaluation, win_back
from labels import probe_name
from schemas import Run, VisibilitySet
from scoring import (MIN_INTERVAL_ANSWERS, echo_draws, gap_verdict, interval, low_confidence, score_topic,
                     visibility_by_question, visibility_draws, visibility_over_tries)

MAX_NAMED = 8
MAX_FOLLOWUP = 4
MAX_ADAPTIVE_ROUNDS = 1
RECURSION_LIMIT = 25


def max_baseline() -> int:
    """The most buyer questions a run may plan: `ana.max_topics()` topics of PER_TOPIC."""
    return ana.max_topics() * ana.PER_TOPIC


def repeat_sampled(buyer: list, n: int) -> list:
    """The `n` buyer questions that are asked BUYER_TRIES times instead of once.

    Evenly spaced through the planned order rather than the first `n`, because the fronts are
    contiguous there: with two fronts and the default sample of 2, one question comes from each, so
    the wobble is not read off one category alone. Deterministic, so a resumed run re-asks the same
    questions and `try_no` keeps meaning the same thing.
    """
    if n <= 0 or not buyer:
        return []
    step = len(buyer) / min(n, len(buyer))
    return [buyer[int(i * step)] for i in range(min(n, len(buyer)))]


STAGES = {  # node -> (UI stage, logical agent). Both strings are shown to the reader verbatim.
    "plan_brand": ("Topic planning", "Agent 2 · Question planner"),
    "plan_aiming": ("Topic planning", "Agent 2 · Question planner"),
    "perceive": ("Perception gap", "Agent 3 · Answer evaluation"),
    "plan_buyer": ("Topic planning", "Agent 2 · Question planner"),
    "validate_and_freeze": ("Topic planning", "Orchestrator"),
    "execute_or_replay": ("Baseline / Follow-up", "Orchestrator"),
    "evaluate": ("Gap evaluation", "Agent 3 · Answer evaluation"),
    "choose_followup": ("Follow-up", "Agent 2 · Question planner"),
    "measure_drift": ("Perception gap", "Agent 3 · Answer evaluation"),
    "build_gap_report": ("Report", "Agent 3 · Answer evaluation"),
}


class State(TypedDict):
    run: Run
    provider: Any
    rounds: int
    asks: Any        # Asks: this run's questions in flight


class Asks:
    """A run's asks in flight. A question is submitted the moment it is frozen and collected when a
    later step needs its answer, so the brand questions, the aimed front and the placed front are
    asked side by side while the graph plans what depends on them. Live asks go to the process-wide
    dispatcher (dispatch.py), under this run's key; a provider with `concurrency` 1 (the replay, and
    tests that want one call at a time) is asked inline, in order, as before.
    The graph thread is the only one that touches the run: a worker returns an Answer, nothing more."""

    def __init__(self, provider, dispatcher: Optional[dispatch.Dispatcher], key):
        self.provider, self.key = provider, key
        self.dispatcher = dispatcher if getattr(provider, "concurrency", 1) > 1 else None
        self.pending: dict[tuple[str, int], Future] = {}
        self.decided: set = set()     # fronts the sampler has decided

    def _ask(self, probe, try_no):
        return self.provider.answer(probe) if try_no == 1 else self.provider.answer(probe, try_no=try_no)

    def submit(self, jobs: list) -> None:
        for p, t in jobs:
            if (p.id, t) in self.pending:
                continue
            if self.dispatcher:
                self.pending[(p.id, t)] = self.dispatcher.submit(self.key, self._ask, p, t)
            else:
                fut = Future()
                fut.set_result(self._ask(p, t))
                self.pending[(p.id, t)] = fut

    def cancel(self) -> None:
        if self.dispatcher:
            self.dispatcher.cancel(self.key)


def askable(run: Run, provider) -> list[tuple]:
    """(probe, try) for every frozen question not answered and not waiting for look 2, plus the
    wobble's repeat asks. Every baseline buyer question is asked once; a small deterministic sample
    of them is asked `tries` times, each in a fresh context, which is what the wobble estimate needs.
    Replay has one authored answer per question, so a fixture provider has no `tries`."""
    done = {a.probe_id for a in run.answers}
    held = set(run.sampler.held) if run.sampler else set()
    todo = [p for p in run.probes if p.id not in done and p.id not in held]
    tries = getattr(provider, "tries", 1)
    have = {(a.probe_id, a.try_no) for a in run.repeat_answers}
    buyer_probes = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline" and p.id not in held]
    sampled = ([p for p in buyer_probes if p.id in run.sampler.wobble] if run.sampler
               else repeat_sampled(buyer_probes, getattr(provider, "repeat_sample", 0)))
    return [(p, 1) for p in todo] + [(p, t) for p in sampled for t in range(2, tries + 1) if (p.id, t) not in have]


FRONT_ORDER = {"placed": 0, "both": 0, "aiming": 1, None: 2}


def canonical(run: Run) -> None:
    """Saved order never depends on which answer came back first. It is the order a run asking one
    step at a time had: the placed front, the aimed one, the claims' questions, then the brand
    questions and the follow-ups; answers brand first, then look 1, look 2 and the follow-ups."""
    rank = lambda t: 3 if t.kind == "perception" else FRONT_ORDER[t.front]
    run.topics.sort(key=rank)
    of = {t.id: rank(t) for t in run.topics}
    run.probes.sort(key=lambda p: 4 if p.phase == "followup" else of.get(p.topic_id, 3))
    index = {p.id: i for i, p in enumerate(run.probes)}
    look2 = set()
    if run.sampler:
        fronts = sampler.front_of(run)
        for f in [f for f in run.sampler.fronts if f.look == 2]:   # its pool past look 1, in pool order
            look2 |= set([p.id for p in run.probes if fronts.get(p.id) == f.front][run.sampler.looks[0]:])
        run.sampler.fronts.sort(key=lambda f: FRONT_ORDER[f.front])
        # a front's questions are numbered in pool order; the placed front's ids are the only "placed-" ones
        for ids in (run.sampler.wobble, run.sampler.held):
            ids.sort(key=lambda pid: (not pid.startswith("placed-"), index.get(pid, 0)))
        run.sampler.unasked.sort(key=lambda p: not p.id.startswith("placed-"))
    by = {p.id: p for p in run.probes}

    def stage(pid: str) -> tuple:
        p = by.get(pid)
        if p is None:
            return (5, 0)
        return (3 if p.phase == "followup" else 0 if p.kind == "named" else 2 if pid in look2 else 1, index[pid])
    run.answers.sort(key=lambda a: stage(a.probe_id))
    run.evaluations.sort(key=lambda e: stage(e.probe_id))
    run.repeat_answers.sort(key=lambda a: (index.get(a.probe_id, 0), a.try_no))


class ValidationError(Exception):
    pass


def plan_brand(s: State):
    """Branded questions first: the unbranded questions are planned from what their answers say."""
    run, provider = s["run"], s["provider"]
    if check := getattr(provider, "check_profile", None):
        check(run.profile)   # an edited profile never receives the bundled replay
    run.attributes = provider.attributes()
    named = provider.named_probes()
    errors = ana.validate_named_probes(named, run.attributes)
    if len(named) > MAX_NAMED:
        errors.append(f"{len(named)} named questions exceeds {MAX_NAMED}")
    if errors:
        raise ValidationError("; ".join(errors))
    run.topics, run.probes = ([ana.perception_topic()] if named else []), named
    run.log.append(f"Question planner prepared {len(named)} branded questions and "
                   f"{len(run.attributes)} attributes; unbranded questions on where AI places it are "
                   "planned from their answers.")
    s["asks"].submit(askable(run, provider))
    return {"run": run}


def plan_aiming(s: State):
    """Where the company aims to be, planned and asked beside the brand questions: its category is
    the customer's own, so nothing in it waits for a brand answer. Only a provider that plans fronts
    one at a time offers it (live); the replay plans its one authored set after the brand answers."""
    run, provider = s["run"], s["provider"]
    early = getattr(provider, "plan_aiming", None)
    if early is None or not run.profile.core_category:
        return {"run": run}
    topics, probes = early(run.profile)
    if not probes:
        return {"run": run}   # nothing to ask on it; plan_buyer says why
    fill_fit(run, topics)
    if errors := ana.validate_probes(probes, topics, run.profile):
        raise ValidationError("; ".join(errors))
    run.topics, run.probes = topics + run.topics, probes + run.probes
    if getattr(provider, "sampler", False):
        run.sampler = sampler.start(run)
    buyer = [p for p in probes if p.phase == "baseline"]
    run.log.append(f"Unbranded questions on where it aims to be ({run.profile.core_category}): {len(buyer)} "
                   "frozen and asked beside the brand questions"
                   + (f", {run.sampler.looks[0]} first" if run.sampler else "") + ".")
    s["asks"].submit(askable(run, provider))
    return {"run": run}


def fill_fit(run: Run, topics: list) -> None:
    """Fit evidence always resolves against the approved profile."""
    points = {pp.id: pp for pp in run.profile.positioning_points}
    for t in topics:
        t.fit_evidence_ids = t.fit_evidence_ids or [e for pid in t.positioning_point_ids if pid in points
                                                    for e in points[pid].evidence_ids]


def perceive(s: State):
    """Perception layer: extract attribute observations from the brand answers, then discover the
    ones nobody declared.

    Observations are re-derived from the answers rather than carried in state, so the drift map can
    never contain an attribute whose quote is no longer verbatim in the answer it came from.
    """
    run = s["run"]
    answers = {a.probe_id: a for a in run.answers}
    observations, dropped = {}, []
    for pr in [x for x in run.probes if x.kind == "named"]:
        if pr.id in answers:
            obs, warns = evaluation.extract_attributes(answers[pr.id], run.attributes)
            observations[pr.id] = obs
            dropped += [f"{probe_name(pr)}: {w}" for w in warns]
    kept, _, _ = drift.named_eligibility(run.probes, run.answers, run.evaluations)
    # Emergent attributes: one discovery call over every eligible brand answer at once, because
    # repetition across answers is the signal. Only a provider with a model offers it, so the
    # authored fixtures — whose unclaimed attributes are hand-written — never run it.
    notes = []
    propose = getattr(s["provider"], "discover", None)
    if propose and len(kept) >= evaluation.EMERGENT_MIN_ANSWERS:
        by_id = {p.id: p for p in run.probes}
        proposals = propose(run.attributes, [(by_id[pid], answers[pid]) for pid in kept])
        if proposals is None:
            notes.append("the discovery call failed, so nothing was discovered from the answers")
        else:
            discovered, found, notes = evaluation.discover_attributes(
                proposals, {pid: answers[pid] for pid in kept}, run.attributes, observations, run.profile)
            run.attributes = run.attributes + discovered
            for pid, obs in found.items():
                observations[pid] = observations.get(pid, []) + obs
            run.log.append(f"Discovery read {len(kept)} brand answers together: {len(proposals)} "
                           f"proposed, {len(discovered)} kept"
                           + (f" ({', '.join(a.label for a in discovered)})." if discovered else "."))
    run.observations = observations
    run.drift_notes = [f"Dropped unverifiable observation — {d}" for d in dropped]
    run.drift_notes += [f"Discovery — {n}" for n in notes]
    return {"run": run}


def plan_buyer(s: State):
    """Buyer questions on two fronts: the category the brand answers most associate with the
    company (where AI places it) and the site's own core category (where it aims to be)."""
    run, provider = s["run"], s["provider"]
    scores = drift.score_attributes(run.attributes, run.probes, run.answers, run.evaluations,
                                    run.observations or {})
    placed = ana.placed_attribute(scores, run.attributes, run.profile)
    topics, probes = provider.plan(run.profile, placed)
    fill_fit(run, topics)
    merge_plan(run, topics, probes)
    if "aiming" in s["asks"].decided and any(t.front == "both" for t in topics):
        s["asks"].decided.add("both")    # the aimed front, decided already, is now the shared set
    buyer = [p for p in probes if p.phase == "baseline"]
    fronts = {t.front for t in topics if t.kind == "buyer" and t.front}
    run.missing_fronts = dict(getattr(provider, "missing_fronts", {}))
    if fronts:
        sc = next((sc for sc in scores if placed and sc.attribute_id == placed.id), None)
        endorsed = round((sc.echo_rate or 0) * sc.n) if sc else 0
        run.log.append(
            (f"Where AI places {run.profile.name}: {placed.label} (endorsed in {endorsed} "
             f"of {sc.n if sc else 0} brand answers). " if placed else "")
            + (f"Where it aims to be: {run.profile.core_category}. " if run.profile.core_category else "")
            + f"{len(buyer)} unbranded questions planned across {len(fronts)} set(s)"
            + (", the rest from the claims." if any(not t.front for t in topics if t.kind == "buyer") else "."))
        if "both" in fronts:
            run.log.append(f"Where AI places {run.profile.name} ({placed.label}) is the category its site "
                           f"aims for ({run.profile.core_category}), so one set of unbranded questions was asked.")
    else:
        run.log.append(f"Question planner prepared {len(buyer)} unbranded questions from the claims.")
    run.demand_notes = list(getattr(provider, "demand_notes", []))
    run.log += run.demand_notes
    for note in [*getattr(provider, "notes", []), *run.missing_fronts.values()]:
        run.log.append(note)
        run.drift_notes.append(note)
    if skipped := getattr(provider, "skipped_questions", []):
        run.log.append(f"{len(skipped)} unbranded question(s) dropped for naming the brand or addressing "
                       f"the vendor instead of describing a need: {'; '.join(skipped)}.")
    return {"run": run}


def merge_plan(run: Run, topics: list, probes: list) -> None:
    """The whole buyer plan into the run. A front planned and asked already (plan_aiming) comes back
    in it with the same ids: it replaces its earlier self — relabelled, when AI places the company in
    that same category, as the one shared set — and a question its sampler set aside stays aside."""
    unasked = {p.id: i for i, p in enumerate(run.sampler.unasked)} if run.sampler else {}
    tpos = {t.id: i for i, t in enumerate(run.topics)}
    ppos = {p.id: i for i, p in enumerate(run.probes)}
    for t in topics:
        if t.id in tpos:
            run.topics[tpos[t.id]] = t
        else:
            run.topics.append(t)
    for p in probes:
        if p.id in ppos:
            run.probes[ppos[p.id]] = p
        elif p.id in unasked:
            run.sampler.unasked[unasked[p.id]] = p
        else:
            run.probes.append(p)
    kept = {p.topic_id for p in run.probes}
    run.topics = [t for t in run.topics if t.id in kept or t.kind != "buyer"]
    if run.sampler and any(t.front == "both" for t in topics):
        for f in run.sampler.fronts:
            f.front = "both" if f.front == "aiming" else f.front
    canonical(run)


def validate_and_freeze(s: State):
    run = s["run"]
    errors = ana.validate_probes(run.probes, run.topics, run.profile)
    errors += ana.validate_named_probes(run.probes, [a for a in run.attributes if not a.discovered])
    blind = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    if len(blind) > (cap := max_baseline()):
        errors.append(f"{len(blind)} baseline questions exceeds {cap}")
    named = [p for p in run.probes if p.kind == "named"]
    if len(named) > MAX_NAMED:
        errors.append(f"{len(named)} named questions exceeds {MAX_NAMED}")
    if errors:
        raise ValidationError("; ".join(errors))
    if getattr(s["provider"], "sampler", False):
        run.sampler = sampler.start(run)
        canonical(run)
        n1, n2 = run.sampler.looks
        run.log.append(f"Sampler: ±{run.sampler.margin} points at 95% on each front, so each front freezes "
                       f"{n2} questions and asks {n1} first; the rest only if the answers so far are not "
                       "clear enough.")
    run.baseline_hash = frozen_hash(run)
    run.status = "baseline_frozen"
    run.log.append("Baseline validated (unbranded questions leak no brand, branded questions leak no attribute) "
                   f"and frozen with fingerprint {run.baseline_hash[:12]}.")
    s["asks"].submit(askable(run, s["provider"]))
    return {"run": run}


def execute_or_replay(s: State):
    """Collect what the next step needs: the brand answers before perception reads them, else every
    question asked so far. Whatever else comes back meanwhile is kept, and a front whose look-1
    answers are all in decides its look 2 there and then (`sample_fronts`), without waiting for the
    others. Answers land in the run in `canonical` order, never in the order they came back."""
    run, provider, asks = s["run"], s["provider"], s["asks"]
    asks.submit(askable(run, provider))
    brand_stage = run.baseline_hash is None
    named = {p.id for p in run.probes if p.kind == "named"}
    phase = {p.id: ("follow-up" if p.phase == "followup" else "brand" if p.kind == "named" else "buyer")
             for p in run.probes}
    got: list = []

    def needed() -> list:
        return [f for (pid, _), f in asks.pending.items() if not brand_stage or pid in named]

    while True:
        for released in sample_fronts(run, provider, asks):
            asks.submit(released)
        if not (waiting := needed()):
            break
        wait(waiting, return_when=FIRST_COMPLETED)
        for key in [k for k, f in asks.pending.items() if f.done()]:
            a = asks.pending.pop(key).result()   # a Refused re-raises here and stops the run
            (run.answers if a.try_no == 1 else run.repeat_answers).append(a)
            got.append(a)
    canonical(run)
    firsts = [a for a in got if a.try_no == 1]
    repeats = len(got) - len(firsts)
    failed = sum(a.status != "ok" for a in got)
    # the log must not claim "replayed from fixtures" for answers a real provider produced
    verb = "Replayed" if all(a.provenance == "synthetic" for a in firsts) else "Collected"
    src = "fixtures" if verb == "Replayed" else f"{provider.name} ({getattr(provider, 'model', '?')})"
    counts = Counter(phase.get(a.probe_id, "buyer") for a in firsts)
    what = ", ".join(f"{n} {k} answers" for k, n in counts.items()) or "no answers"
    extra = f", plus {repeats} repeat ask(s) of sampled unbranded questions" if repeats else ""
    if shared := getattr(provider, "shared", 0):
        if run.sampler:
            run.sampler.shared = shared
        extra += f"; {shared} buyer answer(s) shared with another run in the same category today"
    run.log.append(f"{verb} {what}{extra} from {src} ({failed} failed).")
    return {"run": run}


def sample_fronts(run: Run, provider, asks: Asks) -> list[list]:
    """Sampler-lite's one decision (sampler.py), front by front: a front whose look-1 answers are all
    in and already meet the margin stops; any other asks the rest of its pool. What it does not need
    leaves the run's questions. -> the asks each decision released."""
    if not run.sampler:
        return []
    out = []
    answered = {a.probe_id for a in run.answers}
    fronts = sampler.front_of(run)
    held = set(run.sampler.held)
    for f in list(run.sampler.fronts):
        look1 = [pid for pid, fr in fronts.items() if fr == f.front and pid not in held]
        if f.front in asks.decided or not all(pid in answered for pid in look1):
            continue
        evaluate_new(run)
        waiting = sum(fronts.get(pid) == f.front for pid in held)
        released = sampler.decide(run, getattr(provider, "spent", 0.0), f.front,
                                  committed=sum(not fut.done() for fut in asks.pending.values()),
                                  per_call=getattr(provider, "per_call", lambda: 0.0)())
        sampler.drop_unasked(run, f.front)
        asks.decided.add(f.front)
        name = {"placed": "where AI places it", "aiming": "where it aims to be", "both": "the shared set"}.get(
            f.front, "the unbranded questions")
        run.log.append(f"Sampler, {name}: " + (
            f"within ±{run.sampler.margin} at look 1, {waiting} question(s) not needed." if f.stopped_early
            else f"{len(released)} more question(s) asked for look 2." if released
            else "nothing more to ask.") + (f" {f.note}" if f.note else ""))
        by = {p.id: p for p in run.probes}
        out.append([(by[pid], 1) for pid in released])
    run.sampler.decided = all(f.front in asks.decided for f in run.sampler.fronts)
    return out


def evaluate_new(run: Run) -> list:
    """Every answer not evaluated yet, and every repeat ask again: deterministic, from the labels they carry."""
    done = {e.probe_id for e in run.evaluations}
    answers = {a.probe_id: a for a in run.answers}
    new = [evaluation.evaluate(p, answers[p.id], run.profile) for p in run.probes
           if p.id not in done and p.id in answers]
    run.evaluations += new
    # Repeat asks are validated exactly like the first: deterministic, from the labels they carry.
    by_id = {p.id: p for p in run.probes}
    run.repeat_evaluations = [evaluation.evaluate(by_id[a.probe_id], a, run.profile)
                              .model_copy(update={"try_no": a.try_no}) for a in run.repeat_answers]
    evaluation.merge_divisions([*run.evaluations, *run.repeat_evaluations])
    canonical(run)
    return new


def evaluate(s: State):
    run = s["run"]
    answers = {a.probe_id: a for a in run.answers}
    evaluate_new(run)
    ev = {e.probe_id: e for e in run.evaluations}
    run.topic_evaluations = []
    for phase in ("baseline", "followup"):
        for t in [x for x in run.topics if x.kind == "buyer"]:
            ps = [p for p in run.probes if p.topic_id == t.id and p.phase == phase
                  and p.kind == "blind" and p.id in ev]
            if ps:
                run.topic_evaluations.append(score_topic(t, phase, [answers[p.id] for p in ps], [ev[p.id] for p in ps]))
    # a front's answers may have been evaluated already, to decide its look 2: the count is the run's so far
    run.log.append(f"Evaluated {len(run.evaluations)} answers so far "
                   f"({sum(not e.valid for e in run.evaluations)} need review / failed).")
    return {"run": run}


def choose_followup(s: State):
    run = s["run"]
    if s["rounds"] >= MAX_ADAPTIVE_ROUNDS:
        return {"run": run}
    d = ana.choose_followup(run.topics, run.topic_evaluations, run.evaluations, run.probes,
                            s["provider"].followup_bank(), run.profile)
    d.new_probes = d.new_probes[:MAX_FOLLOWUP]
    if run.mode == "live_api":
        # Only a live provider can answer a question nobody authored, and this one's wording is not
        # known until the baseline answers name somebody. A replay provider would return an error
        # answer for it, so fixture runs never ask it.
        if names := ana.discovered_competitors(run.topic_evaluations):
            p = ana.comparison_probe(run.profile, names, d.evidence_probe_ids)
            if leaks := ana.attribute_leaks(p.text, run.attributes):
                run.log.append(f"Comparison question dropped: a competitor's name collides with the "
                               f"attribute(s) being measured ({', '.join(leaks)}).")
            else:
                d.new_probes.append(p)
                run.log.append(f"Competitors discovered, not asked for: {', '.join(names)}.")
    run.decisions.append(d)
    run.probes += d.new_probes
    run.log.append(f"Follow-up decision: {d.rationale}")
    return {"run": run, "rounds": s["rounds"] + 1}


def route_after_followup(s: State) -> str:
    run = s["run"]
    pending = [p for p in run.probes if p.id not in {a.probe_id for a in run.answers}]
    return "execute_or_replay" if pending and s["rounds"] <= MAX_ADAPTIVE_ROUNDS else "measure_drift"


def measure_drift(s: State):
    """Perception drift and buyer visibility, over the observations `perceive` validated."""
    run = s["run"]
    if run.mode == "live_api" and not ana.discovered_competitors(run.topic_evaluations):
        # "Nobody was named" and "nobody was asked" are different findings: with no claim that has
        # buyer questions there are none to ask, so an empty competitor set is silence, not absence.
        run.drift_notes.append(
            "No competitor was named in any baseline answer, so no comparison question was asked."
            if any(p.kind == "blind" for p in run.probes) else
            "No unbranded question was asked — no claim has an unbranded question — so the buyer axis was "
            "not measured and no competitor could be discovered.")
    score_drift(run)
    run.log.append(f"Drift measured over {run.drift.n_named} brand answers: claim echo "
                   f"{run.drift.claim_echo if run.drift.claim_echo is not None else 'n/a'}, alignment "
                   f"{run.drift.alignment if run.drift.alignment is not None else 'n/a'} "
                   f"({len(run.drift.lost_claims)} lost, {len(run.drift.imposed)} imposed, "
                   f"{sum(n.startswith('Dropped') for n in run.drift_notes)} observation(s) dropped).")
    return {"run": run}


def score_drift(run: Run) -> None:
    """Everything in the drift report that is arithmetic over saved state: no provider, no model.

    measure_drift calls it once the observations exist; `rescore` calls it again after the customer
    sets intent weights on a finished run, which is why nothing here may ask anything.
    """
    if run.sampler:
        sampler.finish(run)
    answers = {a.probe_id: a for a in run.answers}
    blind = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    ev = {e.probe_id: e for e in run.evaluations}
    buyer_ids = {p.id for p in blind}
    counted = [e for e in [ev[p.id] for p in blind if p.id in ev] + run.repeat_evaluations
               if e.probe_id in buyer_ids and e.valid and e.strength is not None]
    tries = max([1] + [e.try_no for e in run.repeat_evaluations])
    # Which questions were re-asked is read off the answers that came back, not recomputed: the
    # wobble must describe the questions actually sampled, even on a run saved under other settings.
    repeated = {e.probe_id for e in run.repeat_evaluations} & buyer_ids
    per_question = lambda ids: [[e.strength for e in counted if e.probe_id == i] for i in ids]
    # Visibility weighs every question once (scoring.visibility_by_question); the range beside it is
    # the WOBBLE — the same repeat-sampled questions scored try by try — not a second estimate of
    # the whole run, which is what the confidence interval below is for.
    visibility = visibility_by_question(per_question([p.id for p in blind]))
    _, spread = visibility_over_tries(
        [[e.strength for e in counted if e.probe_id in repeated and e.try_no == t]
         for t in range(1, tries + 1)])
    # provenance is read off the answers that actually fed the perception layer — never hardcoded,
    # or a live run would publish its drift report under a synthetic label (and vice versa)
    named_provenance = {answers[p.id].provenance for p in run.probes
                        if p.kind == "named" and p.id in answers}
    if len(named_provenance) > 1:
        raise ValidationError(f"named answers mix provenance types: {sorted(named_provenance)}")
    provenance = named_provenance.pop() if named_provenance else "synthetic"
    kept, excluded, asked = drift.named_eligibility(run.probes, run.answers, run.evaluations)
    run.attribute_scores = drift.score_attributes(run.attributes, run.probes, run.answers,
                                                  run.evaluations, run.observations)
    lens = "intent" if any(a.intended for a in run.attributes) else "claim"
    run.drift = drift.build_report(run.attribute_scores, provenance, n_blind=len(counted),
                                   visibility=visibility,
                                   asked=asked, excluded_reasons=excluded,
                                   echo=drift.claim_echo(run.attributes, kept, run.observations),
                                   lens=lens)
    run.drift.tries, run.drift.visibility_range = tries, spread
    run.drift.repeat_sample = len(repeated)

    def no_interval(qs: list[list[int]]) -> str:
        qs = [q for q in qs if q]
        if qs and max(map(len, qs)) < 2:
            return ("No question was asked twice, so there is no interval: a sample of repeat asks "
                    "is what shows how much the same question varies.")
        return (f"Too few unbranded questions for an interval: {len(qs)} scored, at least "
                f"{MIN_INTERVAL_ANSWERS} needed.")
    if run.drift.visibility is not None:
        qs = per_question([p.id for p in blind])
        if draws := visibility_draws(qs):
            run.drift.visibility_interval = interval(draws)
        else:
            run.drift.na_reasons["visibility_interval"] = no_interval(qs)
    # Claim echo and alignment: resample the brand answers the numbers were computed over.
    endorsed = {pid: {o.attribute_id for o in (run.observations or {}).get(pid, []) if o.polarity == "positive"}
                for pid in kept}
    for field, weights in (
            ("claim_echo", {a.id: a.claim_pages for a in run.attributes if not a.discovered and a.claim_pages > 0}),
            ("alignment", {s.attribute_id: s.intended_weight for s in run.attribute_scores
                           if s.intended_weight and s.echo_rate is not None})):
        if getattr(run.drift, field) is None:
            continue
        if draws := echo_draws(kept, weights, endorsed):
            setattr(run.drift, f"{field}_interval", interval(draws))
        else:
            run.drift.na_reasons[f"{field}_interval"] = (
                f"Too few answers for an interval: {len(kept)} brand answer(s), at least "
                f"{MIN_INTERVAL_ANSWERS} needed.")
    if run.drift.visibility is None and not blind:
        run.drift.na_reasons["visibility"] = ("No unbranded question was asked: no claim had an "
                                              "unbranded question, so visibility is not measured.")
    # One set per front, each with its own tries, range and control question. Replay has one
    # unlabelled set (front None), so its numbers are the run's own.
    topic = {t.id: t for t in run.topics}
    fronts = list(dict.fromkeys(topic[p.topic_id].front for p in blind if p.topic_id in topic))
    draws = {}
    for front in fronts:
        ids = {p.id for p in blind if topic[p.topic_id].front == front}
        mine = [e for e in counted if e.probe_id in ids]
        vis = visibility_by_question(per_question(sorted(ids)))
        _, rng = visibility_over_tries(
            [[e.strength for e in mine if e.probe_id in repeated and e.try_no == t]
             for t in range(1, tries + 1)])
        control = next((p for p in run.probes if p.phase == "control"
                        and topic.get(p.topic_id) and topic[p.topic_id].front == front), None)
        # front None beside labelled fronts is the claims' own questions: no one category
        category = next(topic[p.topic_id].label for p in blind if p.id in ids) if front else \
            None if len(fronts) > 1 else run.profile.core_category
        vs = VisibilitySet(front=front, category=category, visibility=vis, tries=tries,
                           visibility_range=rng, n_blind=len(mine), questions=len(ids),
                           repeat_sample=len(ids & repeated),
                           control_probe_id=control.id if control else None)
        qs = per_question(sorted(ids))
        draws[front] = visibility_draws(qs, key=str(front))
        if vis is not None:
            if draws[front]:
                vs.interval = interval(draws[front])
            else:
                vs.interval_note = no_interval(qs)
        if control and vis is not None:
            vs.low_confidence = low_confidence(run.profile.name, category or "",
                                               ev.get(control.id), answers.get(control.id))
        run.drift.sets.append(vs)
    by_front = {vs.front: vs for vs in run.drift.sets}
    if len(controlled := [vs for vs in run.drift.sets if vs.control_probe_id]) == 1:
        run.drift.low_confidence = controlled[0].low_confidence
    placed, aiming = by_front.get("placed") or by_front.get("both"), by_front.get("aiming") or by_front.get("both")
    run.drift.missing_fronts = dict(run.missing_fronts)
    run.drift.placed_category = placed.category if placed else None
    run.drift.aiming_category = aiming.category if aiming else None
    if "placed" in by_front and "aiming" in by_front and None not in (placed.visibility, aiming.visibility):
        run.drift.visibility_gap = round(placed.visibility - aiming.visibility, 1)
        verdict = draws.get("placed") and draws.get("aiming") and gap_verdict(draws["placed"], draws["aiming"])
        if verdict:
            run.drift.gap_interval, run.drift.gap_real = verdict
        else:
            why = (placed.interval_note or aiming.interval_note
                   or "the answers on one side never varied, so its interval has no width.")
            run.drift.na_reasons["visibility_gap_interval"] = f"Too few questions to call the gap: {why}"
    run.drift.limitations += run.drift_notes


def rescore(run: Run, weights: dict[str, float]) -> Run:
    """Lens 2 applied after the run: set intent weights, re-score the saved answers. No model calls.

    Only the weights move. The questions were planned when the run was measured and are not
    re-asked, so zones and alignment change and the buyer axis does not.
    """
    if run.status != "complete":
        raise ValidationError("only a finished run can be re-scored")
    if run.observations is None:
        raise ValidationError("this run was saved before re-scoring existed; measure again to set weights")
    by_id = {a.id: a for a in run.attributes}
    for aid, w in weights.items():
        by_id[aid].intended_weight = round(w, 2) or None
    evaluation.merge_divisions([*run.evaluations, *run.repeat_evaluations])  # a run saved before it existed
    score_drift(run)
    if run.positioning is not None and run.positioning.provenance == "live_api":
        import embeddings
        import positioning
        try:
            run.positioning = positioning.build(run, embed=embeddings.cached)
        except Exception as e:
            note = ("Not redrawn for the new weights: a text it needs was never embedded, and a re-score asks "
                    "no model." if isinstance(e, KeyError) else "Not redrawn for the new weights.")
            if note not in run.positioning.notes:
                run.positioning.notes.append(note)
            run.log.append(f"Positioning map not redrawn on re-score ({type(e).__name__}); the previous map is kept.")
    run.drift.limitations.append("Re-scored after the run with intent weights: the questions were "
                                 "planned when it was measured and were not re-asked.")
    run.log.append("Re-scored with intent weights on the saved answers; no model was asked. "
                   f"Lens: {run.drift.lens}, alignment "
                   f"{run.drift.alignment if run.drift.alignment is not None else 'n/a'}.")
    return run


def build_gap_report(s: State):
    run = s["run"]
    if frozen_hash(run) != run.baseline_hash:
        raise ValidationError("baseline changed after freeze")
    run.findings = evaluation.build_findings(run.topics, run.topic_evaluations, run.evaluations, run.probes)
    # After every score exists, over saved answers and pages only: it reads the zones, never moves them.
    win_back.plan(run, s["provider"])
    if run.win_back or run.win_back_notes:
        run.log.append(f"Action plan: {len(run.win_back)} fix(es) kept, "
                       f"{len(run.win_back_notes)} note(s) on what was dropped.")
    simulate_retrieval(run, s["provider"])
    map_positioning(run, getattr(s["provider"], "positioning", None))
    run.status = "complete"
    run.log.append(f"Gap report built: {len(run.findings)} findings.")
    return {"run": run}


def simulate_retrieval(run: Run, provider) -> None:
    """The retrieval simulation and the fixes re-scored (retrieval.py): after every score, moving none.
    A provider without it (a test transport) asks nothing; a failure is stated, never fatal."""
    simulate = getattr(provider, "retrieval", None)
    if simulate is None:
        return
    try:
        run.retrieval = simulate(run)
    except Exception as e:
        run.log.append(f"Retrieval simulation failed ({type(e).__name__}); no passage was scored.")
        return
    if run.retrieval is None:
        return
    rows = [r for r in run.retrieval.rows if r.yours and r.rival]
    run.log.append(("Retrieval sample (authored, not computed)" if run.retrieval.provenance == "synthetic"
                    else "Retrieval simulation") + f": {run.retrieval.passages} passages from {run.retrieval.pages} "
                   f"pages; your best passage trails the cited page on "
                   f"{sum(r.rival.score > r.yours.score for r in rows)} of {len(rows)} unbranded questions.")


def map_positioning(run: Run, build) -> None:
    """The positioning map (positioning.py): after every score, moving none. A provider without it
    asks nothing; a failure is stated, never fatal."""
    if build is None:
        return
    try:
        run.positioning = build(run)
    except Exception as e:
        run.log.append(f"Positioning map failed ({type(e).__name__}); nothing was placed.")
        return
    if run.positioning is not None:
        m = run.positioning
        run.log.append(("Positioning map sample (authored, not computed)" if m.provenance == "synthetic"
                        else "Positioning map") + (f": {len(m.points)} points placed." if m.points
                                                   else f": not drawn. {m.reason}"))


def route_after_evaluate(s: State) -> str:
    """Brand answers are in and nothing is frozen yet: read them, then plan the unbranded questions."""
    return "perceive" if s["run"].baseline_hash is None else "choose_followup"


def frozen_hash(run: Run) -> str:
    """What validate_and_freeze fingerprints: the probes, or with the sampler the whole frozen pool
    (asked and never needed), so dropping unneeded questions does not read as a changed baseline."""
    return ana.baseline_hash(sampler.frozen(run) if run.sampler else run.probes)


def build_graph():
    g = StateGraph(State)
    for name, fn in [("plan_brand", plan_brand), ("plan_aiming", plan_aiming), ("perceive", perceive),
                     ("plan_buyer", plan_buyer), ("validate_and_freeze", validate_and_freeze),
                     ("execute_or_replay", execute_or_replay), ("evaluate", evaluate),
                     ("choose_followup", choose_followup), ("measure_drift", measure_drift),
                     ("build_gap_report", build_gap_report)]:
        g.add_node(name, fn)
    # plan_brand and plan_aiming submit their questions as they freeze them, so both are being
    # asked while the first execute_or_replay waits for the brand answers alone (class Asks)
    g.add_edge(START, "plan_brand")
    g.add_edge("plan_brand", "plan_aiming")
    g.add_edge("plan_aiming", "execute_or_replay")
    g.add_edge("execute_or_replay", "evaluate")
    g.add_conditional_edges("evaluate", route_after_evaluate, ["perceive", "choose_followup"])
    g.add_edge("perceive", "plan_buyer")
    g.add_edge("plan_buyer", "validate_and_freeze")
    g.add_edge("validate_and_freeze", "execute_or_replay")
    g.add_conditional_edges("choose_followup", route_after_followup, ["execute_or_replay", "measure_drift"])
    g.add_edge("measure_drift", "build_gap_report")
    g.add_edge("build_gap_report", END)
    return g.compile()


GRAPH = build_graph()


def new_run(profile, provider, mode="demo_replay") -> Run:
    return Run(id=uuid.uuid4().hex[:10], mode=mode, scenario=getattr(provider, "scenario", None),
               profile=profile.model_copy(deep=True))


def stream(run: Run, provider, dispatcher: Optional[dispatch.Dispatcher] = None):
    """Yields (node_name, run) after each graph transition. Live asks go to `dispatcher`, the
    process-wide one by default, keyed by this run and the pass paying for it; a run that fails or
    is closed early drops whatever it still has queued there, and nothing of any other run's."""
    asks = Asks(provider, dispatcher or dispatch.shared(), (run.id, access.SPENDER.get()))
    state = {"run": run, "provider": provider, "rounds": 0, "asks": asks}
    try:
        for update in GRAPH.stream(state, {"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"):
            for node, out in update.items():
                if out and "run" in out:
                    run = out["run"]
                yield node, run
    finally:
        asks.cancel()


def execute(run: Run, provider, dispatcher: Optional[dispatch.Dispatcher] = None) -> Run:
    for _, run in stream(run, provider, dispatcher):
        pass
    return run
