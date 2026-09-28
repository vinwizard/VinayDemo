"""The investigation fleet over HTTP (fleet.py, verify.py): start one on a live run, stream its event
log as it is written, and re-check a fix once it is live. The run itself is never changed."""
import queue
import threading
import time
import traceback
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import access
import fleet
import reports
import verify
from providers import live

router = APIRouter()
RUNNING: dict[str, tuple[str, threading.Thread]] = {}   # fleet id -> (run id, its thread), in this process
VERIFYING: set[tuple[str, int]] = set()
_lock = threading.Lock()
POLL_S = 0.5
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def event_sse(e) -> str:
    return f"id: {e.seq}\nevent: fleet\ndata: {e.model_dump_json()}\n\n"


def live_run(run_id: str, holder, what: str):
    """The saved live run, or the HTTPException every refusal raises before anything is spent."""
    from api import main
    main.refuse_in_public(what, holder)
    if not reports.ID.fullmatch(run_id) or not access.visible("run", run_id, main.pass_id(holder)):
        raise HTTPException(404, f"run {run_id} not found")
    try:
        run = reports.load_run(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"run {run_id} not found")
    if run.mode != "live_api":
        raise HTTPException(400, "Only a live run can be investigated: a sample run's answers were written by hand.")
    return run


def resolve(holder, what: str):
    """The live model pair, as preflight settles it for this pass."""
    from api import main
    if not live.available():
        raise HTTPException(400, f"{what} needs {live.KEY_ENV}. {live.status()}")
    try:
        with access.spending(main.pass_id(holder)):
            resolved = live.preflight()
    except access.Refused as e:
        raise HTTPException(403, e.message)
    except live.PreflightFailed as e:
        raise HTTPException(400, str(e))
    if resolved.tool is None:
        raise HTTPException(400, f"{what} needs a model that can search the web, and this account's cannot.")
    return resolved


def running(fleet_id: str) -> bool:
    with _lock:
        return fleet_id in RUNNING and RUNNING[fleet_id][1].is_alive()


def visible_fleet(fleet_id: str, holder) -> fleet.EventLog:
    from api import main
    if not reports.ID.fullmatch(fleet_id) or not access.visible("fleet", fleet_id, main.pass_id(holder)):
        raise HTTPException(404, f"fleet {fleet_id} not found")
    log = fleet.EventLog(fleet_id)
    if not log.path.exists() and not running(fleet_id):
        raise HTTPException(404, f"fleet {fleet_id} not found")
    return log


@router.get("/api/runs/{run_id}/fleets")
def fleets(run_id: str, request: Request = None):
    """A run's fleets, newest first, and what a new one would cost."""
    from api import main
    pid = main.pass_id(main.holder_of(request))
    if not reports.ID.fullmatch(run_id) or not access.visible("run", run_id, pid):
        raise HTTPException(404, f"run {run_id} not found")
    try:
        run = reports.load_run(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, f"run {run_id} not found")
    return {"fleets": [f for f in fleet.list_fleets(run_id) if access.visible("fleet", f["id"], pid)],
            "estimate": fleet.estimate(run) if run.mode == "live_api" else None}


@router.post("/api/runs/{run_id}/fleet")
def start(run_id: str, request: Request = None):
    """Starts a fleet on a worker thread and returns its id at once; the log streams from there."""
    from api import main
    holder = main.holder_of(request)
    run = live_run(run_id, holder, "investigating the gaps")
    if not fleet.shortlist(run):
        raise HTTPException(400, "Nothing on this run to investigate: no claim to win back or amplify, and no "
                                 "perception AI raises in a brand answer.")
    with _lock:
        if any(r == run_id and t.is_alive() for r, t in RUNNING.values()):
            raise HTTPException(409, "A fleet is already investigating this run.")
    resolved = resolve(holder, "Investigating the gaps")
    fleet_id, pid = fleet.new_id(), main.pass_id(holder)
    if pid:
        access.own("fleet", fleet_id, pid, run.profile.name)
        access.log(pid, f"started a fleet on {run.profile.name}")

    def work():
        log = fleet.EventLog(fleet_id)
        with access.spending(pid):
            try:
                fleet.execute(run, log, resolved, pass_id=pid)
            except BaseException as e:
                traceback.print_exc()
                log.append("stopped", reason=f"The fleet failed: {type(e).__name__}.")
                log.append("done", status="stopped")

    t = threading.Thread(target=work, daemon=True)
    with _lock:
        RUNNING[fleet_id] = (run_id, t)
    t.start()
    return {"id": fleet_id}


