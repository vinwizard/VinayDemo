"""The why agent over HTTP (why.py): one investigation per claim and branded question, or one replay
test of a quick win's rewrite per buyer question, streamed as it runs, then kept beside the run it
examined, with its live re-check once the fix is published. The run itself is never changed."""
import traceback
from typing import Callable, Iterator, Optional

from fastapi import APIRouter, HTTPException, Request

import access
import reports
import verify
import why
from agents.ana import attribute_leaks, brand_leaks
from api.fleet import live_run, resolve
from fleet import MAX_TERM

router = APIRouter()
MAX_QUESTION = 200


@router.get("/api/runs/{run_id}/why")
def investigations(run_id: str, request: Request = None):
    """A run's investigations, newest first, each the whole record."""
    from api import main
    pid = main.pass_id(main.holder_of(request))
    if not main.sees_run(run_id, pid) or not reports.ID.fullmatch(run_id):
        raise HTTPException(404, f"run {run_id} not found")
    return [inv.model_dump() for inv in reports.list_investigations(run_id)
            if access.visible("investigation", inv.id, pid)]


def prepare(run_id: str, attribute: str, probe: Optional[str], question: Optional[str], term: Optional[str],
            holder) -> tuple:
    """-> (run, question, probe id, term, resolved model). Every refusal happens here, before any call."""
    run = live_run(run_id, holder, "asking why")
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
    return run, question, probe, term, resolve(holder, "Asking why")


def streamed(setup: Callable[[], tuple], holder) -> Iterator[str]:
    """Runs one experiment in a thread and streams its events. `setup` does every refusal first and
    returns (run, start event, the experiment as a function of emit -> Investigation)."""
    from api import main
    try:
        run, start, experiment = setup()
    except HTTPException as e:
        yield main.sse("error", {"message": str(e.detail)})
        return
    except Exception as e:
        traceback.print_exc()
        yield main.sse("error", {"message": f"Setup failed: {type(e).__name__}"})
        return
    pid = main.pass_id(holder)
    yield main.sse("start", start)

    def work(put):
        access.SPENDER.set(pid)
        try:
            inv = experiment(lambda kind, payload: put((kind, payload)))
            reports.save_investigation(inv)
            if pid:
                access.own("investigation", inv.id, pid, run.profile.name)
                access.log(pid, f"{'tested a rewrite for' if inv.kind == 'buyer' else 'asked why about'} {run.profile.name}")
            put(("done", inv.model_dump()))
        except access.Refused as e:
            put(("error", {"message": e.message}))
        except Exception as e:
            traceback.print_exc()
            put(("error", {"message": f"The investigation failed: {type(e).__name__}"}))

    for kind, payload in main.threaded(work):
        yield main.sse(kind, payload)


def why_events(run_id: str, attribute: str, probe: Optional[str], question: Optional[str],
               term: Optional[str], holder=None) -> Iterator[str]:
    def setup():
        run, q, pid, t, resolved = prepare(run_id, attribute, probe, question, term, holder)

        def experiment(emit):
            from agents.evaluator_model import ModelEvaluator
            lab = why.Lab(resolved.model, resolved.tool)
            evaluator = None if t else ModelEvaluator(model=resolved.judge, transport=lab.judge_transport)
            return why.start(run, attribute, q, probe_id=pid, term=t, lab=lab, evaluator=evaluator, emit=emit)
        return run, {"budget_usd": why.budget(), "question": q, "model": resolved.model}, experiment
    return streamed(setup, holder)


def rewrite_events(run_id: str, attribute: str, probe: str, holder=None) -> Iterator[str]:
    """A quick win's replay test: its rewrite against one buyer question it was written for."""
    def setup():
        run = live_run(run_id, holder, "testing a rewrite")
        action = next((a for a in run.win_back if a.attribute_id == attribute), None)
        p = next((p for p in run.probes if p.id == probe and p.kind == "blind"), None)
        if action is None or p is None or probe not in action.question_ids:
            raise HTTPException(404, "Only a suggested rewrite, against a buyer question it was written for, can be tested.")
        resolved = resolve(holder, "Testing a rewrite")

        def experiment(emit):
            return why.test_rewrite(run, attribute, probe, lab=why.Lab(resolved.model, resolved.tool), emit=emit)
        return run, {"budget_usd": why.budget(), "question": p.text, "model": resolved.model}, experiment
    return streamed(setup, holder)


@router.get("/api/runs/{run_id}/rewrite-test/stream")
def rewrite_stream(run_id: str, attribute: str, probe: str, request: Request = None):
    from api import main
    return main.sse_response(rewrite_events(run_id, attribute, probe, main.holder_of(request)))


def recheck_events(inv_id: str, holder=None) -> Iterator[str]:
    """"Mark fix live" on a rewrite its replay test proved: the page first (free), then live asks. The
    result is kept on the investigation."""
    from api import main
    try:
        main.refuse_in_public("re-checking a fix", holder)
        if not access.visible("investigation", inv_id, main.pass_id(holder)):
            raise HTTPException(404, f"investigation {inv_id} not found")
        try:
            inv = reports.load_investigation(inv_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, f"investigation {inv_id} not found")
        if inv.kind != "buyer" or not any(v.fix in ("copy", "authority") for v in inv.verdicts):
            raise HTTPException(400, "Only a rewrite its replay test proved can be re-checked.")
    except HTTPException as e:
        yield main.sse("error", {"message": str(e.detail)})
        return
    pid = main.pass_id(holder)

    def work(put):
        with access.spending(pid):
            try:
                v = verify.verify_investigation(inv_id, lambda: resolve(holder, "Re-checking a fix"),
                                                emit=lambda text: put(("log", {"text": text})))
                inv.verification = v
                reports.save_investigation(inv)
                put(("done", v.model_dump()))
            except HTTPException as e:
                put(("error", {"message": str(e.detail)}))
            except access.Refused as e:
                put(("error", {"message": e.message}))
            except Exception as e:
                traceback.print_exc()
                put(("error", {"message": f"The re-check failed: {type(e).__name__}"}))

    for kind, payload in main.threaded(work):
        yield main.sse(kind, payload)


@router.get("/api/investigations/{inv_id}/verify/stream")
def recheck_stream(inv_id: str, request: Request = None):
    from api import main
    return main.sse_response(recheck_events(inv_id, main.holder_of(request)))


@router.get("/api/runs/{run_id}/why/stream")
def why_stream(run_id: str, attribute: str, probe: Optional[str] = None, question: Optional[str] = None,
               term: Optional[str] = None, request: Request = None):
    from api import main
    return main.sse_response(why_events(run_id, attribute, probe, question, term, main.holder_of(request)))
