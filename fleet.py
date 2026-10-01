"""The investigation fleet: after a live run, several agents work out why AI says what it says about a
company and what would change it, at the same time (WEB.md, "Investigation fleet").

  coordinator    a model choosing from a shortlist code builds: which claims, with which branded
                 question; then, as each verdict lands, accept it, re-dispatch it once, or stop.
                 Every call it makes is checked here; when a turn fails, code's own ranking decides.
  investigators  why.start, one per claim and question, FLEET_CONCURRENCY at a time.
  critic         code rules on each finished investigation: thin, at a ceiling, not reproducible,
                 quoting off the claim, contradicting another question's verdict.
  planner        code ranks the accepted verdicts and copies every number from an arm; one model
                 call words the lines, and a line is kept only if it adds no number and no page.
  verifier       verify.py, later, once a fix is live.

Agents never call each other. They exchange typed FleetEvents on one append-only log (EventLog), which
the loop's thread alone writes while the fleet runs and which the UI streams. Every model call of every
agent draws on one access.Purse (FLEET_BUDGET_USD) inside the pass that started the fleet. The run is
read and never written; investigations are counterfactual replays and never reach a score.
"""
import json
import queue
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from datetime import datetime
from typing import Callable, Optional

import access
import config
import reports
import why
from agents import ana, evaluation
from agents.evaluator_model import json_object
from agents.onboarding_model import MARKETING
from providers import live
from scoring import domain_matches
from schemas import (ActionPlan, Challenge, FleetEvent, FleetTask, Investigation, PlanItem, Run)

BUDGET_ENV, DEFAULT_BUDGET = "FLEET_BUDGET_USD", 3.00
CONCURRENCY_ENV, DEFAULT_CONCURRENCY = "FLEET_CONCURRENCY", 3
IN_FLIGHT = 18              # calls in flight across the fleet: the pilot peaked here with no 429 (2026-09-28)
MAX_TASKS, MAX_TRIES, MAX_TURNS = 8, 2, 12
FIRST_PICKS = 5             # what code dispatches when the coordinator cannot
WRITER_RESERVE = 0.05       # held back from the purse until the plan is written
TASK_DEADLINE_S = live.LIMITS["investigation_deadline_s"]
FLEET_DEADLINE_S = 1200
CEILING = 0.9               # a base replay rate this high leaves a fix no room to show a rise
MEAN_COST, MEAN_MINUTES = 0.36, 4.8   # one investigation in the pilot (2026-09-28): for the estimate
MAX_TERM = 40               # api/why.MAX_TERM: the same limit a user's own word has


def budget() -> float:
    """FLEET_BUDGET_USD, the most one fleet may spend, every agent together."""
    return config.setting(BUDGET_ENV, DEFAULT_BUDGET, 0.10, float)


def concurrency() -> int:
    return min(6, config.setting(CONCURRENCY_ENV, DEFAULT_CONCURRENCY, 1))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- the event log
class EventLog:
    """DATA_DIR/fleets/<fleet id>.jsonl: one FleetEvent a line, numbered from 1. While the fleet runs its
    loop's thread is the only writer; a verifier appends once the fleet is done, under the same lock."""
    _locks: dict[str, threading.Lock] = {}
    _next: dict[str, int] = {}
    _guard = threading.Lock()

    def __init__(self, fleet_id: str, spent: Callable[[], float] = lambda: 0.0):
        if not reports.ID.fullmatch(fleet_id):
            raise ValueError("bad fleet id")
        self.id, self.spent = fleet_id, spent
        self.path = reports.FLEETS / f"{fleet_id}.jsonl"
        with EventLog._guard:
            self.lock = EventLog._locks.setdefault(str(self.path), threading.Lock())

    def append(self, kind: str, task_id: Optional[str] = None, **data) -> FleetEvent:
        with self.lock:
            key = str(self.path)
            if key not in EventLog._next:
                EventLog._next[key] = len(self.read()) + 1
            event = FleetEvent(seq=EventLog._next[key], at=now(), kind=kind, task_id=task_id, data=data,
                               spent_usd=round(self.spent(), 4))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(event.model_dump_json() + "\n")
            EventLog._next[key] += 1
        return event

    def read(self, after: int = 0) -> list[FleetEvent]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        return [FleetEvent.model_validate_json(line) for line in lines[after:] if line.strip()]


def summary(events: list[FleetEvent]) -> dict:
    """A fleet as its list shows it, read off its log."""
    start = next((e for e in events if e.kind == "started"), None)
    done = next((e for e in events if e.kind == "done"), None)
    return dict(id=start.data.get("fleet_id") if start else None, run_id=start.data.get("run_id") if start else None,
                created_at=start.at if start else None, status=done.data.get("status") if done else "running",
                spent_usd=max((e.spent_usd for e in events), default=0.0), wall_s=done.data.get("wall_s") if done else None,
                tasks=sum(e.kind == "dispatched" for e in events), planned=any(e.kind == "planned" for e in events))


def plan_of(events: list[FleetEvent]) -> Optional[ActionPlan]:
    planned = [e for e in events if e.kind == "planned"]
    return ActionPlan.model_validate(planned[-1].data["plan"]) if planned else None


