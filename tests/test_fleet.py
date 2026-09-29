"""The investigation fleet (fleet.py, verify.py, api/fleet.py), offline. One fake OpenAI stands in at
access._create, so every call goes through the real metering, purse and pass: its answers depend only
on what it is handed to read, so every cause is planted and each agent must find it. No network."""
import json
import re
import threading
import time
from types import SimpleNamespace

import pytest

import access
import fleet
import reports
import verify
import why
from providers import live
from schemas import (Answer, Attribute, AttributeObservation, AttributeScore, Challenge, CompanyProfile, Evidence,
                     FleetTask, Investigation, Probe, Run, WhyArm, WhyRate, WhyVerdict, WinBackAction)

ABOUT = "https://acme.com/about"
NEWS = "https://news.example.com/acme"
BLOG = "https://blog.example.com/acme"
PAGES = {ABOUT: "Acme builds widgets for small shops.",
         NEWS: "Acme carries heavy debt after the merger.",
         BLOG: "Acme is a big company."}
REWRITE = "Acme ships every order in one day."
FAST = Attribute(id="fast", label="Fast shipping", intended_weight=1.0, claim_quotes=["Acme ships in a day."],
                 claim_evidence_ids=["e1"])
DEBT = Attribute(id="emergent_debt", label="Heavy debt", discovered=True)
BIG = Attribute(id="emergent_big", label="Big company", discovered=True)
Q = {"np-1": "What is Acme?", "np-2": "Would you recommend Acme?", "np-3": "What is Acme best known for?"}
RESOLVED = live.Resolved("gpt-6-luna", live.SEARCH_TOOL, "gpt-6-luna", None)
USAGE = {"input_tokens": 1000, "output_tokens": 100}


def world_run(name="Acme", run_id="aaaaaa0001") -> Run:
    def score(a, zone, owner, n=3):
        return AttributeScore(attribute_id=a.id, label=a.label, discovered=a.discovered,
                              intended_weight=a.intended_weight, zone=zone, owner=owner, n=n)
    return Run(
        id=run_id, mode="live_api",
        profile=CompanyProfile(name=name, domain="acme.com", evidence=[
            Evidence(id="e1", url=ABOUT, excerpt="Acme ships in a day.", source_type="page_fetch")]),
        attributes=[FAST, DEBT, BIG],
        probes=[Probe(id=pid, topic_id="perception", text=t.replace("Acme", name), kind="named", phase="baseline",
                      purpose="brand") for pid, t in Q.items()],
        answers=[Answer(probe_id=pid, text="x", provenance="live_api", status="ok") for pid in Q],
        observations={"np-1": [AttributeObservation(attribute_id="emergent_debt", quote="debt", polarity="negative")],
                      "np-2": [AttributeObservation(attribute_id="emergent_big", quote="big", polarity="positive"),
                               AttributeObservation(attribute_id="emergent_debt", quote="debt", polarity="negative")]},
        attribute_scores=[score(FAST, "unstated_intent", "messaging_gap"), score(DEBT, "imposed", "imposed_identity"),
                          score(BIG, "imposed", "imposed_identity")],
        win_back=[WinBackAction(attribute_id="fast", label=FAST.label, zone="unstated_intent", page_url=ABOUT,
                                rewrite=REWRITE, provenance="live_api")],
        status="complete")


def message(text, usage=USAGE):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": usage}


def answer_to(reading: str, question: str = "") -> str:
    """The model under test: it says what it read, and nothing it did not."""
    parts = ["Acme makes widgets."]
    if "heavy debt" in reading:
        parts.append("Acme has heavy debt (CLAIM:emergent_debt:negative).")
    if REWRITE in reading:
        parts.append("Acme ships every order in one day (CLAIM:fast:positive).")
    if "big company" in reading:
        parts.append("It is a big company (CLAIM:emergent_big:positive).")
    return " ".join(parts)


