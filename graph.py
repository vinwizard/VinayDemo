"""Orchestrator: ordinary code owning LangGraph state, routing, budgets and validation."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

import drift
from agents import ana, evaluation
from labels import probe_name
from schemas import Run
from scoring import score_topic, visibility_score

MAX_BASELINE = 12
MAX_NAMED = 8
MAX_FOLLOWUP = 4
MAX_ADAPTIVE_ROUNDS = 1
RECURSION_LIMIT = 12

STAGES = {  # node -> (UI stage, logical agent). Both strings are shown to the reader verbatim.
    "plan_baseline": ("Topic planning", "Agent 2 · Question planner"),
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


def plan_baseline(s: State):
    run = s["run"]
    topics, probes = s["provider"].plan(run.profile)
    points = {pp.id: pp for pp in run.profile.positioning_points}
    for t in topics:  # fit evidence always resolves against the approved profile
        t.fit_evidence_ids = [e for pid in t.positioning_point_ids if pid in points for e in points[pid].evidence_ids]
    run.attributes = s["provider"].attributes()
    named = s["provider"].named_probes()
    if named and not any(t.kind == "perception" for t in topics):
        raise ValidationError("named probes planned without a perception topic to hold them")
    run.topics, run.probes = topics, probes + named
    run.log.append(f"Question planner prepared {len(topics)} topics, {len(probes)} buyer questions, "
                   f"{len(named)} brand questions and {len(run.attributes)} attributes.")
    if skipped := getattr(s["provider"], "skipped_questions", []):
        run.log.append(f"{len(skipped)} saved buyer question(s) dropped for addressing the vendor instead of "
                       f"describing a need: {'; '.join(skipped)}.")
    return {"run": run}


def validate_and_freeze(s: State):
    run = s["run"]
    errors = ana.validate_probes(run.probes, run.topics, run.profile)
    errors += ana.validate_named_probes(run.probes, run.attributes)
    blind = [p for p in run.probes if p.kind == "blind"]
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
    run = s["run"]
    done = {a.probe_id for a in run.answers}
    todo = [p for p in run.probes if p.id not in done]
    # Live answers are two slow calls each (measured + evaluator). Serially that is ~8 minutes for a
    # 12-probe run; ThreadPoolExecutor.map preserves order so results stay deterministic.
    workers = min(getattr(s["provider"], "concurrency", 1), len(todo)) if todo else 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            run.answers += list(pool.map(s["provider"].answer, todo))
    else:
        run.answers += [s["provider"].answer(p) for p in todo]
    phase = ("follow-up" if todo[0].phase == "followup" else todo[0].phase) if todo else "?"
    new = [a for a in run.answers if a.probe_id in {p.id for p in todo}]
    failed = sum(a.status != "ok" for a in new)
    # the log must not claim "replayed from fixtures" for answers a real provider produced
    verb = "Replayed" if all(a.provenance == "synthetic" for a in new) else "Collected"
    src = "fixtures" if verb == "Replayed" else f"{s['provider'].name} ({getattr(s['provider'], 'model', '?')})"
    run.log.append(f"{verb} {len(todo)} {phase} answers from {src} ({failed} failed).")
    return {"run": run}


def evaluate(s: State):
    run = s["run"]
    done = {e.probe_id for e in run.evaluations}
    answers = {a.probe_id: a for a in run.answers}
    new = [evaluation.evaluate(p, answers[p.id], run.profile) for p in run.probes
           if p.id not in done and p.id in answers]
    run.evaluations += new
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
    """Perception layer: extract attribute observations, then classify against intent and claims.

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
    blind = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    ev = {e.probe_id: e for e in run.evaluations}
    strengths = [ev[p.id].strength for p in blind
                 if p.id in ev and ev[p.id].valid and ev[p.id].strength is not None]
    # provenance is read off the answers that actually fed the perception layer — never hardcoded,
    # or a live run would publish its drift report under a synthetic label (and vice versa)
    named_provenance = {answers[p.id].provenance for p in run.probes
                        if p.kind == "named" and p.id in answers}
    if len(named_provenance) > 1:
        raise ValidationError(f"named answers mix provenance types: {sorted(named_provenance)}")
    provenance = named_provenance.pop() if named_provenance else "synthetic"
    kept, excluded, asked = drift.named_eligibility(run.probes, run.answers, run.evaluations)
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
    run.attribute_scores = drift.score_attributes(run.attributes, run.probes, run.answers,
                                                  run.evaluations, observations)
    run.drift = drift.build_report(run.attribute_scores, provenance, n_blind=len(strengths),
                                   visibility=visibility_score(strengths),
                                   asked=asked, excluded_reasons=excluded)
    if dropped:
        run.drift.limitations += [f"Dropped unverifiable observation — {d}" for d in dropped]
    run.drift.limitations += [f"Discovery — {n}" for n in notes]
    if run.mode == "live_api" and not ana.discovered_competitors(run.topic_evaluations):
        # "Nobody was named" and "nobody was asked" are different findings: with no weighted claim
        # there are no buyer questions, so an empty competitor set is silence, not an absence.
        run.drift.limitations.append(
            "No competitor was named in any baseline answer, so no comparison question was asked."
            if blind else
            "No buyer question was asked — no claim is weighted as intended — so the buyer axis was "
            "not measured and no competitor could be discovered.")
    run.log.append(f"Drift measured over {run.drift.n_named} brand answers: alignment "
                   f"{run.drift.alignment if run.drift.alignment is not None else 'n/a'} "
                   f"({len(run.drift.lost_claims)} lost, {len(run.drift.imposed)} imposed, "
                   f"{len(dropped)} observation(s) dropped).")
    return {"run": run}


def build_gap_report(s: State):
    run = s["run"]
    if ana.baseline_hash(run.probes) != run.baseline_hash:
        raise ValidationError("baseline changed after freeze")
    run.findings = evaluation.build_findings(run.topics, run.topic_evaluations, run.evaluations, run.probes)
    run.status = "complete"
    run.log.append(f"Gap report built: {len(run.findings)} findings.")
    return {"run": run}


def build_graph():
    g = StateGraph(State)
    for name, fn in [("plan_baseline", plan_baseline), ("validate_and_freeze", validate_and_freeze),
                     ("execute_or_replay", execute_or_replay), ("evaluate", evaluate),
                     ("choose_followup", choose_followup), ("measure_drift", measure_drift),
                     ("build_gap_report", build_gap_report)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan_baseline")
    g.add_edge("plan_baseline", "validate_and_freeze")
    g.add_edge("validate_and_freeze", "execute_or_replay")
    g.add_edge("execute_or_replay", "evaluate")
    g.add_edge("evaluate", "choose_followup")
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