def list_fleets(run_id: str) -> list[dict]:
    """A run's fleets, newest first."""
    out = []
    for path in reports.FLEETS.glob("*.jsonl"):
        try:
            first = FleetEvent.model_validate_json(path.open().readline())
        except ValueError:
            continue
        if first.kind == "started" and first.data.get("run_id") == run_id:
            out.append(summary(EventLog(path.stem).read()))
    return sorted(out, key=lambda s: s["created_at"] or "", reverse=True)


# ---------------------------------------------------------------- the shortlist (code)
ZONE_WORDS = {"lost_claim": "its site says it and AI does not repeat it",
              "unstated_intent": "it wants to be known for it and its site barely says it",
              "contested": "AI says the opposite"}
PRIORITY = {"contested": 0, "lost_claim": 1, "unstated_intent": 1}


def shortlist(run: Run) -> list[dict]:
    """The claims the coordinator may choose from, in code's own order (its fallback's picks first).

    A claim of the company's that AI does not endorse (to win back, to amplify, contested), and a
    perception AI raised on its own in at least one brand answer. Each carries the run's branded
    questions that do not name it, and what each answer said about it."""
    attrs = {a.id: a for a in run.attributes}
    answered = {a.probe_id for a in run.answers if a.status == "ok"}
    named = [p for p in run.probes if p.kind == "named" and p.phase == "baseline" and p.id in answered]
    obs = run.observations or {}
    rewrites = {w.attribute_id: w for w in run.win_back}
    out = []
    for s in run.attribute_scores:
        a = attrs.get(s.attribute_id)
        if a is None or (not a.discovered and s.zone not in ZONE_WORDS):
            continue
        questions = []
        for p in named:
            if ana.attribute_leaks(p.text, [a]):
                continue
            o = next((o for o in obs.get(p.id, []) if o.attribute_id == a.id), None)
            questions.append(dict(probe_id=p.id, text=p.text, said=o.polarity if o else None,
                                  quote=o.quote if o else None))
        said = [q for q in questions if q["said"]]
        if not questions or (a.discovered and not said):
            continue
        negative = sum(q["said"] == "negative" for q in questions)
        endorsed = sum(q["said"] == "positive" for q in questions)
        w = rewrites.get(a.id)
        kind = "imposed" if a.discovered else "claim"
        out.append(dict(
            attribute_id=a.id, label=a.label, kind=kind, zone=s.zone, weight=a.intended_weight,
            n=s.n, mentioned=len(said), endorsed=endorsed, negative=negative,
            rewrite_page=w.page_url if w else None, questions=questions,
            # code's own ranking: claims by zone and weight, then perceptions AI raises to criticise
            pick=kind == "claim" or negative > 0,
            order=(PRIORITY.get(s.zone, 2) if kind == "claim" else 2 if negative else 3,
                   -(a.intended_weight or 0), -len(said))))
    return sorted(out, key=lambda c: c["order"])


def code_question(c: dict, used: set[str]) -> Optional[str]:
    """Code's own choice of question. A claim of the company's: one where AI does not endorse it yet,
    so a fix has room to show a rise. A perception AI raised: one where AI said it, so there is a cause
    to trace."""
    qs = [q for q in c["questions"] if q["probe_id"] not in used]
    pref = [q for q in qs if q["said"] != "positive"] if c["kind"] == "claim" else [q for q in qs if q["said"]]
    return (pref or qs)[0]["probe_id"] if (pref or qs) else None


# ---------------------------------------------------------------- the critic (code rules)
DECIDED = {"caused_by", "over_determined", "prior_belief", "not_in_reading", "not_said", "copy_fix",
           "authority_fix", "not_movable", "copy_lowers"}
MOVED = {"copy_fix", "authority_fix"}
UNMOVED = {"not_movable", "copy_lowers"}


