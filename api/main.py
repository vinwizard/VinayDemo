"""HTTP API over the existing Python engine. The engine is not modified — only observed.

Streamlit could only render progress when a graph NODE returned, so `execute_or_replay` froze the
page for the whole batch. Here the graph runs on a worker thread and pushes an event per ANSWER as
well as per node, so the browser sees real progress while a long batch is still running.
"""
import json
import queue
import threading
import traceback
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import fetching
import graph
from agents.evaluator_model import ModelEvaluator
from agents.onboarding_model import OnboardingAgent
from config import load_env, redacted_status
from providers import fixture, live
from reports import RUNS, load_run, save_run

_LOADED = load_env()
print(f"[config] {redacted_status(_LOADED)}")  # names only; a key value is never printed

app = FastAPI(title="Positioning Drift API")

# Any loopback port, because Vite silently moves to 5174/5175 when 5173 is taken and a pinned
# origin then fails as an opaque "TypeError: Failed to fetch" in the browser.
# DEV ONLY: tighten this to the real origin before deploying anywhere.
LOOPBACK_ORIGIN = r"http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
app.add_middleware(CORSMiddleware, allow_origin_regex=LOOPBACK_ORIGIN,
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
            intended=[dict(id=a.id, label=a.label, description=a.description,
                           weight=a.intended_weight, claim_pages=a.claim_pages,
                           claim_pages_total=a.claim_pages_total)
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
    try:
        live.preflight()   # one trivial call: an unusable model fails once, not 20 times
    except live.ModelUnsupported as e:
        raise HTTPException(400, str(e))
    prov = live.LiveProvider(base.attributes(), base.named_probes(), profile=profile,
                             evaluator=ModelEvaluator())
    # a live run is both axes now: count the blind probes its own plan will produce, or the progress
    # bar reads "20/8"
    _, blind = prov.plan(profile)
    return prov, profile, len(blind) + len(base.named_probes()), "live_api"


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
    except Exception as e:                           # setup failures surface too, minus the detail
        traceback.print_exc()                        # the detail stays on the server console
        yield sse("error", {"message": f"Setup failed before the run started: {type(e).__name__}"})
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
                        contested=len(d.contested) if d else 0,
                        unstated=len(d.unstated_intent) if d else 0,
                        imposed=len(d.imposed) if d else 0))
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    try:
        return json.loads(load_run(run_id).model_dump_json())
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")


@app.get("/api/onboard")
def onboard(url: str, name: str = ""):
    """Agent 1: crawl a company's own pages and extract the CLAIMED layer.

    Returns claimed attributes with descriptions, verbatim quotes and page counts DERIVED from
    those quotes. Intent weights are deliberately absent — what a company wants to be known for is
    the customer's input and is not derivable from their own marketing copy.
    """
    if not live.available():
        raise HTTPException(400, f"Onboarding needs {live.KEY_ENV} for the extraction model.")
    try:
        pages = fetching.fetch_site(url, max_pages=3)
    except fetching.UnsafeURL as e:
        raise HTTPException(400, f"Refused: {e}")
    except fetching.FetchError as e:
        raise HTTPException(502, f"Could not fetch: {e}")
    domain = fetching.validate(url)[1].removeprefix("www.")
    try:
        profile, attrs, warnings = OnboardingAgent().run(name, domain, pages)
    except ValueError as e:
        raise HTTPException(502, f"Extraction failed: {e}")
    return dict(
        profile=dict(name=profile.name, domain=profile.domain, aliases=profile.aliases,
                     customer_types=profile.customer_types,
                     one_liner=profile.positioning_points[0].text if profile.positioning_points else None,
                     warnings=profile.warnings),
        pages=[dict(url=u, chars=len(t)) for u, t in pages],
        attributes=[dict(id=a.id, label=a.label, description=a.description, aliases=a.aliases,
                         claim_quotes=a.claim_quotes, claim_pages=a.claim_pages,
                         claim_pages_total=a.claim_pages_total,
                         buyer_questions=a.buyer_questions, intended_weight=a.intended_weight)
                    for a in attrs],
        warnings=warnings)


@app.get("/api/health")
def health():
    """Reports whether live mode is usable — never the key itself."""
    from agents import evaluator_model
    measured = live.model_name() if live.available() else None
    evaluator = evaluator_model.model_name() if live.available() else None
    return {"ok": True, "scenarios": sorted(fixture.SCENARIOS),
            "live_available": live.available(), "live_status": live.status(),
            "measured_model": measured, "evaluator_model": evaluator,
            # a model grading its own output has a self-preference bias worth surfacing
            "same_model_warning": bool(measured and evaluator and measured == evaluator)}
