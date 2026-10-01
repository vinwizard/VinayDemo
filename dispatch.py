"""One process-wide dispatcher for every run's measured asks.

Every run hands its asks here instead of to a pool of its own, so LIVE_CONCURRENCY is one cap on
what the whole process has in flight however many people are measuring at once. The next ask is
taken from each run in turn (round-robin by run key), so a 55-question run never makes a 10-question
run wait for it to finish. Each ask runs in a copy of the context that submitted it, so the pass
paying for it (access.SPENDER) is that run's own, and its answer comes back on that run's future
only: nothing a run asked reaches another. Rate limits are handled where every model call passes,
in access._metered (a 429 pauses every call in the process for the time the API asked). An ask
whose pass has calls under way that may reach its cap waits in the queue (access.room), not on a
worker, so the other runs' asks go ahead.

Not the OpenAI Batch API: that one answers within 24 hours, and a run is watched while it happens.
"""
import threading
from collections import deque
from concurrent.futures import Future
from contextvars import copy_context
from typing import Callable, Hashable, Optional

import access
from config import setting

CONCURRENCY_ENV = "LIVE_CONCURRENCY"
DEFAULT_CONCURRENCY = 16
ROOM_POLL_S = 0.5    # a pass's calls under way may be charged outside the dispatcher: look again


def live_concurrency() -> int:
    return setting(CONCURRENCY_ENV, DEFAULT_CONCURRENCY, floor=1)


class Dispatcher:
    def __init__(self, cap: int):
        self.cap = cap
        self._queues: dict[Hashable, deque] = {}   # run key -> its queued asks, oldest first
        self._turn: deque = deque()                 # run keys with something queued, next first
        self._cv = threading.Condition()
        self.in_flight = self.peak = 0              # for tests and the timing script
        for _ in range(cap):
            threading.Thread(target=self._work, daemon=True).start()

    def submit(self, key: Hashable, fn: Callable, *args) -> Future:
        """Queue fn(*args) under `key` (a run): its result or exception lands on the future returned."""
        fut, ctx = Future(), copy_context()
        with self._cv:
            if key not in self._queues:
                self._queues[key] = deque()
                self._turn.append(key)
            self._queues[key].append((fut, ctx, fn, args))
            self._cv.notify()
        return fut

    def cancel(self, key: Hashable) -> int:
        """Drop what `key` still has queued (a run that failed or stopped); its asks in flight finish
        and are thrown away. Other runs' asks are untouched. -> how many were dropped."""
        with self._cv:
            q = self._queues.pop(key, deque())
            if key in self._turn:
                self._turn.remove(key)
        for fut, *_ in q:
            fut.cancel()
        return len(q)

    def _next(self) -> Optional[tuple]:
        """The next ask that may start now, taking the runs in turn. Called holding _cv."""
        for _ in range(len(self._turn)):
            key = self._turn.popleft()
            q = self._queues[key]
            if not q[0][1].run(access.room):
                self._turn.append(key)
                continue
            item = q.popleft()
            if q:
                self._turn.append(key)          # back of the line: the other runs go first
            else:
                del self._queues[key]
            return item
        return None

    def _work(self) -> None:
        while True:
            with self._cv:
                while (item := self._next()) is None:
                    self._cv.wait(ROOM_POLL_S if self._turn else None)
                fut, ctx, fn, args = item
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
            try:
                if fut.set_running_or_notify_cancel():
                    try:
                        fut.set_result(ctx.run(fn, *args))
                    except BaseException as e:      # access.Refused too: it must stop the run that asked
                        fut.set_exception(e)
            finally:
                with self._cv:
                    self.in_flight -= 1
                    self._cv.notify_all()


_shared: Optional[Dispatcher] = None
_shared_lock = threading.Lock()


def shared() -> Dispatcher:
    """The process's dispatcher, started on first use with LIVE_CONCURRENCY workers."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Dispatcher(live_concurrency())
        return _shared