def critic(inv: Investigation, task: FleetTask, attribute, others: list[tuple[FleetTask, Investigation]]) -> list[Challenge]:
    """What to object to in one finished investigation. Pure: the same investigation always draws the
    same challenges, and nothing here asks a model."""
    out = []
    kinds = {v.kind for v in inv.verdicts}
    base = inv.arms[0] if inv.arms else None
    if "not_reproducible" in kinds:
        out.append(Challenge(task_id=task.id, kind="not_reproducible", ask="other_question",
                             text="Replayed, what the model read did not give the live answers, so no experiment on "
                                  "it was fair. Another question may reproduce."))
    elif attribute.discovered and "not_said" in kinds:
        out.append(Challenge(task_id=task.id, kind="floor", ask="other_question",
                             text=f"AI did not say it on this question at all ({inv.live.k} of {inv.live.n} live answers), "
                                  "so there is nothing to trace here. Ask one where it says it."))
    elif not kinds & (DECIDED if attribute.discovered else MOVED | UNMOVED):
        if not attribute.discovered and base and base.n and base.k / base.n >= CEILING:
            out.append(Challenge(task_id=task.id, kind="ceiling", ask="other_question", evidence=[base.id],
                                 text=f"AI already says it in {base.k} of {base.n} replays of this question, so no "
                                      "copy can show a rise here. Ask a question where it does not say it yet."))
        elif kinds & {"budget", "cancelled"} and any(a.decided == "undecided" and a.n < why.LOOKS[-1] for a in inv.arms):
            open_ = [a.id for a in inv.arms if a.decided == "undecided"]
            out.append(Challenge(task_id=task.id, kind="thin", ask="more_budget", evidence=open_,
                                 text="It stopped before an experiment had used all its asks, so more budget could "
                                      "decide it."))
        else:
            out.append(Challenge(task_id=task.id, kind="thin", ask="accept",
                                 evidence=[a.id for a in inv.arms if a.decided == "undecided"],
                                 text="Every experiment used its asks and none decided: more of the same would not."))
    words = why.claim_words(attribute)
    if inv.live_quotes and not any(evaluation.content_words(q) & words for q in inv.live_quotes):
        out.append(Challenge(task_id=task.id, kind="off_claim", ask="accept",
                             text="None of the judge's quotes shares a word with the claim (“"
                                  + inv.live_quotes[0] + "”), so it may be reading more into the answers than they say."))
    mine = {v.kind for v in inv.verdicts if v.fix}
    for t, other in others:
        theirs = {v.kind for v in other.verdicts if v.fix}
        if t.attribute_id == task.attribute_id and ((mine & MOVED and theirs & UNMOVED) or (mine & UNMOVED and theirs & MOVED)):
            moved, still = (inv, other) if mine & MOVED else (other, inv)
            out.append(Challenge(task_id=task.id, kind="contradicts", ask="accept", evidence=[t.id],
                                 text=f"A fix moved it on “{moved.question}” and not on “{still.question}”: it holds "
                                      "for one question, not both."))
    return out


# ---------------------------------------------------------------- the coordinator (a model, bounded)
COORDINATOR = """You coordinate the investigators of Off Message, which measures how AI answer engines describe a company.

Each investigator takes one claim and one branded question (a question that names the company, never the claim). It asks the question live and records what the AI read, then re-asks many times with one thing changed in that reading, to find which pages make AI say the claim and whether the company's copy or its authority would change it. Each costs money, so choose.

Choose the claims worth investigating for this company: claims it wants AI to repeat, and perceptions AI raises on its own that harm it. Skip perceptions that are harmless or flattering: there is nothing for the company to fix.

Choose the question. For a claim of the company's, pick one where AI does not say it yet but plausibly could: if AI already says it, no fix can show a rise. For a perception AI raises, pick one where AI said it, so the investigator can find the pages behind it; you may give a literal term (such as "debt") that counts as saying it, which makes judging exact and free. Never give a term for a claim of the company's.

When a finished task is challenged, redispatch it once changing one thing (another question, a term, or more_budget), or accept it. Call finish when nothing left is worth the money. Every reason is one plain sentence a marketer will read. Respond only with tool calls."""


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}


S = {"type": "string"}
TOOLS = [
    _tool("dispatch", "Send an investigator to one shortlisted claim with one of its branded questions.",
          {"attribute_id": S, "probe_id": S, "term": {"type": ["string", "null"]}, "reason": S},
          ["attribute_id", "probe_id", "reason"]),
    _tool("redispatch", "Send one more investigator after a finished task, changing one thing.",
          {"task_id": S, "probe_id": {"type": ["string", "null"]}, "term": {"type": ["string", "null"]},
           "more_budget": {"type": "boolean"}, "reason": S}, ["task_id", "reason"]),
    _tool("accept", "Keep a finished task's verdict as it is.", {"task_id": S, "reason": S}, ["task_id"]),
    _tool("skip", "Decide a shortlisted claim is not worth investigating.", {"attribute_id": S, "reason": S},
          ["attribute_id", "reason"]),
    _tool("finish", "Nothing more is worth the money: dispatch no more.", {"reason": S}, ["reason"]),
]


class State:
    """The fleet as its loop sees it. Only the loop's thread touches it."""

    def __init__(self, run: Run, purse: access.Purse):
        self.run, self.purse = run, purse
        self.attributes = {a.id: a for a in run.attributes}
        self.candidates = {c["attribute_id"]: c for c in shortlist(run)}
        self.tasks: dict[str, FleetTask] = {}
        self.results: dict[str, Investigation] = {}     # finished task id -> its investigation
        self.failed: dict[str, str] = {}
        self.challenges: dict[str, list[Challenge]] = {}
        self.decided: dict[str, str] = {}               # task id -> accepted | redispatched
        self.skipped: dict[str, str] = {}               # attribute id -> why
        self.queue: list[FleetTask] = []
        self.running: set[str] = set()
        self.notes: list[str] = []                      # calls rejected last turn, told back to the model
        self.turns = 0
        self.finished = False                           # dispatch no more
        self.refused: Optional[str] = None

    def tries(self, attribute_id: str) -> list[FleetTask]:
        return [t for t in self.tasks.values() if t.attribute_id == attribute_id]

    def pending(self) -> list[str]:
        """Finished tasks with a challenge nobody has decided yet."""
        return [tid for tid in self.results if self.challenges.get(tid) and tid not in self.decided]