class Fake:
    """access._create's stand-in. `coordinator` is a list of turns (lists of tool calls); `hooks` let a
    test slow, fail or synchronise the live asks of one question."""

    def __init__(self, coordinator=None, pages=None, usage=USAGE, live_says=None, hooks=None, writer=None):
        self.turns = list(coordinator or [])
        self.pages = pages or PAGES
        self.usage, self.live_says, self.hooks = usage, live_says or {}, hooks or {}
        self.writer = writer
        self.calls, self.lock = [], threading.Lock()

    def __call__(self, timeout, **kw):
        kind = self.kind(kw)
        with self.lock:
            self.calls.append((kind, access.SPENDER.get(), kw))
        if kind == "coordinator":
            with self.lock:
                turn = self.turns.pop(0) if self.turns else [("finish", {"reason": "Nothing else is worth it."})]
            return {"output": [{"type": "function_call", "name": n, "arguments": json.dumps(a)} for n, a in turn],
                    "usage": self.usage}
        if kind == "writer":
            items = re.findall(r"^(\d+)\. ", kw["input"], re.M)
            lines = (self.writer(items) if self.writer else
                     [{"rank": int(r), "text": "Lead acme.com/about with the rewrite."} for r in items])
            return message(json.dumps({"lines": lines}), self.usage)
        if kind == "judge":
            return SimpleNamespace(output_text=judge(kw["input"]), output=[], usage=self.usage)
        if kind == "off":
            return message("Acme makes widgets.", self.usage)
        question = next(i["content"] for i in kw["input"] if i.get("role") == "user")
        if kind == "live":
            if hook := self.hooks.get(question):
                hook()
            results = [{"url": u, "title": "t", "text": t} for u, t in self.pages.items()]
            text = self.live_says.get(question) or answer_to(" ".join(self.pages.values()), question)
            return {"output": [{"type": "web_search_call", "action": {"type": "search", "query": question},
                                "results": results}, message(text)["output"][0]], "usage": self.usage}
        read = "\n".join(i["output"] for i in kw["input"] if i.get("type") == "function_call_output")
        return message(answer_to(read, question), self.usage)

    @staticmethod
    def kind(kw):
        tools = kw.get("tools") or []
        if any(t.get("name") == "dispatch" for t in tools):
            return "coordinator"
        if isinstance(kw.get("input"), str):
            return "writer" if kw["input"].startswith("You write the action plan") else "judge"
        if kw.get("include"):
            return "live"
        return "replay" if tools else "off"

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


