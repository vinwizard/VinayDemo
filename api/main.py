"""HTTP API over the existing Python engine. The engine is not modified — only observed.

Streamlit could only render progress when a graph NODE returned, so `execute_or_replay` froze the
page for the whole batch. Here the graph runs on a worker thread and pushes an event per ANSWER as
well as per node, so the browser sees real progress while a long batch is still running.
"""
import json
import queue
import threading
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import graph
from agents.evaluator_model import ModelEvaluator
from config import load_env, redacted_status
from providers import fixture, live
from reports import RUNS, load_run, save_run

_LOADED = load_env()
print(f"[config] {redacted_status(_LOADED)}")  # names only; a key value is never printed

app = FastAPI(title="Positioning Drift API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.get("/api/scenarios")
def scenarios():
    out = []
    for sid in sorted(fixture.SCENARIOS):
        p = fixture.FixtureProvider(sid)
        attrs = p.attributes()
        out.append(dict(
            id=sid, title=p.title, notice=p.data.get("notice"),
            company=p.data["profile"]["name"],
            named_probes=len(p.named_probes()),
            intended=[dict(id=a.id, label=a.label, weight=a.intended_weight,
                           claim_pages=a.claim_pages, claim_pages_total=a.claim_pages_total)
                      for a in attrs if a.intended]))
    return out


def build_provider(scenario: str, mode: str):
    """-> (provider, profile, expected_answers, run_mode). Live mode needs a key; it never falls back
    silently to fixtures, because a fixture result labelled live would be a fabricated measurement."""
    base = fixture.FixtureProvider(scenario)
    profile = fixture.bundled_profile(scenario)
    if mode != "live":
        return base, profile, len(base.named_probes()) + graph.MAX_BASELINE + graph.MAX_FOLLOWUP, "demo_replay"
    if not live.available():
        raise HTTPException(400, f"Live mode needs {live.KEY_ENV}. {live.status()}")
    prov = live.LiveProvider(base.attributes(), base.named_probes(), profile=profile,
                             evaluator=ModelEvaluator())
    return prov, profile, len(base.named_probes()), "live_api"


def run_events(scenario: str, mode: str = "demo") -> Iterator[str]:
    """Executes one run on a worker thread, yielding SSE as the graph progresses."""
    if scenario not in fixture.SCENARIOS:
        yield sse("error", {"message": f"unknown scenario {scenario!r}"})
        return
    try:
        prov, profile, expected, run_mode = build_provider(scenario, mode)
    except HTTPException as e:
        yield sse("error", {"message": str(e.detail)})
        return
    q: queue.Queue = queue.Queue()
    state = {"done": 0}

    inner = prov.answer

    def counting_answer(probe):                     # per-answer progress: the whole point
        a = inner(probe)
        state["done"] += 1
        q.put(("answer", dict(probe_id=probe.id, kind=probe.kind, phase=probe.phase,
                              text=probe.text, status=a.status,
                              done=state["done"], expected=expected)))
        return a

    prov.answer = counting_answer

    def work():
        try:
            run = graph.new_run(profile, prov, mode=run_mode)
            for node, run in graph.stream(run, prov):
                stage, agent = graph.STAGES[node]
                q.put(("node", dict(node=node, stage=stage, agent=agent,
                                    log=run.log[-1] if run.log else "")))
            save_run(run)
            q.put(("done", dict(run_id=run.id, run=json.loads(run.model_dump_json()))))
        except Exception as e:                       # surfaced, never swallowed
            q.put(("error", dict(message=f"{type(e).__name__}: {e}")))
        finally:
            q.put((None, None))

    threading.Thread(target=work, daemon=True).start()
    while True:
        kind, payload = q.get()
        if kind is None:
            return
        yield sse(kind, payload)


@app.get("/api/stream")
def stream(scenario: str = "A", mode: str = "demo"):
    return StreamingResponse(run_events(scenario, mode), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
def list_all():
    """Run history: newest first, with enough detail to pick one for comparison."""
    out = []
    for p in sorted(RUNS.glob("*.json")):
        try:
            r = load_run(p.stem)
        except Exception:
            continue
        d = r.drift
        out.append(dict(id=r.id, created_at=r.created_at, scenario=r.scenario, status=r.status,
                        company=r.profile.name,
                        alignment=d.alignment if d else None,
                        visibility=d.visibility if d else None,
                        landed=len(d.landed) if d else 0,
                        lost=len(d.lost_claims) if d else 0,
                        unstated=len(d.unstated_intent) if d else 0,
                        imposed=len(d.imposed) if d else 0))
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    try:
        return json.loads(load_run(run_id).model_dump_json())
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")


@app.get("/api/health")
def health():
    """Reports whether live mode is usable — never the key itself."""
    return {"ok": True, "scenarios": sorted(fixture.SCENARIOS),
            "live_available": live.available(), "live_status": live.status(),
            "measured_model": live.model_name() if live.available() else None}