def describe(c: dict) -> str:
    if c["kind"] == "claim":
        return (f"a claim of the company's: {ZONE_WORDS[c['zone']]}"
                + (f"; intent weight {c['weight']:g}" if c["weight"] else "")
                + f"; AI endorsed it in {c['endorsed']} of {c['n']} brand answers"
                + (f"; a suggested rewrite exists for {why.page_name(c['rewrite_page'])}" if c["rewrite_page"] else ""))
    return (f"a perception AI raises on its own: mentioned in {c['mentioned']} of {c['n']} brand answers, "
            f"negatively in {c['negative']}")


def digest(st: State) -> str:
    """What the coordinator is told each turn: the shortlist and what happened, never an answer's full
    text, a reading list or an arm."""
    run = st.run
    lines = [f"Company: {run.profile.name}. Budget left: ${st.purse.left():.2f} of ${st.purse.limit:.2f}; an "
             f"investigation may spend up to ${why.budget():.2f} (about ${MEAN_COST:.2f} on average). At most "
             f"{MAX_TASKS} tasks and {MAX_TRIES} per claim; {len(st.running)} running, {len(st.queue)} waiting.",
             "", "Shortlist:"]
    for aid, c in st.candidates.items():
        tries = [t.id for t in st.tries(aid)]
        state = (f"tasks {', '.join(tries)}" if tries else f"skipped: {st.skipped[aid]}" if aid in st.skipped
                 else "not dispatched")
        lines.append(f"- {aid}: “{c['label']}” — {describe(c)} [{state}]")
        for q in c["questions"]:
            said = (f"AI said it ({q['said']}): “{q['quote']}”" if q["said"] else "AI did not say it")
            lines.append(f"    {q['probe_id']}: “{q['text']}” — {said}")
    if st.tasks:
        lines += ["", "Tasks:"]
        for t in st.tasks.values():
            if t.id in st.results:
                inv = st.results[t.id]
                status = "finished: " + " | ".join(f"{v.kind}: {v.text}" for v in inv.verdicts)
                status += "".join(f" | CHALLENGED ({c.kind}, suggests {c.ask}): {c.text}" for c in st.challenges.get(t.id, []))
                status += f" | {st.decided[t.id]}" if t.id in st.decided else ""
            else:
                status = f"failed: {st.failed[t.id]}" if t.id in st.failed else "running" if t.id in st.running else "waiting"
            lines.append(f"- {t.id}: {t.attribute_id} on {t.probe_id}" + (f" term “{t.term}”" if t.term else "")
                         + f" (try {t.try_no}, budget ${t.budget_usd:.2f}): {status}")
    if st.notes:
        lines += ["", "Rejected last turn:", *[f"- {n}" for n in st.notes]]
    lines += ["", "Decide now, with tool calls."]
    return "\n".join(lines)


def coordinator_calls(st: State, model: str) -> list[tuple[str, dict]]:
    r = access.openai_response(live.LIMITS["per_call_timeout_s"], model=model, tools=TOOLS, tool_choice="required",
                               input=[{"role": "system", "content": COORDINATOR}, {"role": "user", "content": digest(st)}])
    calls = []
    for item in live._output_items(r):
        if live._item(item, "type") == "function_call":
            try:
                args = json.loads(live._item(item, "arguments") or "{}")
            except ValueError:
                args = {}
            calls.append((live._item(item, "name"), args if isinstance(args, dict) else {}))
    return calls


def _text(x) -> Optional[str]:
    return " ".join(x.split()) if isinstance(x, str) and x.strip() else None