def judge(prompt: str) -> str:
    """The evaluator: an observation for the claim under test wherever the answer carries its marker."""
    aid = re.search(r"^- (\S+): ", prompt, re.M).group(1)
    obs = [{"attribute_id": aid, "quote": m.group(0), "polarity": m.group(1)}
           for m in re.finditer(rf"\(CLAIM:{re.escape(aid)}:(\w+)\)", prompt)][:1]
    return json.dumps({"mentioned": True, "recommended": False, "negative_mention": False,
                       "competitor_recommendations": [], "evidence_quotes": [], "on_topic": True, "attributes": obs})


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Runs, investigations, fleets and the access database under tmp_path; a key that is never used."""
    for mod, attr, sub in ((reports, "DATA", ""), (reports, "RUNS", "runs"), (reports, "INVESTIGATIONS", "investigations"),
                           (reports, "FLEETS", "fleets")):
        monkeypatch.setattr(mod, attr, tmp_path / sub if sub else tmp_path)
    monkeypatch.setenv(access.KEY_ENV, "k")
    fleet.EventLog._next.clear()

    def install(fake):
        monkeypatch.setattr(access, "_create", fake)
        return fake
    return install


def execute(run, fake_or_none=None, **kw):
    log = fleet.EventLog(fleet.new_id())
    status = fleet.execute(run, log, RESOLVED, **kw)
    return status, log.read()


def of(events, kind, task=None):
    return [e for e in events if e.kind == kind and (task is None or e.task_id == task)]


def dispatch(aid, probe, term=None, reason="Worth it."):
    return ("dispatch", {"attribute_id": aid, "probe_id": probe, "term": term, "reason": reason})


# ---------------------------------------------------------------- the shortlist and the coordinator's bounds
def test_the_shortlist_is_claims_to_win_back_and_perceptions_ai_raised():
    got = {c["attribute_id"]: c for c in fleet.shortlist(world_run())}
    assert set(got) == {"fast", "emergent_debt", "emergent_big"}
    assert got["fast"]["kind"] == "claim" and got["fast"]["rewrite_page"] == ABOUT
    assert got["emergent_debt"]["negative"] == 2 and got["emergent_debt"]["pick"]
    assert not got["emergent_big"]["pick"]      # flattering: code's fallback never spends on it
    assert [c["attribute_id"] for c in fleet.shortlist(world_run())][:2] == ["fast", "emergent_debt"]
    # a claim gets a question where AI does not endorse it yet; a perception one where AI said it
    assert fleet.code_question(got["fast"], set()) == "np-1"
    assert fleet.code_question(got["emergent_debt"], set()) == "np-1"


def test_invalid_coordinator_calls_are_rejected_with_reasons_and_code_steps_in(world):
    fake = world(Fake(coordinator=[[dispatch("nope", "np-1"), dispatch("fast", "np-1", term="ships"),
                                    dispatch("fast", "np-9"), ("dispatch", {"attribute_id": "fast", "probe_id": "np-2"})],
                                   [dispatch("nope", "np-1")]]))    # the repair turn fails too
    status, events = execute(world_run())
    reasons = [e.data["reason"] for e in of(events, "rejected")]
    assert len(reasons) == 5
    assert reasons[0] == "not on the shortlist"
    assert "give no term" in reasons[1] and "not one of this claim's branded questions" in reasons[2]
    assert "reason" in reasons[3]
    # none usable: code dispatched its own picks, and says so
    tasks = [e.data["task"] for e in of(events, "dispatched")]
    assert {t["attribute_id"] for t in tasks} == {"fast", "emergent_debt"} and all(t["by"] == "code" for t in tasks)
    assert status == "complete" and of(events, "planned")


def test_a_failed_coordinator_call_falls_back_to_code(world):
    class Broken(Fake):
        def __call__(self, timeout, **kw):
            if self.kind(kw) == "coordinator":
                raise RuntimeError("boom")
            return super().__call__(timeout, **kw)
    world(Broken())
    status, events = execute(world_run())
    assert of(events, "turn")[0].data["by"] == "code"
    assert all(e.data["task"]["by"] == "code" for e in of(events, "dispatched"))
    assert status == "complete"


# ---------------------------------------------------------------- dispatch, verdicts, plan
def test_investigators_really_run_at_the_same_time(world):
    gate = threading.Barrier(3, timeout=10)
    first = {q: threading.Event() for q in Q.values()}

    def at_first_ask(q):
        def hook():
            if not first[q].is_set():
                first[q].set()
                gate.wait()   # opens only when three questions are being asked at once
        return hook
    world(Fake(coordinator=[[dispatch("fast", "np-2"), dispatch("emergent_debt", "np-1", term="debt"),
                             dispatch("emergent_big", "np-3", term="big")]],
               hooks={q: at_first_ask(q) for q in first}))
    status, events = execute(world_run(), lanes=3)
    assert status == "complete"   # a barrier of 3 only opens when 3 investigators are asking at once
    assert len(of(events, "finished")) == 3


def test_a_copy_fix_and_a_cause_are_found_and_ranked(world):
    fake = world(Fake(coordinator=[[dispatch("fast", "np-2", reason="Wanted, and not said yet."),
                                    dispatch("emergent_debt", "np-1", term="debt", reason="Harms it.")],
                                   [("finish", {"reason": "Enough."})]]))
    status, events = execute(world_run())
    plan = fleet.plan_of(events)
    fix = next(i for i in plan.items if i.attribute_id == "fast")
    assert fix.fix == "copy" and fix.page_url == ABOUT and fix.rewrite == REWRITE and fix.hypothetical
    assert fix.k > fix.base_k and fix.interval[0] > 0 and fix.rank == 1
    cause = next(i for i in plan.items if i.attribute_id == "emergent_debt")
    assert cause.fix == "source" and cause.sources == [NEWS]
    assert "None of them is your page to edit" in cause.text    # news.example.com is not Acme's
    assert plan.written_by == "gpt-6-luna" and fix.text == "Lead acme.com/about with the rewrite."
    assert status == "complete"
    # the writer and the coordinator were each paid for through the same metered path; the writer is
    # handed only the tested fixes, never a source to "remove" or an undecided claim to act on
    [(_, _, sent)] = fake.of("writer")
    assert "[copy]" in sent["input"] and "[source]" not in sent["input"] and fake.of("coordinator")


def test_a_challenged_task_is_redispatched_with_one_change(world):
    # on np-1 the live answers say the claim but the replays never do: not reproducible
    fake = world(Fake(coordinator=[[dispatch("fast", "np-1")],
                                   [("redispatch", {"task_id": "t1", "probe_id": "np-2", "reason": "Another question."})]],
                      live_says={Q["np-1"]: "Acme ships every order in one day (CLAIM:fast:positive)."}))
    status, events = execute(world_run())
    challenge = of(events, "challenged", "t1")[0].data["challenge"]
    assert challenge["kind"] == "not_reproducible" and challenge["ask"] == "other_question"
    again = of(events, "dispatched", "t2")[0].data["task"]
    assert again["parent"] == "t1" and again["try_no"] == 2 and again["probe_id"] == "np-2"
    plan = fleet.plan_of(events)
    assert [i.fix for i in plan.items if i.attribute_id == "fast"] == ["copy"]
    assert next(i for i in plan.items if i.attribute_id == "fast").task_id == "t2"
    # a re-dispatch that changes nothing is refused
    st = fleet.State(world_run(), access.Purse(3))
    st.tasks["t1"] = FleetTask(id="t1", attribute_id="fast", claim="Fast", probe_id="np-2", question="q",
                               reason="r", budget_usd=0.6)
    st.results["t1"] = Investigation(id="i1", run_id="r", company="Acme", question="q", attribute_id="fast",
                                     claim="Fast", model="m", judge="j", budget_usd=0.6)
    c = fleet.Coordinator(st, fleet.EventLog(fleet.new_id()), "m")
    assert "change one thing" in c.apply("redispatch", {"task_id": "t1", "reason": "again"}, "model")


def test_code_follows_the_critics_ask_when_the_coordinator_stops_answering(world):
    world(Fake(coordinator=[[dispatch("fast", "np-1")], [("accept", {"task_id": "t9"})], [("accept", {"task_id": "t9"})]],
               live_says={Q["np-1"]: "Acme ships every order in one day (CLAIM:fast:positive)."}))
    status, events = execute(world_run())
    again = of(events, "dispatched", "t2")[0].data["task"]
    assert again["by"] == "code" and again["parent"] == "t1" and again["probe_id"] != "np-1"


def test_one_investigator_failing_never_stalls_the_rest(world):
    def fail():
        raise RuntimeError("upstream fell over")
    world(Fake(coordinator=[[dispatch("fast", "np-2"), dispatch("emergent_debt", "np-3", term="debt"),
                             dispatch("emergent_big", "np-1", term="big")]],
               hooks={Q["np-3"]: fail}, writer=lambda ranks: []))
    status, events = execute(world_run())
    assert status == "complete"
    assert [e.task_id for e in of(events, "failed")] == ["t2"]
    assert {e.task_id for e in of(events, "finished")} == {"t1", "t3"}
    item = next(i for i in fleet.plan_of(events).items if i.attribute_id == "emergent_debt")
    assert item.fix == "thin" and "RuntimeError" in item.text


def test_a_task_past_its_deadline_is_cancelled_and_keeps_what_it_found(world):
    world(Fake(coordinator=[[dispatch("fast", "np-2"), dispatch("emergent_debt", "np-1", term="debt")]],
               hooks={Q["np-2"]: lambda: time.sleep(0.6)}))
    status, events = execute(world_run(), task_deadline=0.3)
    assert [e.task_id for e in of(events, "cancelling")] == ["t1"]
    verdicts = of(events, "finished", "t1")[0].data["verdicts"]
    assert verdicts[-1]["kind"] == "cancelled" and "deadline" in verdicts[-1]["text"]
    assert of(events, "finished", "t2")[0].data["status"] == "complete"   # the other ran to its end
    assert status == "complete" and of(events, "planned")


def test_the_purse_stops_every_agent_and_still_leaves_the_plan_written(world, monkeypatch):
    # each task alone is affordable, both together are not: the shared purse, not a task's cap, stops
    # the second; the first, a copy fix, is what the writer's reserve is kept for
    monkeypatch.setenv(why.BUDGET_ENV, "0.30")
    fake = world(Fake(coordinator=[[dispatch("fast", "np-2"), dispatch("emergent_debt", "np-1", term="debt")]],
                      usage={"input_tokens": 20_000, "output_tokens": 4_000}))   # $0.004 a call
    status, events = execute(world_run(), budget_usd=0.45, lanes=1)
    stopped = [v for e in of(events, "finished") for v in e.data["verdicts"] if v["kind"] == "budget"]
    assert stopped and "the fleet's $0.45 budget" in stopped[0]["text"]
    assert of(events, "done")[0].data["spent_usd"] <= 0.45 + 0.02     # the limit, plus what an estimate misses
    assert fake.of("writer") and fleet.plan_of(events).written_by == "gpt-6-luna"   # the reserve paid for it


def test_a_capped_pass_stops_the_fleet_and_the_plan_falls_back_to_the_template(world):
    pid = access.create_pass("tester", 0.0)
    world(Fake())
    with access.spending(pid):
        status, events = execute(world_run())
    assert status == "stopped" and of(events, "stopped")
    plan = fleet.plan_of(events)
    assert plan.written_by == "template"
    assert [i.fix for i in plan.items] == ["untested"]                # nothing ran; the run's rewrite stays, untested
    # a writer the pass refuses leaves every line the template's
    fix = fleet.PlanItem(rank=1, attribute_id="fast", claim="Fast", fix="copy", text="Lead acme.com/about.")
    worded = fleet.ActionPlan(items=[fix])
    with access.spending(pid):
        fleet.write(worded, world_run(), "gpt-6-luna")
    assert worded.written_by == "template" and "writer's call failed" in worded.notes[0]


# ---------------------------------------------------------------- passes, provenance, the log
def test_two_fleets_under_two_passes_never_cross(world):
    fake = world(Fake())
    runs = {"p": world_run("Acme", "aaaaaa0001"), "q": world_run("Bolt", "bbbbbb0002")}
    passes = {k: access.create_pass(k, 10.0) for k in runs}

    def go(k):
        with access.spending(passes[k]):
            fleet.execute(runs[k], fleet.EventLog(fleet.new_id()), RESOLVED, pass_id=passes[k])
    threads = [threading.Thread(target=go, args=(k,)) for k in runs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    for kind, spender, kw in fake.calls:
        text = json.dumps(kw.get("input"), default=str)
        assert ("Bolt" in text) == (spender == passes["q"]), (kind, spender)
    with access.db() as c:
        rows = dict(c.execute("SELECT pass_id, COUNT(*) FROM ledger GROUP BY pass_id").fetchall())
    assert rows[passes["p"]] + rows[passes["q"]] == len(fake.calls)
    assert all(access.owner("investigation", i.id) == passes["p" if i.company == "Acme" else "q"]
               for i in map(reports.load_investigation, [p.stem for p in reports.INVESTIGATIONS.glob("*.json")]))


def test_the_run_is_never_written_and_replays_never_score(world):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]]))
    run = world_run()
    reports.save_run(run)
    before = (reports.RUNS / f"{run.id}.json").read_bytes()
    execute(reports.load_run(run.id))
    assert (reports.RUNS / f"{run.id}.json").read_bytes() == before
    invs = reports.list_investigations(run.id)
    assert invs and all(i.provenance == "counterfactual_replay" and i.fleet_id for i in invs)
    assert fleet.plan_of(fleet.EventLog(invs[0].fleet_id).read()).provenance == "counterfactual_replay"


def test_the_log_is_ordered_and_reads_back_the_same(world):
    world(Fake(coordinator=[[dispatch("fast", "np-2"), dispatch("emergent_debt", "np-1", term="debt")]]))
    status, events = execute(world_run())
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[0].kind == "started" and events[-1].kind == "done" and events[-2].kind == "planned"
    for t in ("t1", "t2"):
        order = [e.kind for e in events if e.task_id == t]
        assert order[0] == "dispatched" and order[1] == "began"
        assert order.index("finished") > max(i for i, k in enumerate(order) if k in ("progress", "arm", "verdict"))
    log = fleet.EventLog(events[0].data["fleet_id"])
    assert log.read() == events and log.read(after=5) == events[5:]
    assert fleet.summary(events)["status"] == "complete" and fleet.summary(events)["planned"]


# ---------------------------------------------------------------- the critic
def inv_with(arms, verdicts, quotes=(), question="q"):
    return Investigation(id="i1", run_id="r", company="Acme", question=question, attribute_id="fast", claim="Fast",
                         model="m", judge="j", budget_usd=0.6, arms=arms, verdicts=verdicts, live_quotes=list(quotes))


TASK = FleetTask(id="t1", attribute_id="fast", claim="Fast shipping", probe_id="np-1", question="q", reason="r",
                 budget_usd=0.6)


def test_a_claim_already_said_on_its_question_is_at_a_ceiling():
    inv = inv_with([WhyArm(id="base", kind="base", label="b", k=35, n=36, decided="base"),
                    WhyArm(id="a2", kind="edit", label="e", k=35, n=36, decided="undecided")],
                   [WhyVerdict(kind="undecided", text="Your copy may move it.")])
    [c] = fleet.critic(inv, TASK, FAST, [])
    assert (c.kind, c.ask) == ("ceiling", "other_question") and "35 of 36" in c.text


def test_budget_with_an_experiment_still_open_asks_for_more_budget_and_full_asks_accept():
    stopped = inv_with([WhyArm(id="base", kind="base", label="b", k=3, n=18, decided="base"),
                        WhyArm(id="a1", kind="edit", label="e", k=6, n=18, decided="undecided")],
                       [WhyVerdict(kind="budget", text="Stopped.")])
    assert [(c.kind, c.ask) for c in fleet.critic(stopped, TASK, FAST, [])] == [("thin", "more_budget")]
    spent = inv_with([WhyArm(id="base", kind="base", label="b", k=3, n=36, decided="base"),
                      WhyArm(id="a1", kind="edit", label="e", k=8, n=36, decided="undecided")],
                     [WhyVerdict(kind="undecided", text="Undecided.")])
    assert [(c.kind, c.ask) for c in fleet.critic(spent, TASK, FAST, [])] == [("thin", "accept")]


def test_quotes_that_share_no_word_with_the_claim_are_flagged():
    ai = Attribute(id="innovation", label="Leads with scientific innovation and technology")
    inv = inv_with([WhyArm(id="base", kind="base", label="b", k=2, n=18, decided="base")],
                   [WhyVerdict(kind="copy_fix", text="Fix.", fix="copy")],
                   quotes=["the company forecast full-year 2026 revenue"])
    kinds = [c.kind for c in fleet.critic(inv, TASK, ai, [])]
    assert kinds == ["off_claim"]
    on = inv_with(inv.arms, inv.verdicts, quotes=["a leader in scientific innovation"])
    assert fleet.critic(on, TASK, ai, []) == []


def test_a_perception_never_said_on_its_question_is_a_floor():
    # live Amgen, 28 Sep 2026: "falling sales" was said in 0 of 3 answers to "What has changed about Amgen?"
    inv = inv_with([WhyArm(id="base", kind="base", label="b", k=0, n=18, decided="base")],
                   [WhyVerdict(kind="not_said", text="AI does not say it for this question.")])
    inv.live = WhyRate(k=0, n=3)
    [c] = fleet.critic(inv, TASK, DEBT, [])
    assert (c.kind, c.ask) == ("floor", "other_question") and "0 of 3" in c.text


def test_a_turn_whose_every_call_was_refused_gets_one_repair_turn(world):
    # live Amgen, 28 Sep 2026: the coordinator dispatched a claim already dispatched, and the fleet ended
    fake = world(Fake(coordinator=[[dispatch("nope", "np-1")], [dispatch("fast", "np-2", reason="Fixed it.")]]))
    status, events = execute(world_run())
    turns = [e.data for e in of(events, "turn")]
    assert turns[0]["repair"] is False and turns[1]["repair"] is True
    [task] = [e.data["task"] for e in of(events, "dispatched")]
    assert task["by"] == "model" and task["reason"] == "Fixed it."   # the model's own fix, not code's fallback
    assert "not on the shortlist" in json.dumps(fake.of("coordinator")[1][2]["input"])   # it was told why


def test_verdicts_that_disagree_across_questions_are_contradictions():
    moved = inv_with([], [WhyVerdict(kind="copy_fix", text="Fix.", fix="copy")], question="Q one")
    still = inv_with([], [WhyVerdict(kind="not_movable", text="No.", fix="none")], question="Q two")
    other = TASK.model_copy(update={"id": "t2"})
    [c] = fleet.critic(still, other, FAST, [(TASK, moved)])
    assert c.kind == "contradicts" and c.evidence == ["t1"] and "“Q one” and not on “Q two”" in c.text


# ---------------------------------------------------------------- the polarity fix (why.Judge)
class Labels:
    model = "judge"

    def __init__(self, polarity):
        self.polarity = polarity

    def label(self, probe, answer, attributes, profile):
        return {"attributes": [{"attribute_id": attributes[0].id, "quote": "ships fast", "polarity": self.polarity}],
                "mentioned": True, "recommended": False, "negative_mention": False,
                "competitor_recommendations": [], "evidence_quotes": [], "on_topic": True}


def test_a_claim_counts_only_endorsements_as_the_report_does():
    neutral = why.Judge(FAST, CompanyProfile(name="Acme", domain="acme.com"), "q", evaluator=Labels("neutral"), endorse=True)
    assert neutral("Acme ships fast, some say.") == (False, None)
    positive = why.Judge(FAST, CompanyProfile(name="Acme", domain="acme.com"), "q", evaluator=Labels("positive"), endorse=True)
    assert positive("Acme ships fast.") == (True, "ships fast")
    assert "endorsements only" in positive.name
    # a perception AI raises counts any mention, as drift.py keys it on mentions
    mention = why.Judge(DEBT, CompanyProfile(name="Acme", domain="acme.com"), "q", evaluator=Labels("negative"))
    assert mention("Acme ships fast.") == (True, "ships fast")


def test_an_investigation_records_what_it_counted(world):
    world(Fake())
    run = world_run()
    lab = why.Lab("gpt-6-luna", live.SEARCH_TOOL)
    from agents.evaluator_model import ModelEvaluator
    claim = why.start(run, "fast", Q["np-2"], lab=lab, evaluator=ModelEvaluator(model="gpt-6-luna", transport=lab.judge_transport))
    assert claim.counts == "endorsements" and "endorsements only" in claim.judge
    perception = why.start(run, "emergent_debt", Q["np-1"], term="debt", lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL))
    assert perception.counts == "mentions" and "any mention" in perception.judge


# ---------------------------------------------------------------- the writer's checks
def test_the_writer_may_reword_but_never_add_a_number_or_a_page():
    old = "With your rewrite leading acme.com/about, AI says it in 14 of 18 answers against 6 of 18."
    assert fleet.acceptable("Lead acme.com/about with the rewrite: 14 of 18 answers said it, from 6 of 18.", old)
    assert not fleet.acceptable("Lead acme.com/about with the rewrite: 90% of answers will say it.", old)
    assert not fleet.acceptable("Put it on acme.com/shipping instead: 14 of 18.", old)
    assert not fleet.acceptable("A seamless rewrite of acme.com/about.", old)
    assert not fleet.acceptable("Rewrite the page: 14 of 18 answers said it.", old)   # dropped which page


def test_a_writer_line_that_adds_a_number_keeps_the_template(world):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]],
               writer=lambda ranks: [{"rank": int(r), "text": "Guaranteed 99% lift."} for r in ranks]))
    _, events = execute(world_run())
    plan = fleet.plan_of(events)
    assert plan.written_by == "template" and "Guaranteed" not in plan.items[0].text


# ---------------------------------------------------------------- the verifier
def verification(live_kn, pred=(14, 18), base=(6, 18), control=(0, 0)):
    return verify.Verification(fleet_id="f", rank=1, attribute_id="a", claim="c", page_url=ABOUT, copy_text="x",
                               question="q", investigation_id="i", budget_usd=0.75, live=WhyRate(k=live_kn[0], n=live_kn[1]),
                               predicted=WhyRate(k=pred[0], n=pred[1]), base=WhyRate(k=base[0], n=base[1]),
                               control=WhyRate(k=control[0], n=control[1]))


def test_the_verifier_concludes_from_where_the_live_interval_falls():
    assert verify.conclude(verification((13, 16)))[0] == "confirmed"
    assert verify.conclude(verification((5, 16)))[0] == "not_confirmed"
    assert verify.conclude(verification((8, 16), pred=(12, 18)))[0] == "undecided"
    moved = verify.conclude(verification((13, 16), control=(16, 16)))
    assert moved[0] == "model_moved" and "model itself changed" in moved[1]


def finished_fleet(world, monkeypatch, pages=None):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]], pages=pages))
    run = world_run()
    reports.save_run(run)
    status, events = execute(run)
    return events[0].data["fleet_id"], fleet.plan_of(events)


def test_an_unpublished_fix_is_checked_for_free(world, monkeypatch):
    fid, plan = finished_fleet(world, monkeypatch)
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", "<p>" + "Acme builds widgets. " * 20 + "</p>"))
    before = len(access._create.calls)
    v = verify.verify(fid, 1, resolve=lambda: pytest.fail("no model is needed"))
    assert v.verdict == "not_published" and v.page_has_copy is False and v.spent_usd == 0
    assert len(access._create.calls) == before


def test_a_live_fix_ai_now_reads_is_confirmed(world, monkeypatch):
    fid, plan = finished_fleet(world, monkeypatch)
    live_page = {**PAGES, ABOUT: REWRITE + " " + PAGES[ABOUT]}
    access._create.pages = live_page    # the fix is published and crawled: search now returns it
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", "<p>" + (REWRITE + " ") * 10 + "</p>"))
    v = verify.verify(fid, 1, resolve=lambda: RESOLVED)
    assert v.page_has_copy and v.read_by_ai.k == v.read_by_ai.n == 16
    assert (v.live.k, v.live.n) == (16, 16) and v.live_provenance == "live_api"
    assert v.control.n == verify.CONTROL_ASKS and v.control.k == 0          # the old reading list: unchanged
    assert v.verdict == "confirmed" and 0 < v.spent_usd <= v.budget_usd


def test_a_published_fix_search_has_not_read_is_not_crawled_yet(world, monkeypatch):
    fid, plan = finished_fleet(world, monkeypatch)
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", "<p>" + (REWRITE + " ") * 10 + "</p>"))
    v = verify.verify(fid, 1, resolve=lambda: RESOLVED)
    assert v.verdict == "not_crawled" and v.read_by_ai.n == verify.LOOKS[0] and v.read_by_ai.k == 0


# ---------------------------------------------------------------- over HTTP
@pytest.fixture
def client(world, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setattr(live, "preflight", lambda *a, **k: RESOLVED)
    return TestClient(main.app)


def sse_events(text):
    return [json.loads(d) for e, d in re.findall(r"event: (\w+)\ndata: (.*)\n", text) if e == "fleet"]


def test_a_fleet_starts_streams_and_ends_over_http(world, client):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]]))
    run = world_run()
    reports.save_run(run)
    fid = client.post(f"/api/runs/{run.id}/fleet").json()["id"]
    body = client.get(f"/api/fleets/{fid}/stream").text
    kinds = [e["kind"] for e in sse_events(body)]
    assert kinds[0] == "started" and kinds[-1] == "done" and "planned" in kinds and "event: end" in body
    listed = client.get(f"/api/runs/{run.id}/fleets").json()
    assert listed["fleets"][0]["id"] == fid and listed["fleets"][0]["planned"] and listed["estimate"]["picks"] == 2
    # a reconnect resumes after the last number it saw
    resumed = sse_events(client.get(f"/api/fleets/{fid}/stream", params={"after": 3}).text)
    assert resumed[0]["seq"] == 4


def test_a_sample_run_is_refused_before_anything_is_spent(client):
    run = world_run().model_copy(update={"mode": "demo_replay"})
    reports.save_run(run)
    r = client.post(f"/api/runs/{run.id}/fleet")
    assert r.status_code == 400 and "Only a live run" in r.json()["detail"]


def test_a_recheck_logged_later_keeps_what_the_fleet_spent(world):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]]))
    status, events = execute(world_run())
    spent = fleet.summary(events)["spent_usd"]
    log = fleet.EventLog(events[0].data["fleet_id"])
    log.append("verified", rank=1)
    assert spent > 0 and fleet.summary(log.read())["spent_usd"] == spent


def test_a_second_start_during_the_first_ones_preflight_is_refused(world, client, monkeypatch):
    world(Fake(coordinator=[[dispatch("fast", "np-2")]]))
    run = world_run()
    reports.save_run(run)
    seen = []

    def preflight(*a, **k):
        if not seen:
            seen.append(client.post(f"/api/runs/{run.id}/fleet").status_code)
        return RESOLVED
    monkeypatch.setattr(live, "preflight", preflight)
    fid = client.post(f"/api/runs/{run.id}/fleet").json()["id"]
    client.get(f"/api/fleets/{fid}/stream")
    assert seen == [409]
