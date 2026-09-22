"""Orchestrator: ordinary code owning LangGraph state, routing, budgets and validation."""
import contextvars
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

import drift
from agents import ana, evaluation, win_back
from labels import probe_name
from schemas import Run, VisibilitySet
from scoring import (MIN_INTERVAL_ANSWERS, echo_draws, gap_verdict, interval, low_confidence, score_topic, visibility_draws,
                     visibility_over_tries)

MAX_BASELINE = 12
MAX_NAMED = 8
MAX_FOLLOWUP = 4
MAX_ADAPTIVE_ROUNDS = 1
RECURSION_LIMIT = 20

STAGES = {  # node -> (UI stage, logical agent). Both strings are shown to the reader verbatim.
    "plan_brand": ("Topic planning", "Agent 2 · Question planner"),
    "perceive": ("Perception drift", "Agent 3 · Answer evaluation"),
    "plan_buyer": ("Topic planning", "Agent 2 · Question planner"),
    "validate_and_freeze": ("Topic planning", "Orchestrator"),
    "execute_or_replay": ("Baseline / Follow-up", "Orchestrator"),
    "evaluate": ("Gap evaluation", "Agent 3 · Answer evaluation"),
    "choose_followup": ("Follow-up", "Agent 2 · Question planner"),
    "measure_drift": ("Perception drift", "Agent 3 · Answer evaluation"),
    "build_gap_report": ("Report", "Agent 3 · Answer evaluation"),
}


class State(TypedDict):
    run: Run
    provider: Any
    rounds: int


class ValidationError(Exception):
    pass


def plan_brand(s: State):
    """Brand questions first: the buyer questions are planned from what their answers say."""
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
    run.log.append(f"Question planner prepared {len(named)} brand questions and "
                   f"{len(run.attributes)} attributes; buyer questions are planned from their answers.")
    return {"run": run}


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
    points = {pp.id: pp for pp in run.profile.positioning_points}
    for t in topics:  # fit evidence always resolves against the approved profile
        t.fit_evidence_ids = t.fit_evidence_ids or [e for pid in t.positioning_point_ids if pid in points
                                                    for e in points[pid].evidence_ids]
    have = {t.id for t in run.topics}
    # buyer questions first, as a run has always listed them
    run.topics = [t for t in topics if t.id not in have] + run.topics
    run.probes = probes + run.probes
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
            + f"{len(buyer)} buyer questions planned across {len(fronts)} set(s)"
            + (", the rest from the claims." if any(not t.front for t in topics if t.kind == "buyer") else "."))
        if "both" in fronts:
            run.log.append(f"Where AI places {run.profile.name} ({placed.label}) is the category its site "
                           f"aims for ({run.profile.core_category}), so one set of buyer questions was asked.")
    else:
        run.log.append(f"Question planner prepared {len(buyer)} buyer questions from the claims.")
    run.demand_notes = list(getattr(provider, "demand_notes", []))
    run.log += run.demand_notes
    for note in [*getattr(provider, "notes", []), *run.missing_fronts.values()]:
        run.log.append(note)
        run.drift_notes.append(note)
    if skipped := getattr(provider, "skipped_questions", []):
        run.log.append(f"{len(skipped)} buyer question(s) dropped for naming the brand or addressing "
                       f"the vendor instead of describing a need: {'; '.join(skipped)}.")
    return {"run": run}


def validate_and_freeze(s: State):
    run = s["run"]
    errors = ana.validate_probes(run.probes, run.topics, run.profile)
    errors += ana.validate_named_probes(run.probes, [a for a in run.attributes if not a.discovered])
    blind = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    if len(blind) > MAX_BASELINE:
        errors.append(f"{len(blind)} baseline questions exceeds {MAX_BASELINE}")
    named = [p for p in run.probes if p.kind == "named"]
    if len(named) > MAX_NAMED:
        errors.append(f"{len(named)} named questions exceeds {MAX_NAMED}")
    if errors:
        raise ValidationError("; ".join(errors))
    run.baseline_hash = ana.baseline_hash(run.probes)
    run.status = "baseline_frozen"
    run.log.append("Baseline validated (buyer questions leak no brand, brand questions leak no attribute) "
                   f"and frozen with fingerprint {run.baseline_hash[:12]}.")
    return {"run": run}


def execute_or_replay(s: State):
    run, provider = s["run"], s["provider"]
    done = {a.probe_id for a in run.answers}
    todo = [p for p in run.probes if p.id not in done]
    # Every baseline buyer question is asked `tries` times, each in a fresh context. Replay has one
    # authored answer per question, so a fixture provider has no `tries` and is asked once.
    tries = getattr(provider, "tries", 1)
    have = {(a.probe_id, a.try_no) for a in run.repeat_answers}
    again = [(p, t) for p in run.probes if p.kind == "blind" and p.phase == "baseline"
             for t in range(2, tries + 1) if (p.id, t) not in have]
    jobs = [(p, 1) for p in todo] + again
    ask = lambda p, t: provider.answer(p) if t == 1 else provider.answer(p, try_no=t)
    # Live answers are two slow calls each (measured + evaluator). Serially that is ~8 minutes for a
    # 12-probe run; results are collected in submission order so they stay deterministic.
    workers = min(getattr(provider, "concurrency", 1), len(jobs)) if jobs else 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # each answer runs in a copy of this thread's context, so the pass paying for it
            # (access.SPENDER) reaches the pool threads
            got = [f.result() for f in [pool.submit(contextvars.copy_context().run, ask, p, t)
                                        for p, t in jobs]]
    else:
        got = [ask(p, t) for p, t in jobs]
    new = got[:len(todo)]
    run.answers += new
    run.repeat_answers += got[len(todo):]
    phase = ("follow-up" if todo[0].phase == "followup" else "brand" if all(p.kind == "named" for p in todo)
             else todo[0].phase) if todo else "?"
    failed = sum(a.status != "ok" for a in got)
    # the log must not claim "replayed from fixtures" for answers a real provider produced
    verb = "Replayed" if all(a.provenance == "synthetic" for a in new) else "Collected"
    src = "fixtures" if verb == "Replayed" else f"{provider.name} ({getattr(provider, 'model', '?')})"
    extra = f", plus {len(again)} repeat asks of the buyer questions ({tries} tries each)" if again else ""
    run.log.append(f"{verb} {len(todo)} {phase} answers{extra} from {src} ({failed} failed).")
    return {"run": run}


