"""Orchestrator: ordinary code owning LangGraph state, routing, budgets and validation."""
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import ana, evaluation
from schemas import Run
from scoring import score_topic

MAX_BASELINE = 12
MAX_FOLLOWUP = 4
MAX_ADAPTIVE_ROUNDS = 1
RECURSION_LIMIT = 12

STAGES = {  # node -> (UI stage, logical agent)
    "plan_baseline": ("Topic planning", "Agent 2 · AnA"),
    "validate_and_freeze": ("Topic planning", "Orchestrator"),
    "execute_or_replay": ("Baseline / Follow-up", "Orchestrator"),
    "evaluate": ("Gap evaluation", "Agent 3 · Evaluation"),
    "choose_followup": ("Follow-up", "Agent 2 · AnA"),
    "build_gap_report": ("Report", "Agent 3 · Evaluation"),
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
    run.topics, run.probes = topics, probes
    run.log.append(f"AnA planned {len(topics)} topics and {len(probes)} baseline questions (fixture plan).")
    return {"run": run}


def validate_and_freeze(s: State):
    run = s["run"]
    errors = ana.validate_probes(run.probes, run.topics, run.profile)
    if len(run.probes) > MAX_BASELINE:
        errors.append(f"{len(run.probes)} baseline questions exceeds {MAX_BASELINE}")
    if errors:
        raise ValidationError("; ".join(errors))
    run.baseline_hash = ana.baseline_hash(run.probes)
    run.status = "baseline_frozen"
    run.log.append(f"Baseline validated (no brand leakage) and frozen: {run.baseline_hash[:12]}.")
    return {"run": run}


def execute_or_replay(s: State):
    run = s["run"]
    done = {a.probe_id for a in run.answers}
    todo = [p for p in run.probes if p.id not in done]
    run.answers += [s["provider"].answer(p) for p in todo]
    phase = todo[0].phase if todo else "?"
    failed = sum(a.status != "ok" for a in run.answers if a.probe_id in {p.id for p in todo})
    run.log.append(f"Replayed {len(todo)} {phase} answers from fixtures ({failed} failed).")
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
        for t in run.topics:
            ps = [p for p in run.probes if p.topic_id == t.id and p.phase == phase and p.id in ev]
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
    run.decisions.append(d)
    run.probes += d.new_probes
    run.log.append(f"AnA decision: {', '.join(d.selected_topics) or 'stop'} — {d.rationale}")
    return {"run": run, "rounds": s["rounds"] + 1}


def route_after_followup(s: State) -> str:
    run = s["run"]
    pending = [p for p in run.probes if p.id not in {a.probe_id for a in run.answers}]
    return "execute_or_replay" if pending and s["rounds"] <= MAX_ADAPTIVE_ROUNDS else "build_gap_report"


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
                     ("choose_followup", choose_followup), ("build_gap_report", build_gap_report)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan_baseline")
    g.add_edge("plan_baseline", "validate_and_freeze")
    g.add_edge("validate_and_freeze", "execute_or_replay")
    g.add_edge("execute_or_replay", "evaluate")
    g.add_edge("evaluate", "choose_followup")
    g.add_conditional_edges("choose_followup", route_after_followup, ["execute_or_replay", "build_gap_report"])
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