class Coordinator:
    """Applies the coordinator's calls, each checked; a rejected call is logged and told back next turn."""

    def __init__(self, st: State, log: EventLog, model: str):
        self.st, self.log, self.model = st, log, model

    def turn(self) -> None:
        st = self.st
        if st.finished or st.refused:
            return
        if st.turns >= MAX_TURNS:
            return self.fallback(f"the coordinator used its {MAX_TURNS} turns")
        for repair in (False, True):
            # a turn whose every call was refused gets one more, with the reasons, before code decides
            st.turns += 1
            try:
                calls = coordinator_calls(st, self.model)
            except access.Refused as e:
                st.refused = e.message
                self.log.append("stopped", reason=e.message)
                return
            except (Exception, access.PurseEmpty) as e:
                self.log.append("turn", by="code", n=st.turns, error=type(e).__name__)
                return self.fallback(f"the coordinator's call failed ({type(e).__name__})")
            st.notes = []
            self.log.append("turn", by="model", n=st.turns, calls=len(calls), repair=repair)
            valid = 0
            for name, args in calls:
                problem = self.apply(name, args, "model")
                if problem:
                    st.notes.append(f"{name}({json.dumps(args)[:200]}): {problem}")
                    self.log.append("rejected", call=name, args=args, reason=problem)
                else:
                    valid += 1
            if valid or not st.notes or st.finished or st.turns >= MAX_TURNS:
                break
        if not valid:
            self.fallback("none of the coordinator's calls could be used")

    def fallback(self, why_: str) -> None:
        """Code decides: its own top picks on the first turn; afterwards each challenge's own ask."""
        st = self.st
        if not st.tasks:
            for c in [c for c in st.candidates.values() if c["pick"]][:FIRST_PICKS]:
                probe = code_question(c, set())
                if probe:
                    self.apply("dispatch", dict(attribute_id=c["attribute_id"], probe_id=probe,
                                                reason=f"Code's pick ({why_}): "
                                                       + ("a claim to win back or amplify." if c["kind"] == "claim"
                                                          else "AI raises it critically.")), "code")
        for tid in st.pending():
            ask = st.challenges[tid][0].ask
            task = st.tasks[tid]
            problem = "accept"
            if ask == "other_question":
                probe = code_question(st.candidates[task.attribute_id], {t.probe_id for t in st.tries(task.attribute_id)})
                problem = self.apply("redispatch", dict(task_id=tid, probe_id=probe,
                                                        reason="Another question, as the critic asked."),
                                     "code") if probe else "no other question"
            elif ask == "more_budget":
                problem = self.apply("redispatch", dict(task_id=tid, more_budget=True,
                                                        reason="More budget, as the critic asked."), "code")
            if problem:
                self.apply("accept", dict(task_id=tid, reason="Accepted: a re-dispatch was not possible."), "code")

    def apply(self, name: str, args: dict, by: str) -> Optional[str]:
        """-> None when the call was applied, else why not, in words the model reads next turn."""
        st = self.st
        if name == "dispatch":
            aid, probe = args.get("attribute_id"), args.get("probe_id")
            c = st.candidates.get(aid)
            if c is None:
                return "not on the shortlist"
            if st.tries(aid):
                return f"already dispatched as {st.tries(aid)[0].id}; use redispatch on a finished task"
            return self._new(c, probe, args.get("term"), why.budget(), args, by)
        if name == "redispatch":
            task = st.tasks.get(args.get("task_id"))
            if task is None or (task.id not in st.results and task.id not in st.failed):
                return "not a finished or failed task"
            if task.id in st.decided:
                return f"already {st.decided[task.id]}"
            if len(st.tries(task.attribute_id)) >= MAX_TRIES:
                return f"{MAX_TRIES} tries per claim is the limit"
            probe = args.get("probe_id") or task.probe_id
            term = args.get("term") if "term" in args else task.term
            more = bool(args.get("more_budget"))
            used = {t.probe_id for t in st.tries(task.attribute_id)}
            if task.id in st.results and not more and probe in used and (term or None) == (task.term or None):
                return "change one thing: another question, a term, or more_budget"
            spend = min(2 * why.budget(), 2 * task.budget_usd) if more else why.budget()
            problem = self._new(st.candidates[task.attribute_id], probe, term, spend, args, by, parent=task)
            if not problem:
                st.decided[task.id] = "redispatched"
            return problem
        if name == "accept":
            tid = args.get("task_id")
            if tid not in st.results:
                return "not a finished task"
            if tid in st.decided:
                return f"already {st.decided[tid]}"
            st.decided[tid] = "accepted"
            self.log.append("accepted", tid, by=by, reason=_text(args.get("reason")) or "")
            return None
        if name == "skip":
            aid = args.get("attribute_id")
            if aid not in st.candidates:
                return "not on the shortlist"
            if st.tries(aid) or aid in st.skipped:
                return "already decided"
            st.skipped[aid] = _text(args.get("reason")) or "not worth investigating"
            self.log.append("skipped", attribute_id=aid, claim=st.candidates[aid]["label"], by=by, reason=st.skipped[aid])
            return None
        if name == "finish":
            st.finished = True
            self.log.append("turn", by=by, finish=_text(args.get("reason")) or "")
            return None
        return f"unknown tool {name!r}"

    def _new(self, c: dict, probe: Optional[str], term, spend: float, args: dict, by: str,
             parent: Optional[FleetTask] = None) -> Optional[str]:
        st = self.st
        q = next((q for q in c["questions"] if q["probe_id"] == probe), None)
        if q is None:
            return f"{probe!r} is not one of this claim's branded questions"
        term = _text(term)
        if term and c["kind"] == "claim":
            return ("a literal term counts any mention, and a claim of the company's counts only endorsements, "
                    "so give no term")
        if term and len(term) > MAX_TERM:
            return f"a term must be at most {MAX_TERM} characters"
        reason = _text(args.get("reason"))
        if not reason:
            return "give a reason a marketer can read"
        if st.finished:
            return "the fleet has finished dispatching"
        if len(st.tasks) >= MAX_TASKS:
            return f"{MAX_TASKS} tasks is the fleet's limit"
        if st.purse.left() < spend:
            return f"the purse has ${st.purse.left():.2f} left, less than this task's ${spend:.2f}"
        task = FleetTask(id=f"t{len(st.tasks) + 1}", attribute_id=c["attribute_id"], claim=c["label"], probe_id=q["probe_id"],
                         question=q["text"], term=term, reason=reason, budget_usd=round(spend, 2), by=by,
                         try_no=parent.try_no + 1 if parent else 1, parent=parent.id if parent else None)
        st.tasks[task.id] = task
        st.queue.append(task)
        self.log.append("dispatched", task.id, task=task.model_dump())
        return None