def fleet_events(fleet_id: str, after: int, holder) -> Iterator[str]:
    from api import main
    try:
        log = visible_fleet(fleet_id, holder)
    except HTTPException as e:
        yield main.sse("error", {"message": str(e.detail)})
        return
    seen, ended = after, any(e.kind == "done" for e in log.read())
    while True:
        new = log.read(seen)
        for e in new:
            yield event_sse(e)
            seen = e.seq
        if ended or any(e.kind == "done" for e in new):
            yield main.sse("end", {"seq": seen})
            return
        if not new and not running(fleet_id):
            # the process that ran it is gone (a restart): say so once, keep what finished
            log.append("stopped", reason="The server restarted while this fleet ran; what finished is kept.")
            log.append("done", status="stopped")
            continue
        time.sleep(POLL_S)


@router.get("/api/fleets/{fleet_id}/stream")
def stream(fleet_id: str, after: int = 0, request: Request = None):
    """The fleet's log as SSE: every event after `after` (a reconnect's last seen number), then the
    rest as they are written, then `end` once the fleet is done."""
    from api import main
    after = max(after, int(request.headers.get("last-event-id") or 0) if request else 0)
    return StreamingResponse(fleet_events(fleet_id, after, main.holder_of(request)),
                             media_type="text/event-stream", headers=SSE_HEADERS)


def verify_events(fleet_id: str, rank: int, holder) -> Iterator[str]:
    from api import main
    try:
        main.refuse_in_public("re-checking a fix", holder)
        log = visible_fleet(fleet_id, holder)
        events = log.read()
        if not any(e.kind == "done" for e in events):
            raise HTTPException(409, "The fleet is still running: re-check a fix once its plan is written.")
        plan = fleet.plan_of(events)
        item = next((i for i in plan.items if i.rank == rank), None) if plan else None
        if item is None or item.fix not in ("copy", "authority"):
            raise HTTPException(400, "Only a tested copy or authority fix can be re-checked.")
        with _lock:
            if (fleet_id, rank) in VERIFYING:
                raise HTTPException(409, "This fix is already being re-checked.")
            VERIFYING.add((fleet_id, rank))
    except HTTPException as e:
        yield main.sse("error", {"message": str(e.detail)})
        return
    q: queue.Queue = queue.Queue()
    pid = main.pass_id(holder)

    def work():
        with access.spending(pid):
            try:
                q.put(log.append("verify", rank=rank, text=f"Re-checking fix {rank}: {item.claim}."))
                v = verify.verify(fleet_id, rank, lambda: resolve(holder, "Re-checking a fix"),
                                  emit=lambda text: q.put(log.append("verify", rank=rank, text=text)))
                q.put(log.append("verified", rank=rank, verification=v.model_dump()))
            except HTTPException as e:
                q.put(log.append("verify", rank=rank, text=str(e.detail), error=True))
            except access.Refused as e:
                q.put(log.append("verify", rank=rank, text=e.message, error=True))
            except Exception as e:
                traceback.print_exc()
                q.put(log.append("verify", rank=rank, text=f"The re-check failed: {type(e).__name__}.", error=True))
            finally:
                with _lock:
                    VERIFYING.discard((fleet_id, rank))
                q.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (e := q.get()) is not None:
        yield event_sse(e)
    yield main.sse("end", {"rank": rank})


@router.get("/api/fleets/{fleet_id}/verify/stream")
def verify_stream(fleet_id: str, rank: int, request: Request = None):
    """Re-checks plan item `rank` of a finished fleet: the page first (free), then live asks. Its events
    go onto the fleet's log too, so the result is kept."""
    from api import main
    return StreamingResponse(verify_events(fleet_id, rank, main.holder_of(request)),
                             media_type="text/event-stream", headers=SSE_HEADERS)


def health() -> dict:
    return {"fleet_budget_usd": fleet.budget(), "fleet_concurrency": fleet.concurrency(),
            "verify_budget_usd": verify.budget()}