def evaluate(s: State):
    run = s["run"]
    done = {e.probe_id for e in run.evaluations}
    answers = {a.probe_id: a for a in run.answers}
    new = [evaluation.evaluate(p, answers[p.id], run.profile) for p in run.probes
           if p.id not in done and p.id in answers]
    run.evaluations += new
    # Repeat asks are validated exactly like the first: deterministic, from the labels they carry.
    by_id = {p.id: p for p in run.probes}
    run.repeat_evaluations = [evaluation.evaluate(by_id[a.probe_id], a, run.profile)
                              .model_copy(update={"try_no": a.try_no}) for a in run.repeat_answers]
    ev = {e.probe_id: e for e in run.evaluations}
    run.topic_evaluations = []
    for phase in ("baseline", "followup"):
        for t in [x for x in run.topics if x.kind == "buyer"]:
            ps = [p for p in run.probes if p.topic_id == t.id and p.phase == phase
                  and p.kind == "blind" and p.id in ev]
            if ps:
                run.topic_evaluations.append(score_topic(t, phase, [answers[p.id] for p in ps], [ev[p.id] for p in ps]))
    run.log.append(f"Evaluated {len(new)} answers ({sum(not e.valid for e in new)} need review / failed).")
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
            "No buyer question was asked — no claim has a buyer question — so the buyer axis was "
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
    answers = {a.probe_id: a for a in run.answers}
    blind = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    ev = {e.probe_id: e for e in run.evaluations}
    buyer_ids = {p.id for p in blind}
    counted = [e for e in [ev[p.id] for p in blind if p.id in ev] + run.repeat_evaluations
               if e.probe_id in buyer_ids and e.valid and e.strength is not None]
    tries = max([1] + [e.try_no for e in run.repeat_evaluations])
    visibility, spread = visibility_over_tries(
        [[e.strength for e in counted if e.try_no == t] for t in range(1, tries + 1)])
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
    per_question = lambda ids: [[e.strength for e in counted if e.probe_id == i] for i in ids]

    def no_interval(qs: list[list[int]]) -> str:
        qs = [q for q in qs if q]
        if qs and max(map(len, qs)) < 2:
            return "1 try per question, so there is no interval: repeat asks show how much answers vary."
        return (f"Too few buyer questions for an interval: {len(qs)} scored, at least "
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
        run.drift.na_reasons["visibility"] = ("No buyer question was asked: no claim had a buyer "
                                              "question, so visibility is not measured.")
    # One set per front, each with its own tries, range and control question. Replay has one
    # unlabelled set (front None), so its numbers are the run's own.
    topic = {t.id: t for t in run.topics}
    fronts = list(dict.fromkeys(topic[p.topic_id].front for p in blind if p.topic_id in topic))
    draws = {}
    for front in fronts:
        ids = {p.id for p in blind if topic[p.topic_id].front == front}
        mine = [e for e in counted if e.probe_id in ids]
        vis, rng = visibility_over_tries(
            [[e.strength for e in mine if e.try_no == t] for t in range(1, tries + 1)])
        control = next((p for p in run.probes if p.phase == "control"
                        and topic.get(p.topic_id) and topic[p.topic_id].front == front), None)
        # front None beside labelled fronts is the claims' own questions: no one category
        category = next(topic[p.topic_id].label for p in blind if p.id in ids) if front else \
            None if len(fronts) > 1 else run.profile.core_category
        vs = VisibilitySet(front=front, category=category, visibility=vis, tries=tries,
                           visibility_range=rng, n_blind=len(mine), questions=len(ids),
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
    if ana.baseline_hash(run.probes) != run.baseline_hash:
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
                   f"{sum(r.rival.score > r.yours.score for r in rows)} of {len(rows)} buyer questions.")


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
    """Brand answers are in and nothing is frozen yet: read them, then plan the buyer questions."""
    return "perceive" if s["run"].baseline_hash is None else "choose_followup"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("plan_brand", plan_brand), ("perceive", perceive), ("plan_buyer", plan_buyer),
                     ("validate_and_freeze", validate_and_freeze),
                     ("execute_or_replay", execute_or_replay), ("evaluate", evaluate),
                     ("choose_followup", choose_followup), ("measure_drift", measure_drift),
                     ("build_gap_report", build_gap_report)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan_brand")
    g.add_edge("plan_brand", "execute_or_replay")
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


def stream(run: Run, provider):
    """Yields (node_name, run) after each graph transition."""
    state = {"run": run, "provider": provider, "rounds": 0}
    for update in GRAPH.stream(state, {"recursion_limit": RECURSION_LIMIT}, stream_mode="updates"):
        for node, out in update.items():
            if out and "run" in out:
                run = out["run"]
            yield node, run


def execute(run: Run, provider) -> Run:
    for _, run in stream(run, provider):
        pass
    return run