# ---------------------------------------------------------------- the planner/writer
ORDER = {"copy": 0, "authority": 1, "source": 2, "none": 3, "thin": 4, "untested": 5}


def _arm(inv: Investigation, arm_id: Optional[str]):
    return next((a for a in inv.arms if a.id == arm_id), None)


def _numbers(a) -> dict:
    return dict(arm_id=a.id, k=a.k, n=a.n, base_k=a.base_k, base_n=a.base_n, effect=a.effect, interval=a.interval)


def item_for(task: FleetTask, inv: Investigation, attribute, challenges: list[Challenge],
             own: tuple[str, ...] = ()) -> PlanItem:
    """One claim's line, from the investigation that decided most. Numbers are the arm's own. `own` is
    the company's domains: a source on them is its to change, anyone else's is not."""
    base = dict(rank=0, attribute_id=task.attribute_id, claim=task.claim, question=task.question, task_id=task.id,
                investigation_id=inv.id, notes=[c.text for c in challenges if c.kind in ("off_claim", "contradicts")])
    doubtful = any(c.kind == "off_claim" for c in challenges)
    fix = next((v for v in inv.verdicts if v.kind in MOVED), None)
    if fix and not doubtful:
        a = _arm(inv, fix.arm_id)
        return PlanItem(fix="copy" if fix.kind == "copy_fix" else "authority", text=fix.text, page_url=a.urls[0],
                        rewrite=a.text[0] if a.text else None, hypothetical=a.hypothetical, **_numbers(a), **base)
    drops = [a for a in inv.arms if a.kind in ("drop_source", "drop_passage") and a.decided == "effect" and a.effect < 0]
    if attribute.discovered and drops and not doubtful:
        a = drops[-1]   # the narrowest cause the investigation decided
        cause = next((v for v in inv.verdicts if v.kind in ("caused_by", "over_determined")), None)
        text = cause.text if cause else (
            f"AI says it because of what {why.count_pages(a.urls)} say together ({why.named(a.urls)}): removing them "
            f"takes it from {a.base_k}/{a.base_n} to {a.k}/{a.n} replays. Neither part of them decided alone.")
        mine = [u for u in a.urls if domain_matches(u, list(own))]
        text += (" Some of them are your own pages: what they say there is yours to change." if mine else
                 " None of them is your page to edit: answer what they say on a page of yours that AI reads.")
        return PlanItem(fix="source", text=text, sources=a.urls, **_numbers(a), **base)
    settled = next((v for v in inv.verdicts if v.kind in ("prior_belief", "not_movable", "copy_lowers", "not_in_reading", "not_said")), None)
    if settled and not doubtful:
        a = _arm(inv, settled.arm_id)
        return PlanItem(fix="none", text=settled.text, **(_numbers(a) if a else {}), **base)
    last = inv.verdicts[-1].text if inv.verdicts else "The investigation ended without a verdict."
    why_thin = next((c.text for c in challenges), "")
    return PlanItem(fix="thin", text=f"Not decided. {last}" + (f" {why_thin}" if why_thin else ""), **base)


def best(tries: list[tuple[FleetTask, Investigation]]) -> tuple[FleetTask, Investigation]:
    """The try to plan from: one with a tested fix, else one with any decided verdict, else the latest."""
    def score(pair):
        kinds = {v.kind for v in pair[1].verdicts}
        return (bool(kinds & MOVED), bool(kinds & DECIDED), pair[0].try_no)
    return max(tries, key=score)


def plan(st: State) -> ActionPlan:
    """Code ranks: tested copy fixes by the low end of their interval times intent weight, then authority
    fixes, then sources to address, then what copy cannot move, then what did not decide, then the
    run's untested rewrites."""
    run, items = st.run, []
    for aid in dict.fromkeys(t.attribute_id for t in st.tasks.values()):
        tries = [(t, st.results[t.id]) for t in st.tries(aid) if t.id in st.results]
        if not tries:
            last = st.tries(aid)[-1]
            items.append(PlanItem(rank=0, attribute_id=aid, claim=last.claim, fix="thin", question=last.question,
                                  task_id=last.id, text="No investigation of it finished: "
                                                        + (st.failed.get(last.id) or "the fleet stopped first.")))
            continue
        task, inv = best(tries)
        items.append(item_for(task, inv, st.attributes[aid], st.challenges.get(task.id, []),
                              tuple(run.profile.all_domains())))
    for w in run.win_back:
        if w.attribute_id not in {i.attribute_id for i in items}:
            items.append(PlanItem(rank=0, attribute_id=w.attribute_id, claim=w.label, fix="untested", page_url=w.page_url,
                                  rewrite=w.passage(), hypothetical=True,
                                  text=f"Not tested: the run's suggested rewrite for {why.page_name(w.page_url)}."))
    weight = {a.id: a.intended_weight or 1.0 for a in run.attributes}

    def key(i: PlanItem):
        if i.fix in ("copy", "authority") and i.interval:
            return ORDER[i.fix], -i.interval[0] * weight.get(i.attribute_id, 1.0)
        return ORDER[i.fix], (i.effect or 0) if i.fix == "source" else 0
    items.sort(key=key)
    for n, i in enumerate(items, 1):
        i.rank = n
    return ActionPlan(items=items)


