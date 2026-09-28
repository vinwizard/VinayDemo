"""The why agent over HTTP (why.py): one investigation per claim and branded question, streamed as
it runs, then kept beside the run it examined. The run itself is never changed."""
import queue
import threading
import traceback
from typing import Iterator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import access
import reports
import why
from agents.ana import attribute_leaks, brand_leaks
from providers import live

router = APIRouter()
MAX_QUESTION, MAX_TERM = 200, 40


def summary(inv) -> dict:
    return dict(id=inv.id, created_at=inv.created_at, claim=inv.claim, attribute_id=inv.attribute_id,
                question=inv.question, status=inv.status, verdicts=[v.kind for v in inv.verdicts],
                spent_usd=inv.spent_usd, budget_usd=inv.budget_usd)


@router.get("/api/runs/{run_id}/why")
def investigations(run_id: str, request: Request = None):
    """A run's investigations, newest first, each the whole record."""
    from api import main
    pid = main.pass_id(main.holder_of(request))
    if not access.visible("run", run_id, pid) or not reports.ID.fullmatch(run_id):
        raise HTTPException(404, f"run {run_id} not found")
    return [inv.model_dump() for inv in reports.list_investigations(run_id)
            if access.visible("investigation", inv.id, pid)]


@router.get("/api/investigations/{inv_id}")
def investigation(inv_id: str, request: Request = None):
    from api import main
    if not access.visible("investigation", inv_id, main.pass_id(main.holder_of(request))):
        raise HTTPException(404, f"investigation {inv_id} not found")
    try:
        return reports.load_investigation(inv_id).model_dump()
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"investigation {inv_id} not found")


def prepare(run_id: str, attribute: str, probe: Optional[str], question: Optional[str], term: Optional[str],
            holder) -> tuple:
    """-> (run, question, probe id, term, resolved model). Every refusal happens here, before any call."""
    from api import main
    main.refuse_in_public("asking why", holder)
    if not access.visible("run", run_id, main.pass_id(holder)):
        raise HTTPException(404, f"run {run_id} not found")
    try:
        run = reports.load_run(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"run {run_id} not found")
    if run.mode != "live_api":
        raise HTTPException(400, "Only a live run can be investigated: a sample run's answers were written by hand.")
    target = next((a for a in run.attributes if a.id == attribute), None)
    if target is None:
        raise HTTPException(404, f"unknown claim {attribute!r}")
    if probe:
        p = next((p for p in run.probes if p.id == probe and p.kind == "named"), None)
        if p is None:
            raise HTTPException(404, f"{probe!r} is not a branded question of this run")
        question = p.text
    question = " ".join((question or "").split())
    if not question or len(question) > MAX_QUESTION:
        raise HTTPException(400, f"Ask a branded question of at most {MAX_QUESTION} characters.")
    if not brand_leaks(question, run.profile):
        raise HTTPException(400, f"The question must name {run.profile.name}: the why agent explains what AI "
                                 "says about the company when asked about it.")
    if attribute_leaks(question, [target]):
        raise HTTPException(400, "The question names the claim it would test, which invites the model to agree. "
                                 "Ask without naming it.")
    term = " ".join((term or "").split()) or None
    if term and len(term) > MAX_TERM:
        raise HTTPException(400, f"The word to look for must be at most {MAX_TERM} characters.")
    if not live.available():
        raise HTTPException(400, f"Asking why needs {live.KEY_ENV}. {live.status()}")
    try:
        with access.spending(main.pass_id(holder)):
            resolved = live.preflight()
    except access.Refused as e:
        raise HTTPException(403, e.message)
    except live.PreflightFailed as e:
        raise HTTPException(400, str(e))
    if resolved.tool is None:
        raise HTTPException(400, "Asking why needs a model that can search the web, and this account's cannot.")
    return run, question, probe, term, resolved


def why_events(run_id: str, attribute: str, probe: Optional[str], question: Optional[str],
               term: Optional[str], holder=None) -> Iterator[str]:
    from api import main
    try:
        run, question, probe, term, resolved = prepare(run_id, attribute, probe, question, term, holder)
    except HTTPException as e:
        yield main.sse("error", {"message": str(e.detail)})
        return
    except Exception as e:
        traceback.print_exc()
        yield main.sse("error", {"message": f"Setup failed: {type(e).__name__}"})
        return
    q: queue.Queue = queue.Queue()
    pid = main.pass_id(holder)
    yield main.sse("start", {"budget_usd": why.budget(), "question": question, "model": resolved.model})

    def work():
        access.SPENDER.set(pid)
        try:
            from agents.evaluator_model import ModelEvaluator
            lab = why.Lab(resolved.model, resolved.tool)
            evaluator = None if term else ModelEvaluator(model=resolved.judge, transport=lab.judge_transport)
            inv = why.start(run, attribute, question, probe_id=probe, term=term, lab=lab, evaluator=evaluator,
                            emit=lambda kind, payload: q.put((kind, payload)))
            reports.save_investigation(inv)
            if pid:
                access.own("investigation", inv.id, pid, run.profile.name)
                access.log(pid, f"asked why about {run.profile.name}")
            q.put(("done", inv.model_dump()))
        except access.Refused as e:
            q.put(("error", {"message": e.message}))
        except Exception as e:
            traceback.print_exc()
            q.put(("error", {"message": f"The investigation failed: {type(e).__name__}"}))
        finally:
            q.put((None, None))

    threading.Thread(target=work, daemon=True).start()
    while True:
        kind, payload = q.get()
        if kind is None:
            return
        yield main.sse(kind, payload)


@router.get("/api/runs/{run_id}/why/stream")
def why_stream(run_id: str, attribute: str, probe: Optional[str] = None, question: Optional[str] = None,
               term: Optional[str] = None, request: Request = None):
    from api import main
    return StreamingResponse(why_events(run_id, attribute, probe, question, term, main.holder_of(request)),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
