"""Brand and buyer questions asked side by side, and many runs sharing one dispatcher (dispatch.py).

The aimed front's category is the customer's own, so it is asked beside the brand questions; the
placed front waits for the brand answers it is planned from, and nothing else. Every run's asks go
to one process-wide dispatcher: one cap on what is in flight, taken from each run in turn.
No key, no network: transports sleep instead of calling a model, and log when each ask ran.
"""
import threading
import time
import zlib
from collections import defaultdict

import pytest

import access
import dispatch
import graph
import sampler
from fakes import Judge, openai_reply
from providers import fixture, live
from test_fronts import AIM_QS, AIMING, ENDORSE, PLACED, WRITTEN

F = fixture.FixtureProvider("A")
PLACED_LIST = [*PLACED.buyer_questions, *WRITTEN]
PLACED_QS = set(PLACED_LIST)
BRAND_QS = {p.text for p in F.named_probes()}
USAGE = {"input_tokens": 1000, "output_tokens": 100}


def says(q: str) -> str:
    """One answer per question, whatever order the asks run in."""
    if q == f"Which companies lead in {PLACED.label}?":
        return "Notion, Coda and Linear lead."
    if q.startswith("Which companies lead in"):
        return "Linear, Asana and Coda lead."
    if q in PLACED_QS:   # half name the brand, so the placed front is unsure at look 1 and asks look 2
        return "Notion fits." if PLACED_LIST.index(q) % 2 == 0 else "Coda fits."
    if q in AIM_QS:
        return "Coda fits."
    return "Notion is an AI-native workspace for teams."


class Clock:
    """A transport that sleeps `delay(question)` and records when each ask ran, across threads."""

    def __init__(self, delay=lambda q: 0.0, text=says, fail=lambda q: False):
        self.delay, self.text, self.fail = delay, text, fail
        self.asks, self.now, self.peak = [], 0, 0
        self._lock = threading.Lock()

    def __call__(self, messages, model, timeout):
        q = messages[-1]["content"]
        with self._lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        t0 = time.monotonic()
        try:
            time.sleep(self.delay(q))
            if self.fail(q):
                raise RuntimeError("upstream broke")
            return openai_reply(self.text(q), searched=True, usage=USAGE)
        finally:
            with self._lock:
                self.now -= 1
                self.asks.append((q, t0, time.monotonic()))

    def span(self, pred) -> tuple[float, float]:
        ts = [(a, b) for q, a, b in self.asks if pred(q)]
        return min(a for a, _ in ts), max(b for _, b in ts)


def provider(clock, aiming=AIMING, sequential=False):
    profile = F.profile.model_copy(update=dict(core_category=aiming, category_questions=AIM_QS))
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="gpt-6-luna",
                             transport=clock, evaluator=Judge(endorse=ENDORSE), writer=lambda l, d, n: WRITTEN[:n])
    if sequential:   # the order a run had before: one ask at a time, every buyer question after the brand's
        prov.concurrency, prov.plan_aiming = 1, None
    return profile, prov


def measure(clock, aiming=AIMING, sequential=False, dispatcher=None):
    profile, prov = provider(clock, aiming, sequential)
    return graph.execute(graph.new_run(profile, prov, mode="live_api"), prov,
                         dispatcher or dispatch.Dispatcher(16)), prov