WRITER = """You write the action plan for {name}'s marketing team. Each item below is a fix an experiment tested, already ranked, with a line written by code. Rewrite each line in plain words a marketer acts on: what to publish or get found, on which page, and what the experiment found. Keep the action the line gives; keep every number exactly as given and add none. Name the page the line names and no other. No marketing adjectives. At most 45 words a line.

Return ONLY JSON: {{"lines": [{{"rank": <int>, "text": <string>}}]}}

Items:
{items}"""
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
DOMAIN = re.compile(r"\b[\w-]+(?:\.[a-z]{2,})+(?:/[\w\-./%~]*[\w/])?", re.I)


def acceptable(new, old: str) -> bool:
    """A writer's line replaces the template's only if it adds no number, no page and no marketing word,
    and still names the page the template names."""
    if not evaluation.real(new) or len(new.split()) > 60:
        return False
    pages, named = set(DOMAIN.findall(new)), set(DOMAIN.findall(old))
    return (set(NUMBER.findall(new)) <= set(NUMBER.findall(old)) and pages <= named and (pages or not named)
            and not MARKETING.search(new))


WORDED = ("copy", "authority")   # the fixes a marketer acts on; every other line stays code's own


def write(p: ActionPlan, run: Run, model: str) -> None:
    """One model call words the tested fixes; code keeps each line only if `acceptable`, else the
    template's. Sources, what copy cannot move and what did not decide keep code's lines: on the live
    Amgen fleet (2026-09-28) the writer turned "AI says it because of a line of the SEC filing" into
    "remove them", and "not decided" into instructions to test more."""
    worded = [i for i in p.items if i.fix in WORDED]
    if not worded:
        return
    items = "\n".join(f"{i.rank}. [{i.fix}] {i.claim}: {i.text}" for i in worded)
    try:
        r = access.openai_response(live.LIMITS["per_call_timeout_s"], model=model,
                                   input=WRITER.format(name=run.profile.name, items=items))
        lines = json_object(live.parse_response(r)[0]).get("lines")
    except (Exception, access.PurseEmpty, access.Refused) as e:
        p.notes.append(f"The writer's call failed ({type(e).__name__}), so every line is the template's.")
        return
    by_rank, kept = {i.rank: i for i in worded}, 0
    for line in lines if isinstance(lines, list) else []:
        item = by_rank.get(line.get("rank")) if isinstance(line, dict) else None
        if item and acceptable(line.get("text"), item.text):
            item.text, kept = " ".join(line["text"].split()), kept + 1
    p.written_by = model if kept else "template"
    if kept < len(worded):
        p.notes.append(f"{len(worded) - kept} of {len(worded)} fix line(s) are the template's: the writer's version "
                       "added a number or a page, dropped the page, or was missing.")


# ---------------------------------------------------------------- the loop
def investigate(run: Run, task: FleetTask, resolved, emit, cancel: threading.Event) -> Investigation:
    from agents.evaluator_model import ModelEvaluator
    lab = why.Lab(resolved.model, resolved.tool)
    evaluator = None if task.term else ModelEvaluator(model=resolved.judge, transport=lab.judge_transport)
    return why.start(run, task.attribute_id, task.question, probe_id=task.probe_id, term=task.term, lab=lab,
                     evaluator=evaluator, emit=emit, budget_usd=task.budget_usd, cancel=cancel)


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def execute(run: Run, log: EventLog, resolved, pass_id: Optional[str] = None, budget_usd: Optional[float] = None,
            lanes: Optional[int] = None, task_deadline: float = TASK_DEADLINE_S,
            deadline: float = FLEET_DEADLINE_S) -> str:
    """Runs one fleet to its end on a saved live run. -> its status. The caller sets the paying pass
    (access.spending); every thread this starts inherits it and the purse."""
    purse = access.Purse(budget_usd or budget(), WRITER_RESERVE, IN_FLIGHT)
    log.spent = lambda: purse.spent
    lanes = lanes or concurrency()
    st = State(run, purse)
    coordinator = Coordinator(st, log, resolved.judge)
    t0 = time.monotonic()
    log.append("started", fleet_id=log.id, run_id=run.id, company=run.profile.name, budget_usd=purse.limit,
               concurrency=lanes, why_budget_usd=why.budget(), model=resolved.model, coordinator=resolved.judge,
               max_tasks=MAX_TASKS)
    log.append("shortlist", candidates=[{k: c[k] for k in ("attribute_id", "label", "kind", "zone", "mentioned",
                                                           "endorsed", "negative", "n")} for c in st.candidates.values()])
    inbox: queue.Queue = queue.Queue()
    running: dict = {}   # future -> (task, cancel flag, started)
    status = "complete"
    with access.drawing(purse), ThreadPoolExecutor(lanes) as pool:
        if st.candidates:
            coordinator.turn()
        while True:
            while st.queue and len(running) < lanes and not st.refused:
                task = st.queue.pop(0)
                if purse.left() < min(task.budget_usd, why.budget()) / 4:
                    log.append("skipped", task.id, attribute_id=task.attribute_id, claim=task.claim, by="code",
                               reason="The fleet's budget ran out before it started.")
                    continue
                cancel = threading.Event()
                emit = (lambda tid: lambda kind, payload: inbox.put((tid, kind, payload)))(task.id)
                f = pool.submit(copy_context().run, investigate, run, task, resolved, emit, cancel)
                running[f] = (task, cancel, time.monotonic())
                st.running.add(task.id)
                log.append("began", task.id)
            if not running:
                break
            done, _ = wait(running, timeout=0.5, return_when=FIRST_COMPLETED)
            drain(inbox, log)
            landed = []
            for f in done:
                task, _, _ = running.pop(f)
                st.running.discard(task.id)
                if inv := outcome(f, task, st, log, pass_id):
                    landed.append((task, inv))
            for task, inv in landed:
                others = [(t, st.results[t.id]) for t in st.tries(task.attribute_id) if t.id in st.results and t.id != task.id]
                st.challenges[task.id] = critic(inv, task, st.attributes[task.attribute_id], others)
                for c in st.challenges[task.id]:
                    log.append("challenged", task.id, challenge=c.model_dump())
                if not st.challenges[task.id]:
                    st.decided[task.id] = "accepted"
                    log.append("accepted", task.id, by="code", reason="The critic found nothing to challenge.")
            if done:
                coordinator.turn()
            late = time.monotonic() - t0 > deadline
            if late and not st.finished:
                st.finished, status = True, "stopped"
                for task in st.queue:
                    log.append("skipped", task.id, attribute_id=task.attribute_id, claim=task.claim, by="code",
                               reason="The fleet reached its deadline before it started.")
                st.queue.clear()
            for task, cancel, began in running.values():
                if not cancel.is_set() and (late or time.monotonic() - began > task_deadline):
                    cancel.set()
                    log.append("cancelling", task.id, reason="deadline")
        drain(inbox, log)
        for tid in st.pending():
            st.decided[tid] = "accepted"
            log.append("accepted", tid, by="code", reason="Accepted as it stood when the fleet ended.")
        purse.release_reserve()
        p = plan(st)
        write(p, run, resolved.judge)
        log.append("planned", plan=p.model_dump())
    if st.refused:
        status = "stopped"
    log.append("done", status=status, wall_s=round(time.monotonic() - t0, 1), spent_usd=round(purse.spent, 4),
               tasks=len(st.tasks), refused=st.refused)
    return status


def drain(inbox: queue.Queue, log: EventLog) -> None:
    """The investigators' own events, in the order they arrived, onto the log."""
    while True:
        try:
            tid, kind, payload = inbox.get_nowait()
        except queue.Empty:
            return
        if kind == "log":
            log.append("progress", tid, text=payload.get("text", ""))
        elif kind == "arm":
            log.append("arm", tid, arm=payload)
        elif kind == "verdict":
            log.append("verdict", tid, verdict=payload)


def outcome(f, task: FleetTask, st: State, log: EventLog, pass_id: Optional[str]) -> Optional[Investigation]:
    """A finished future onto the log: its investigation saved and owned, or why it failed. Never raises."""
    exc = f.exception()
    if exc is None:
        inv = f.result()
        inv.fleet_id = log.id
        reports.save_investigation(inv)
        if pass_id:
            access.own("investigation", inv.id, pass_id, st.run.profile.name)
        st.results[task.id] = inv
        base = inv.arms[0] if inv.arms else None
        log.append("finished", task.id, investigation_id=inv.id, status=inv.status, spent_usd=inv.spent_usd,
                   verdicts=[v.model_dump() for v in inv.verdicts], live=inv.live.model_dump(),
                   base={"k": base.k, "n": base.n} if base else None, arms=len(inv.arms) - 1 if inv.arms else 0)
        return inv
    if isinstance(exc, access.Refused):
        st.refused = exc.message
        st.failed[task.id] = exc.message
    else:
        st.failed[task.id] = f"{type(exc).__name__}: {live.safe_error(exc) if isinstance(exc, Exception) else exc}"
    log.append("failed", task.id, error=st.failed[task.id])
    return None


def estimate(run: Run) -> dict:
    """What the button says before anything is spent: the pilot's mean investigation times the picks."""
    n = min(FIRST_PICKS, sum(c["pick"] for c in shortlist(run)))
    usd = min(budget(), n * MEAN_COST * 1.4)            # room for re-dispatches
    minutes = MEAN_MINUTES * -(-max(n, 1) // concurrency()) * 1.4
    return dict(candidates=len(shortlist(run)), picks=n, usd=round(usd, 2), minutes=round(minutes), budget_usd=budget())