def content(run) -> dict:
    """Everything a run saves except what names this run or this moment."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("collected_at", "created_at")}
        return [strip(v) for v in x] if isinstance(x, list) else x
    return strip(run.model_dump(mode="json", exclude={"id", "log"}))


@pytest.fixture(autouse=True)
def small_fronts(monkeypatch):
    monkeypatch.setenv(sampler.MARGIN_ENV, "33")   # six questions frozen a front, four asked first


def is_brand(q):
    return q in BRAND_QS


def test_the_aimed_front_is_asked_while_the_brand_questions_are():
    clock = Clock(delay=lambda q: 0.15 if is_brand(q) else 0.02)
    run, _ = measure(clock)
    brand_start, brand_end = clock.span(is_brand)
    aimed_start, _ = clock.span(lambda q: q in AIM_QS)
    assert aimed_start < brand_end           # not after the brand answers: beside them
    assert run.status == "complete" and {s.front for s in run.drift.sets} >= {"placed", "aiming"}


def test_the_placed_front_starts_without_waiting_for_the_aimed_front():
    clock = Clock(delay=lambda q: 0.5 if q in AIM_QS else 0.01)
    run, _ = measure(clock)
    _, aimed_end = clock.span(lambda q: q in AIM_QS)
    placed_start, _ = clock.span(lambda q: q in PLACED_QS)
    _, brand_end = clock.span(is_brand)
    assert brand_end < placed_start < aimed_end
    # and it is still planned from the brand answers: they endorsed the AI-native claim
    placed = next(s for s in run.drift.sets if s.front == "placed")
    assert placed.category == PLACED.label
    assert any("Where AI places Notion: AI-native workspace (endorsed in 8 of 8" in line for line in run.log)


def test_no_brand_endorsement_means_no_placed_front_even_when_the_aimed_one_is_already_asked():
    clock = Clock(text=lambda q: "Notion is a tool." if is_brand(q) else says(q))
    run, _ = measure(clock)
    assert [s.front for s in run.drift.sets if s.front] == ["aiming"]
    assert "placed" in run.drift.missing_fronts


@pytest.mark.parametrize("aiming", [AIMING, PLACED.label + " tools"])   # two fronts; one shared set
def test_a_parallel_run_saves_what_a_sequential_one_did(aiming):
    """Same answers, whatever order they come back in: jittered delays shuffle the completions."""
    jitter = lambda q: (zlib.crc32(q.encode()) % 7) / 200
    seq, _ = measure(Clock(), aiming, sequential=True)
    par, _ = measure(Clock(delay=jitter), aiming)
    if aiming == AIMING:   # the placed front is unsure at look 1: its look 2 is decided while the other front runs
        assert [f.look for f in par.sampler.fronts] == [2, 1]
    assert content(par) == content(seq)


def test_one_failing_call_fails_that_answer_and_nothing_else():
    broken = AIM_QS[1]
    seq, _ = measure(Clock(fail=lambda q: q == broken), sequential=True)
    par, _ = measure(Clock(fail=lambda q: q == broken, delay=lambda q: 0.01))
    failed = [a for a in par.answers if a.status != "ok"]
    assert [a.probe_id for a in failed] == ["cat-b2"] and par.status == "complete"
    assert content(par) == content(seq)


def test_a_run_budget_stops_look_2_as_it_did(monkeypatch):
    monkeypatch.setenv(sampler.BUDGET_ENV, "0.001")
    seq, _ = measure(Clock(), sequential=True)
    par, _ = measure(Clock(delay=lambda q: 0.01))
    assert all(f.look == 1 for f in par.sampler.fronts)
    assert any("budget" in (f.note or "") for f in par.sampler.fronts)
    assert content(par) == content(seq)



@pytest.mark.parametrize("calls", [29, 33, 37])   # around what look 2 costs: some fronts get it, some do not
def test_a_run_budget_that_allows_some_look_2_decides_as_the_sequential_run_did(monkeypatch, calls):
    one = access.cost("gpt-6-luna", Clock()([{"content": "q"}], "gpt-6-luna", 1))[0]
    monkeypatch.setenv(sampler.BUDGET_ENV, str(one * (calls + 0.5)))
    seq, _ = measure(Clock(), sequential=True)
    par, _ = measure(Clock(delay=lambda q: 0.01))
    assert content(par) == content(seq)

# ---------------------------------------------------------------- many runs, one dispatcher
def test_four_runs_share_one_cap_fairly_and_keep_their_own_answers():
    d = dispatch.Dispatcher(4)
    clocks = [Clock(delay=lambda q: 0.01, text=lambda q, k=k: f"[run {k}] {says(q)}") for k in range(4)]
    runs = [None] * 4

    def go(k):
        runs[k] = measure(clocks[k], dispatcher=d)

    threads = [threading.Thread(target=go, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert d.peak <= 4                                          # one cap for the whole process
    solo, solo_prov = measure(Clock())
    for k, (run, prov) in enumerate(runs):
        texts = [a.text for a in [*run.answers, *run.repeat_answers] if a.status == "ok"]
        assert texts and all(t.startswith(f"[run {k}]") for t in texts)   # nothing crossed runs
        assert len(run.answers) == len(solo.answers)
        # each run's purse is its own: exactly the calls it made, at the reported usage
        one = access.cost(prov.model, Clock()([{"content": "q"}], prov.model, 1))[0]
        assert prov.spent == pytest.approx(len(clocks[k].asks) * one)
    # fairness: every run was being answered before any other had finished
    spans = [c.span(lambda q: True) for c in clocks]
    assert max(start for start, _ in spans) < min(end for _, end in spans)


def test_a_run_that_fails_drops_only_its_own_queued_asks():
    d = dispatch.Dispatcher(2)
    calls = defaultdict(int)

    def refusing(messages, model, timeout):   # a pass hitting its cap mid-run
        calls["bad"] += 1
        if calls["bad"] > 3:
            raise access.Refused("capped")
        return Clock(delay=lambda q: 0.01)(messages, model, timeout)

    good, bad = {}, {}
    t = threading.Thread(target=lambda: good.update(run=measure(Clock(delay=lambda q: 0.01), dispatcher=d)[0]))
    t.start()
    with pytest.raises(access.Refused):
        measure(refusing, dispatcher=d)
    t.join()
    assert good["run"].status == "complete" and all(a.status == "ok" for a in good["run"].answers)
    assert calls["bad"] <= 3 + 2              # at most what was in flight when it failed
    assert not d._queues                       # nothing of the failed run left waiting


def test_round_robin_lets_a_small_run_through_a_big_one():
    d = dispatch.Dispatcher(2)
    done = defaultdict(list)
    work = lambda key, i: (time.sleep(0.01), done[key].append(time.monotonic()))
    big = [d.submit("big", work, "big", i) for i in range(40)]
    small = [d.submit("small", work, "small", i) for i in range(4)]
    for f in big + small:
        f.result()
    assert max(done["small"]) < sorted(done["big"])[10]   # not after the big run's 40
    assert d.peak <= 2


def test_cancel_drops_queued_asks_of_that_run_only():
    d = dispatch.Dispatcher(1)
    gate = threading.Event()
    first = d.submit("a", gate.wait)
    while not d.in_flight:
        time.sleep(0.001)
    a_rest = [d.submit("a", lambda: "a") for _ in range(3)]
    b = d.submit("b", lambda: "b")
    assert d.cancel("a") == 3
    gate.set()
    assert first.result() is True and b.result() == "b"
    assert all(f.cancelled() for f in a_rest)


# ---------------------------------------------------------------- metering under concurrency
class RateLimited(Exception):
    status_code, code = 429, "rate_limit_exceeded"

    def __init__(self, headers):
        self.response = type("R", (), {"headers": headers})()


def test_a_429_pauses_every_call_for_the_time_the_api_asked_then_retries(monkeypatch):
    seen = []

    def create(timeout, **kw):
        seen.append(time.monotonic())
        if len(seen) == 1:
            raise RateLimited({"retry-after-ms": "200"})
        return {"usage": USAGE}

    monkeypatch.setattr(access, "_create", create)
    monkeypatch.setattr(access, "_calm_at", 0.0)
    access.openai_response(5, model="gpt-6-luna", input="hi")
    assert len(seen) == 2 and seen[1] - seen[0] >= 0.19
    # a call that starts during the pause waits it out too
    access.pause(0.2)
    t0 = time.monotonic()
    access.openai_response(5, model="gpt-6-luna", input="hi")
    assert seen[-1] - t0 >= 0.19


def test_an_exhausted_quota_is_not_waited_on(monkeypatch):
    class Quota(RateLimited):
        code = "insufficient_quota"
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: (_ for _ in ()).throw(Quota({})))
    monkeypatch.setattr(access, "_calm_at", 0.0)
    with pytest.raises(Quota):
        access.openai_response(5, model="gpt-6-luna", input="hi")


def test_calls_under_way_count_against_a_pass_so_concurrency_cannot_overspend_it(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "db_path", lambda: tmp_path / "access.db")
    pid = access.create_pass("tester", 0.001)   # under one call's estimate: a second must wait
    gate, made = threading.Event(), []

    def create(timeout, **kw):
        made.append(kw["input"])
        if kw["input"] == "first":
            gate.wait()
        # $0.06 at gpt-4o-mini: the first call alone takes the pass past its cap
        return {"usage": {"input_tokens": 400_000, "output_tokens": 0}}

    monkeypatch.setattr(access, "_create", create)
    refused = []

    def call(text):
        try:
            with access.spending(pid):
                access.openai_response(5, model="gpt-4o-mini", input=text)
        except access.Refused:
            refused.append(text)

    first = threading.Thread(target=call, args=("first",), daemon=True)
    first.start()
    while not made:
        time.sleep(0.001)
    second = threading.Thread(target=call, args=("second",), daemon=True)
    second.start()
    time.sleep(0.05)
    try:
        assert made == ["first"]              # the second waits for the first to be charged
    finally:
        gate.set()
    first.join(), second.join()
    assert made == ["first"] and refused == ["second"]
    assert access.get_pass(pid)["spent_usd"] == pytest.approx(0.06)


def test_one_429_pauses_every_call_once_and_a_call_is_tried_a_bounded_number_of_times(monkeypatch):
    monkeypatch.setattr(access, "_calm_at", 0.0)
    paused, seen, lock = [], [], threading.Lock()
    real_pause = access.pause
    monkeypatch.setattr(access, "pause", lambda s: (real_pause(s), paused.append(s)))

    def create(timeout, **kw):
        with lock:
            seen.append((kw["input"], time.monotonic()))
            first = len(seen) == 1
        if first:
            raise RateLimited({"retry-after-ms": "300"})
        return {"usage": USAGE}

    monkeypatch.setattr(access, "_create", create)
    first = threading.Thread(target=access.openai_response, args=(5,), kwargs=dict(model="gpt-6-luna", input="a"))
    first.start()
    while not paused:
        time.sleep(0.001)
    t0 = time.monotonic()
    others = [threading.Thread(target=access.openai_response, args=(5,), kwargs=dict(model="gpt-6-luna", input=f"b{i}"))
              for i in range(3)]
    for t in [*others]:
        t.start()
    for t in [first, *others]:
        t.join()
    assert len(paused) == 1                                     # one 429, one pause
    assert all(at - t0 >= 0.25 for q, at in seen[1:])          # started during it: waited it out
    assert sorted(q for q, _ in seen) == ["a", "a", "b0", "b1", "b2"]

    tries = []
    monkeypatch.setattr(access, "pause", lambda s: None)
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: tries.append(1) or (_ for _ in ()).throw(RateLimited({})))
    with pytest.raises(RateLimited):
        access.openai_response(5, model="gpt-6-luna", input="hi")
    assert len(tries) == access.RATE_LIMIT_RETRIES + 1


def test_a_pass_at_its_cap_waits_in_the_queue_not_on_a_shared_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "db_path", lambda: tmp_path / "access.db")
    pid = access.create_pass("tester", 0.001)   # one call under way takes it to its cap
    gate, made = threading.Event(), []

    def create(timeout, **kw):
        made.append(kw["input"])
        if kw["input"] == "first":
            gate.wait()
        return {"usage": {"input_tokens": 400_000, "output_tokens": 0}}

    monkeypatch.setattr(access, "_create", create)
    ask = lambda text: access.openai_response(5, model="gpt-4o-mini", input=text)
    d = dispatch.Dispatcher(3)
    with access.spending(pid):   # all at once: no worker may take a second before the first has reserved
        capped = [d.submit("capped", ask, text) for text in ("first", "second", "third")]
    other = d.submit("other", lambda: "answered")
    try:
        assert other.result(timeout=2) == "answered"   # no free worker was parked on the capped pass
        while not made:
            time.sleep(0.001)
        time.sleep(0.05)
        assert made == ["first"] and not any(f.done() for f in capped)
    finally:
        gate.set()
    capped[0].result(timeout=2)
    for f in capped[1:]:
        with pytest.raises(access.Refused):
            f.result(timeout=2)
    assert made == ["first"] and not access._starting
