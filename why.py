"""The why agent: why does AI say this about a brand, and what would change it, by experiment.

Ask the branded question live and record what the model read (providers/live.reading_of). Ask it
with search off too: what the model says from what it already believes. Then replay that reading
list with search off, handed back as the web_search tool's own output, and check the replay says
the claim about as often as live did; if it does not, the answer depends on more than what was read
and the investigation stops there. Otherwise change one thing in the reading list and ask again:

  drop source   every result from some pages          is this what makes AI say it?
  drop passage  only the lines that say it            which sentence, which table row?
  edit          the company's rewrite leads a page    would copy on a page AI already reads fix it?
                AI already read
  inject        a company page search never returned  would AI say it if search found the page?

Each arm is re-asked in batches (LOOKS) until the change in how often answers state the claim has a
95% interval that excludes zero, or sits inside ±NO_EFFECT, or the batches run out. The interval is
corrected for every look and every arm the investigation could try (Z), so its 95% covers the whole
investigation, not one lucky arm. Causes can be redundant, so sources are tested as a group and
bisected, never one guess at a time.

A quick win's rewrite gets the same experiment on a buyer question (test_rewrite): ask it live and
record what the model read, replay that, then replay it again with the rewrite on its page (leading it
when AI read the page, added to the search results when it did not) and count the gap the question
has: whether the answer names the company (a question that did not name it), or recommends it (one
that named it without recommending it). That is the proof, or the disproof, that a rewrite would
change what AI says for that question, before anything is published. A question whose replays
already name or recommend the company nearly every time cannot show a gain, and says so (ceiling).

A replay is an experiment on a recorded reading list, never a measurement: its answers are
provenance `counterfactual_replay`, live only in the Investigation, and never reach a score.
Edited or injected text that is not a page's own verbatim text is hypothetical copy and is labelled so. Every call goes through
access.openai_response, and the whole investigation stops at its budget (WHY_BUDGET_USD), at its
fleet's purse (access.PurseEmpty) or when its fleet cancels it (fleet.py).

"States the claim" counts what the report counts: for a claim of the company's, only answers that
endorse it (drift.py's echo counts positive observations only); for a perception AI raised on its
own, any mention (drift.py keys those on mentions). A literal term cannot tell the two apart, so it
counts any mention and says so.
"""
import json
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Callable, Optional
from urllib.parse import urlparse

import access
from agents import evaluation
from providers import live
from schemas import (Answer, Attribute, CompanyProfile, Investigation, Probe, ReadResult, ReadStep,
                     WhyArm, WhyRate, WhyVerdict)
from scoring import domain_matches, mentions_alias, newcombe, wilson, z_for

BUDGET_ENV = "WHY_BUDGET_USD"
DEFAULT_BUDGET = 0.60      # the pilot's mean investigation cost $0.36 (2026-09-28)
LIVE_ASKS = OFF_ASKS = 3
LOOKS = (6, 18, 36)          # asks per arm at each look; the base is topped up to match
MAX_ARMS = 6                 # the most experiments one investigation may run
Z = z_for(0.05 / (len(LOOKS) * MAX_ARMS))   # every look of every arm shares the 5%: z ≈ 2.99
# An interval inside ±this is "no effect", decided. A fifth of answers is what 36 asks can rule out
# at a rate near 0; nearer 50% the interval stays wider and the arm is reported undecided.
NO_EFFECT = 0.2
FIX_ARMS = 2                 # kept back for the copy and authority tests of a claim the company makes
READ_CAP = 20_000            # characters of each result kept to replay; the run's own copy is capped harder
CONCURRENCY = 6

OFF_INSTRUCTION = live.NEUTRAL_INSTRUCTION.replace("Use web search. ", "")
# The replay hands the recorded reading list back in the slot a real search result arrives in, so
# the model reads it as it read it live. Pasted into the prompt instead, agreement with the live
# answer fell (0.68–0.90 against 0.83–1.00 on four Amgen questions, 2026-09-28).
REPLAY_TOOL = {"type": "function", "name": "web_search", "description": "Search the web and read pages.",
               "parameters": {"type": "object", "properties": {
                   "queries": {"type": "array", "items": {"type": "string"}},
                   "open": {"type": "string"}, "find": {"type": "string"}}}}


def budget() -> float:
    """WHY_BUDGET_USD, the most one investigation may spend; unreadable or tiny -> the default."""
    try:
        return max(0.05, float(os.environ.get(BUDGET_ENV) or DEFAULT_BUDGET))
    except ValueError:
        return DEFAULT_BUDGET


# ---------------------------------------------------------------- the reading list
def replay_input(question: str, reading: list[ReadStep]) -> list[dict]:
    """The neutral prompt, then each recorded step as the tool call and its output, in order."""
    items = [{"role": "system", "content": live.NEUTRAL_INSTRUCTION}, {"role": "user", "content": question}]
    n = 0
    for i, step in enumerate(reading):
        args = ({"queries": step.queries} if step.kind == "search"
                else {"open": step.url} if step.kind == "open_page" else {"find": step.pattern or "", "open": step.url})
        out = "\n\n".join(f"[{n + j}] {r.title or ''} — {r.url}\n{r.text}" for j, r in enumerate(step.results))
        n += len(step.results)
        items += [{"type": "function_call", "call_id": f"call_{i}", "name": "web_search", "arguments": json.dumps(args)},
                  {"type": "function_call_output", "call_id": f"call_{i}", "output": out or "(no results)"}]
    return items


def urls_of(reading: list[ReadStep]) -> list[str]:
    return list(dict.fromkeys(r.url for s in reading for r in s.results))


def drop_sources(reading: list[ReadStep], urls: set[str]) -> list[ReadStep]:
    return [s.model_copy(update={"results": [r for r in s.results if r.url not in urls]}) for s in reading]


SEGMENT = re.compile(r"(?<=[.!?])\s+|\n")


def drop_lines(reading: list[ReadStep], url: str, says: Callable[[str], bool]) -> tuple[list[ReadStep], list[str]]:
    """-> the reading list without the lines or sentences of `url` that say it, and those lines."""
    gone = []

    def cut(text: str) -> str:
        kept = []
        for seg in re.split(r"(\n)", text):
            if seg == "\n":
                kept.append(seg)
                continue
            parts = [p for p in re.split(r"(?<=[.!?])\s+", seg)]
            keep = [p for p in parts if not says(p)]
            gone.extend(p.strip() for p in parts if says(p) and p.strip())
            kept.append(" ".join(keep))
        return "".join(kept)

    out = [s.model_copy(update={"results": [r.model_copy(update={"text": cut(r.text)}) if r.url == url else r
                                            for r in s.results]}) for s in reading]
    return out, list(dict.fromkeys(gone))


def lead_with(reading: list[ReadStep], url: str, copy: str) -> list[ReadStep]:
    """The company's copy put first on a page AI already read (every result from that page)."""
    return [s.model_copy(update={"results": [r.model_copy(update={"text": f"{copy} {r.text}"}) if r.url == url else r
                                            for r in s.results]}) for s in reading]


def inject(reading: list[ReadStep], url: str, title: str, copy: str) -> list[ReadStep]:
    """A page search never returned, added last to the first search's results."""
    page = ReadResult(url=url, title=title, text=copy)
    first = next((i for i, s in enumerate(reading) if s.kind == "search"), None)
    if first is None:
        return [*reading, ReadStep(kind="search", results=[page])]
    return [s.model_copy(update={"results": [*s.results, page]}) if i == first else s for i, s in enumerate(reading)]


# ---------------------------------------------------------------- does an answer state the claim?
def term_pattern(term: str) -> re.Pattern:
    """A word, whole: an acronym ("AI") only in capitals, so "said" never counts; anything else in any case."""
    flags = 0 if term.isupper() else re.I
    return re.compile(rf"(?<![\w]){re.escape(term)}(?![\w])", flags)


def sentence_with(text: str, m: re.Match) -> str:
    start = max(text.rfind(c, 0, m.start()) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, m.end()) for c in ".!?\n") if i != -1]
    return text[start:(min(ends) + 1) if ends else len(text)].strip()


class Judge:
    """Whether one answer states the claim, with the verbatim sentence or quote that does.

    With a `term`, a literal whole-word match decides: deterministic and free, and it counts any
    mention. Otherwise the run's evaluator model labels the answer against this one claim and
    evaluation.extract_attributes keeps only a quote that is verbatim in it — the same validation
    every scored answer goes through — and with `endorse` only a positive observation counts, as the
    report's echo counts it. A neutral mention ("research and development, AI and data") of a claim
    to amplify is not AI saying it."""

    def __init__(self, attribute: Attribute, profile: CompanyProfile, question: str,
                 term: Optional[str] = None, evaluator=None, endorse: bool = False):
        self.attribute, self.profile, self.term, self.endorse = attribute, profile, term, endorse
        self.pattern = term_pattern(term) if term else None
        self.evaluator = evaluator
        self.probe = Probe(id="why", topic_id="perception", text=question, kind="named", phase="baseline",
                           purpose="why-agent experiment")

    @property
    def name(self) -> str:
        if self.term:
            return f"literal “{self.term}”, any mention"
        return f"evaluator ({getattr(self.evaluator, 'model', '?')})" + (", endorsements only" if self.endorse else "")

    def __call__(self, text: str) -> tuple[Optional[bool], Optional[str]]:
        """-> (states it?, the quote), or (None, None) when it could not be judged."""
        if not text:
            return None, None
        if self.pattern:
            m = self.pattern.search(evaluation.answer_body(text))
            return (True, sentence_with(evaluation.answer_body(text), m)) if m else (False, None)
        answer = Answer(probe_id="why", text=text, provenance="counterfactual_replay", status="ok")
        labels = self.evaluator.label(self.probe, answer, [self.attribute], self.profile)
        if labels is None:
            return None, None
        obs, _ = evaluation.extract_attributes(answer.model_copy(update={"evaluator_labels": labels}), [self.attribute])
        obs = [o for o in obs if o.polarity == "positive" or not self.endorse]
        return (True, obs[0].quote) if obs else (False, None)


class NamesJudge:
    """Whether an answer to a buyer question names the company: any of its names, whole and in its own
    case, in the answer's body (a name only in a citation is a source it read, not something it said).
    Free and deterministic, and the same test buyer visibility's mentions rest on (scoring.mentions_alias)."""

    def __init__(self, profile: CompanyProfile):
        self.names = profile.names()
        self.name = f"names {profile.name} (any of its names)"

    def __call__(self, text: str) -> tuple[Optional[bool], Optional[str]]:
        if not text:
            return None, None
        body = evaluation.answer_body(text)
        if not mentions_alias(body, self.names):
            return False, None
        m = min((m for n in self.names if (m := re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", body))),
                key=lambda m: m.start())
        return True, sentence_with(body, m)


class RecommendsJudge:
    """Whether an answer to a buyer question recommends the company: the run's evaluator labels it and
    evaluation.evaluate validates it as it does every scored answer, so a recommendation without a
    mention in the body, or a label that fails its checks, is not one."""

    def __init__(self, profile: CompanyProfile, probe: Probe, evaluator):
        self.profile, self.probe, self.evaluator = profile, probe, evaluator
        self.name = f"recommends {profile.name}, evaluator ({getattr(evaluator, 'model', '?')})"

    def __call__(self, text: str) -> tuple[Optional[bool], Optional[str]]:
        if not text:
            return None, None
        answer = Answer(probe_id=self.probe.id, text=text, provenance="counterfactual_replay", status="ok")
        labels = self.evaluator.label(self.probe, answer, [], self.profile)
        if labels is None:
            return None, None
        e = evaluation.evaluate(self.probe, answer.model_copy(update={"evaluator_labels": labels}), self.profile)
        if not e.valid:
            return None, None
        return (True, next(iter(e.evidence_quotes), None)) if e.recommended else (False, None)


def buyer_judge(run, probe: Probe, counts: str, evaluator=None):
    """The judge a buyer question's replay test counts with: naming, or recommending when it already named you."""
    return RecommendsJudge(run.profile, probe, evaluator) if counts == "recommends" else NamesJudge(run.profile)


def marker(attribute: Attribute, term: Optional[str], quotes: list[str],
           reading: list[ReadStep]) -> Callable[[str], bool]:
    """-> whether a piece of what was read says the claim. The term if there is one; else the words
    the claim's label and the live answers' quotes share, minus any word most results contain (it
    cannot tell one source from another)."""
    if term:
        pattern = term_pattern(term)
        return lambda text: bool(pattern.search(text))
    claim = evaluation.content_words(" ".join([attribute.label, attribute.description or "", *attribute.aliases]))
    said = set().union(*(evaluation.content_words(q) for q in quotes)) if quotes else set()
    words = (claim & said) or claim
    results = [r.text for s in reading for r in s.results]
    common = {w for w in words if sum(w in evaluation.content_words(t) for t in results) > len(results) / 2}
    words = (words - common) or words
    return lambda text: bool(words & evaluation.content_words(text))


# ---------------------------------------------------------------- the calls
class Lab:
    """The three ways the agent asks, each one metered call through access.openai_response, and the
    running spend of all of them. Tests inject `transport`, which receives the create() kwargs."""

    def __init__(self, model: str, tool: Optional[dict] = live.SEARCH_TOOL, transport: Optional[Callable] = None):
        self.model, self.tool = model, tool
        self._transport = transport or (lambda **kw: access.openai_response(live.LIMITS["per_call_timeout_s"], **kw))
        self.spent = 0.0
        self._lock = threading.Lock()

    def call(self, **kw):
        response = self._transport(**{"model": self.model, **kw})
        cost = access.cost(kw.get("model", self.model), response)[0]
        with self._lock:
            self.spent += cost
        return response

    def live(self, question: str):
        return self.call(input=[{"role": "system", "content": live.NEUTRAL_INSTRUCTION},
                                {"role": "user", "content": question}],
                         tools=[self.tool], tool_choice=live.TOOL_CHOICE, include=live.INCLUDE)

    def off(self, question: str):
        return self.call(input=[{"role": "system", "content": OFF_INSTRUCTION}, {"role": "user", "content": question}])

    def replay(self, question: str, reading: list[ReadStep]):
        return self.call(input=replay_input(question, reading), tools=[REPLAY_TOOL], tool_choice="none")

    def judge_transport(self, prompt: str, model: str, timeout: int) -> str:
        """The evaluator's calls, counted against this investigation's budget too."""
        from agents.evaluator_model import _text_from
        r = self.call(model=model, input=prompt)
        return getattr(r, "output_text", None) or _text_from(r)


class OverBudget(Exception):
    pass


class Cancelled(Exception):
    """The fleet stopped waiting for this investigation (its deadline); it stops at the next batch."""


# ---------------------------------------------------------------- the investigation
class Agent:
    def __init__(self, inv: Investigation, lab: Lab, judge: Judge, attribute: Attribute,
                 profile: CompanyProfile, rewrite: Optional[tuple[str, str]] = None,
                 emit: Callable[[str, dict], None] = lambda kind, payload: None,
                 cancel: Optional[threading.Event] = None):
        self.inv, self.lab, self.judge, self.attribute, self.profile = inv, lab, judge, attribute, profile
        self.cancel = cancel
        self.rewrite = rewrite          # (page url, copy) from the run's action plan, if any
        self.emit = emit
        self.readings: dict[str, list[ReadStep]] = {}
        self.per_ask = 0.0              # the running cost of one replay plus its judging

    def note(self, text: str) -> None:
        self.inv.log.append(text)
        self.emit("log", {"text": text, "spent_usd": round(self.lab.spent, 4)})

    def pmap(self, fn, items):
        """fn over items, CONCURRENCY at a time. Each call runs in a copy of THIS thread's context, taken
        here: a pool thread starts with an empty one, so a copy taken inside it would drop the paying
        pass (access.SPENDER) and a fleet's purse, and every call would go unmetered or be refused."""
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            return [f.result() for f in [pool.submit(copy_context().run, fn, x) for x in items]]

    def afford(self, asks: int) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled
        estimate = asks * (self.per_ask or 0.01)
        if self.lab.spent + estimate > self.inv.budget_usd:
            raise OverBudget

    # -- asking
    def ask_replays(self, arm: WhyArm, upto: int) -> None:
        need = upto - arm.n
        if need <= 0:
            return
        self.afford(need)
        before = self.lab.spent
        texts = self.pmap(lambda _: live.parse_response(self.lab.replay(self.inv.question, self.readings[arm.id]))[0],
                          range(need))
        for states, quote in self.pmap(self.judge, texts):
            if states is None:
                continue
            arm.n += 1
            if states:
                arm.k += 1
                if quote and len(arm.quotes) < 2 and quote not in arm.quotes:
                    arm.quotes.append(quote)
        self.per_ask = (self.lab.spent - before) / need
        self.inv.spent_usd = round(self.lab.spent, 4)

    def room(self, reserve: int = 0) -> int:
        """Experiments still allowed (the base is not one), keeping `reserve` back."""
        return MAX_ARMS - (len(self.inv.arms) - 1) - reserve

    def add(self, arm: WhyArm, reading: list[ReadStep], reserve: int = 0) -> Optional[WhyArm]:
        if self.room(reserve) <= 0:
            self.note(f"No room for “{arm.label}”: the interval is corrected for at most {MAX_ARMS} experiments.")
            return None
        self.readings[arm.id] = reading
        self.inv.arms.append(arm)
        return arm

    @property
    def base(self) -> WhyArm:
        return self.inv.arms[0]

    def test(self, arm: WhyArm) -> WhyArm:
        """Re-ask the arm (and the base beside it) look by look until the effect is decided."""
        for n in LOOKS:
            self.ask_replays(self.base, n)
            self.ask_replays(arm, n)
            if not arm.n or not self.base.n:
                continue
            lo, hi = newcombe(arm.k, arm.n, self.base.k, self.base.n, Z)
            arm.base_k, arm.base_n = self.base.k, self.base.n
            arm.effect = round(arm.k / arm.n - self.base.k / self.base.n, 2)
            arm.interval = [round(lo, 2), round(hi, 2)]
            arm.decided = "effect" if lo > 0 or hi < 0 else "no_effect" if -NO_EFFECT <= lo and hi <= NO_EFFECT else "undecided"
            if arm.decided != "undecided":
                break
        self.emit("arm", arm.model_dump())
        self.note(f"{arm.label}: {arm.k}/{arm.n} against {arm.base_k}/{arm.base_n} — "
                  + {"effect": f"changes it by {arm.effect:+.2f} [{arm.interval[0]:+.2f}, {arm.interval[1]:+.2f}]",
                     "no_effect": "no change",
                     "undecided": "not decided within the asks allowed"}[arm.decided] if arm.interval else f"{arm.label}: not judged")
        return arm

    def verdict(self, kind: str, text: str, arm: Optional[WhyArm] = None, fix: Optional[str] = None) -> None:
        self.inv.verdicts.append(WhyVerdict(kind=kind, text=text, arm_id=arm.id if arm else None, fix=fix))
        self.emit("verdict", self.inv.verdicts[-1].model_dump())

    # -- the steps
    def record(self) -> list[tuple[str, Optional[list[ReadStep]], Optional[bool], Optional[str], list]]:
        self.note(f"Asking live {LIVE_ASKS} times, recording what the model read.")
        self.afford(LIVE_ASKS * 5)
        raws = self.pmap(lambda _: self.lab.live(self.inv.question), range(LIVE_ASKS))
        out = []
        for raw in raws:
            text, _, searched = live.parse_response(raw)
            reading = live.reading_of(raw, cap=READ_CAP) if searched else None
            states, quote = self.judge(text) if text else (None, None)
            out.append((text, reading, states, quote, raw))
        judged = [o for o in out if o[2] is not None]
        self.inv.live = WhyRate(k=sum(o[2] for o in judged), n=len(judged))
        self.inv.live_quotes = [o[3] for o in judged if o[3]][:3]
        self.inv.spent_usd = round(self.lab.spent, 4)
        return out

    def prior(self) -> None:
        texts = self.pmap(lambda _: live.parse_response(self.lab.off(self.inv.question))[0], range(OFF_ASKS))
        judged = [s for s, _ in self.pmap(self.judge, texts) if s is not None]
        self.inv.off = WhyRate(k=sum(judged), n=len(judged))
        self.note(f"With search off it said it in {self.inv.off.k} of {self.inv.off.n} answers: "
                  + ("the model already believes it." if self.inv.off.k else "not something it says from memory."))

    def run(self) -> Investigation:
        inv = self.inv
        try:
            recorded = self.record()
            with_reading = [o for o in recorded if o[1]]
            if not with_reading:
                self.verdict("not_reproducible", "The model answered without searching, so there is no reading list to test.")
                return self.finish("complete")
            self.note(f"Live: stated in {inv.live.k} of {inv.live.n} answers.")
            self.prior()
            chosen = next((o for o in with_reading if o[2]), with_reading[0])
            inv.reading = chosen[1]
            self.cited = self.cited_near(chosen[0], chosen[3], chosen[4])
            base = self.add(WhyArm(id="base", kind="base", label="The recorded reading list, replayed", decided="base"),
                            inv.reading)
            self.ask_replays(base, LOOKS[0])
            # one check, before any experiment: plain 95% on both sides
            live_lo, live_hi = wilson(inv.live.k, inv.live.n)
            base_lo, base_hi = wilson(base.k, base.n)
            if inv.live.n and (base_hi < live_lo or base_lo > live_hi):
                self.verdict("not_reproducible",
                             f"Replayed, what the model read gives the claim in {base.k} of {base.n} answers against "
                             f"{inv.live.k} of {inv.live.n} live, so the answer depends on more than what it read. "
                             "No experiment on the reading list would be a fair test.")
                return self.finish("complete")
            self.note(f"Replayed, the reading list gives it in {base.k} of {base.n}: close enough to live to experiment on.")
            # whether AI says it at all decides which experiments run, so it gets the second look's asks
            self.ask_replays(base, LOOKS[1])
            if base.k:
                self.find_cause(reserve=0 if self.attribute.discovered else FIX_ARMS)
            elif self.attribute.discovered:
                self.verdict("not_said", f"AI does not say it for this question: {inv.live.k} of {inv.live.n} live "
                                         f"answers and {base.k} of {base.n} replays.")
            if not self.attribute.discovered:
                self.test_fixes()
            return self.finish("complete")
        except (OverBudget, access.PurseEmpty) as e:
            limit = f"the fleet's ${e.limit:.2f} budget" if isinstance(e, access.PurseEmpty) else f"the ${inv.budget_usd:.2f} budget"
            self.verdict("budget", f"Stopped at {limit}: {max(0, len(inv.arms) - 1)} experiment(s) "
                                   "ran; what is below is as far as they got.")
            return self.finish("stopped")
        except Cancelled:
            self.verdict("cancelled", f"Stopped at the fleet's deadline: {max(0, len(inv.arms) - 1)} experiment(s) "
                                      "ran; what is below is as far as they got.")
            return self.finish("stopped")

    def finish(self, status: str) -> Investigation:
        self.inv.status = status
        self.inv.spent_usd = round(self.lab.spent, 4)
        return self.inv

    def cited_near(self, text: str, quote: Optional[str], raw) -> list[str]:
        """Pages the answer cites at or right after the sentence that states the claim."""
        at = text.find(quote) if quote else -1
        out = []
        for item in live._output_items(raw):
            for block in (live._item(item, "content", []) or []) if live._item(item, "type") == "message" else []:
                for ann in live._item(block, "annotations", []) or []:
                    if live._item(ann, "type") == "url_citation" and at >= 0 and live._item(ann, "start_index", -1) >= at:
                        out.append(live._item(ann, "url"))
        return [u.split("?utm_source")[0] for u in out[:2]]

    def find_cause(self, reserve: int = 0) -> None:
        inv = self.inv
        says = marker(self.attribute, inv.term, inv.live_quotes, inv.reading)
        own = self.profile.all_domains()
        sources = [u for u in urls_of(inv.reading)
                   if any(says(r.text) for s in inv.reading for r in s.results if r.url == u)]
        if not sources:
            self.verdict("prior_belief" if inv.off.k else "not_in_reading",
                         "Nothing the model read says it, yet it said it"
                         + (": it comes from what the model already believes." if inv.off.k else
                            ". It is the model's own wording, not a source's."))
            return
        rank = lambda u: (not any(u.startswith(c) or c.startswith(u) for c in self.cited),
                          not domain_matches(u, own))
        sources.sort(key=rank)
        self.note(f"{count_pages(sources).capitalize()} in what it read say it; removing them all first.")
        group = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="drop_source", urls=sources,
                                label=f"Removed the {count_pages(sources)} that say it"),
                         drop_sources(inv.reading, set(sources)), reserve)
        if group is None:
            return
        self.test(group)
        if group.decided == "undecided":
            self.verdict("undecided", "Removing the pages that say it may change the answer, but not decidedly "
                                      "within the asks allowed.", group)
            return
        if group.decided == "no_effect":
            self.verdict("prior_belief" if inv.off.k else "not_in_reading",
                         "Removing every page that says it does not stop the model saying it"
                         + (" — and with search off it says it too: it comes from what the model already "
                            "believes, and no page edit can move it." if inv.off.k else
                            ". It is the model's own wording, not a source's."), group)
            return
        if group.effect >= 0:
            self.verdict("not_in_reading", "Removing every page that says it makes the model say it more often, not "
                                           "less: those pages are not why AI says it, they hold it back.", group)
            return
        pages = sources
        while len(pages) > 1:
            half = pages[:len(pages) // 2], pages[len(pages) // 2:]
            found, cleared = None, 0
            for part in half:
                arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="drop_source", urls=list(part),
                                      label="Removed " + ", ".join(page_name(u) for u in part)),
                               drop_sources(inv.reading, set(part)), reserve)
                if arm is None:
                    self.verdict("undecided", f"The {count_pages(pages)} that say it together are the reason ("
                                 + named(pages) + "); there were not enough experiments "
                                 "left to tell which of them.", group)
                    return
                if self.test(arm).decided == "effect" and arm.effect < 0:
                    found = list(part)
                    break
                cleared += arm.decided != "undecided"
            if not found and cleared < len(half):
                self.verdict("undecided", f"The {count_pages(pages)} that say it together are the reason ("
                             + named(pages) + "); removing part of them was not decided "
                             "within the asks allowed.", group)
                return
            if not found:
                self.verdict("over_determined",
                             f"No single source is the reason: {count_pages(pages)} say it and removing any part of them "
                             "leaves the others to say it. " + named(pages) + ".", group)
                return
            pages = found
        cause = pages[0]
        source_arm = next((a for a in reversed(inv.arms) if a.urls == [cause]), group)
        reading, lines = drop_lines(inv.reading, cause, says)
        arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="drop_passage", urls=[cause], text=lines[:4],
                              label=f"Removed only the lines of {page_name(cause)} that say it"), reading, reserve) if lines else None
        if arm and self.test(arm).decided == "effect" and arm.effect < 0:
            self.verdict("caused_by", f"AI says it because of {len(lines)} line(s) of {page_name(cause)}: removing just "
                                      f"them takes it from {arm.base_k}/{arm.base_n} to {arm.k}/{arm.n}.", arm)
        else:
            self.verdict("caused_by", f"AI says it because of {page_name(cause)}: removing it takes it from "
                                      f"{source_arm.base_k}/{source_arm.base_n} to {source_arm.k}/{source_arm.n}.", source_arm)

    def test_fixes(self) -> None:
        """Copy or authority? Put the company's copy first on its page AI already read; add its page
        that states it where search never found it. Neither moving it: the question is not asking."""
        inv = self.inv
        own = self.profile.all_domains()
        read = urls_of(inv.reading)
        # a file in the site's media library (a PDF, an .ashx download) is not a page: it takes no rewrite
        mine = [u for u in read if domain_matches(u, own) and not is_asset(u)]
        copy = self.rewrite[1] if self.rewrite else next(iter(self.attribute.claim_quotes), None)
        if not copy:
            self.note("No rewrite or site quote to test for this claim, so copy and authority were not tested.")
            return
        yours = "your rewrite" if self.rewrite else "your own copy"
        results = []
        if mine:
            # the copy question is "does a page AI reads, and that does not say it yet, move it if it
            # does": a page that already says it only repeats it. Cited pages first.
            says = marker(self.attribute, inv.term, inv.live_quotes, inv.reading)
            silent = [u for u in mine if not any(says(r.text) for s in inv.reading for r in s.results if r.url == u)]
            pool = silent or mine
            target = next((u for u in pool if u in self.cited), pool[0])
            arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="edit", urls=[target], text=[copy],
                                  hypothetical=bool(self.rewrite),
                                  label=f"{yours.capitalize()} leads {page_name(target)}, a page AI already read"),
                           lead_with(inv.reading, target, copy))
            if arm:
                results.append(self.test(arm))
        page, text, hypothetical = next(
            ((e.url, " ".join(qs[:2]), False) for e in self.profile.evidence
             if e.id in self.attribute.claim_evidence_ids and e.url and e.url not in read and not is_asset(e.url)
             and (qs := [q for q in self.attribute.claim_quotes if q in e.excerpt])),
            (self.rewrite[0], self.rewrite[1], True)
            if self.rewrite and self.rewrite[0] not in read and not is_asset(self.rewrite[0]) else (None, None, True))
        if page:
            arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="inject", urls=[page], text=[text],
                                  hypothetical=hypothetical,
                                  label=f"Added {page_name(page)}, your page search never returned"),
                           inject(inv.reading, page, self.profile.name, text))
            if arm:
                results.append(self.test(arm))
        up = [a for a in results if a.decided == "effect" and a.effect > 0]
        if edit := next((a for a in up if a.kind == "edit"), None):
            self.verdict("copy_fix", f"The fix is copy: with {yours} leading {page_name(edit.urls[0])}, AI says it in "
                                     f"{edit.k} of {edit.n} answers against {edit.base_k} of {edit.base_n} — a predicted "
                                     f"{edit.effect:+.0%} ({edit.interval[0]:+.0%} to {edit.interval[1]:+.0%}) once the "
                                     "page is re-crawled.", edit, "copy")
        elif add := next((a for a in up if a.kind == "inject"), None):
            self.verdict("authority_fix", f"The fix is your rewrite and authority: AI says it once it reads your "
                                          f"rewrite on {page_name(add.urls[0])} ({add.k} of {add.n} answers), but search "
                                          "never returned that page for this question. Both are needed: the rewrite on "
                                          "it, and getting it found." if add.hypothetical else
                                          f"The fix is authority: AI says it once it reads {page_name(add.urls[0])} "
                                          f"({add.k} of {add.n} answers), but search never returned that page for this "
                                          "question. Getting it found is the fix, not rewriting it.", add, "authority")
        elif down := next((a for a in results if a.decided == "effect" and a.effect < 0), None):
            where = (f"with {yours} leading {page_name(down.urls[0])}" if down.kind == "edit"
                     else f"once it reads {page_name(down.urls[0])}")
            self.verdict("copy_lowers", f"This copy lowers it: {where}, AI says it in {down.k} of {down.n} answers "
                                        f"against {down.base_k} of {down.base_n} — {down.effect:+.0%} "
                                        f"({down.interval[0]:+.0%} to {down.interval[1]:+.0%}). It is not the fix.",
                         down, "none")
        elif results and all(a.decided == "no_effect" for a in results):
            self.verdict("not_movable", f"No copy moves it on this question: neither {yours} on a page AI reads "
                                        "nor your page that states it changed how often AI says it by a fifth of "
                                        "answers or more. The question is not asking for it.",
                         results[0], "none")
        elif results:
            self.verdict("undecided", "Your copy may move it, but not decidedly within the asks allowed.", results[0])


class RewriteAgent(Agent):
    """A quick win's replay test: does the rewrite make AI name the company for one buyer question?

    The same loop as a claim's investigation, with a different question and a different count: record
    the live reading lists, check a replay agrees with live, then test one arm, the rewrite on its page.
    AI read that page: the rewrite leads it (edit). It did not: the page is added to the search results
    (inject), and a rise then says the rewrite works once the page is found, which is its own job."""

    @property
    def said(self) -> str:
        return "recommended" if self.inv.counts == "recommends" else "named"

    def run(self) -> Investigation:
        inv = self.inv
        name, said = self.profile.name, self.said
        verb = inv.counts
        try:
            recorded = self.record()
            with_reading = [o for o in recorded if o[1]]
            if not with_reading:
                self.verdict("not_reproducible", "The model answered without searching, so there is no reading list to test.")
                return self.finish("complete")
            self.note(f"Live: {said} {name} in {inv.live.k} of {inv.live.n} answers.")
            self.prior()
            # the reading list of an answer that missed the company is the one a fix is for
            chosen = next((o for o in with_reading if o[2] is False), with_reading[0])
            inv.reading = chosen[1]
            base = self.add(WhyArm(id="base", kind="base", label="The recorded reading list, replayed", decided="base"),
                            inv.reading)
            self.ask_replays(base, LOOKS[0])
            live_lo, live_hi = wilson(inv.live.k, inv.live.n)
            base_lo, base_hi = wilson(base.k, base.n)
            if inv.live.n and (base_hi < live_lo or base_lo > live_hi):
                self.verdict("not_reproducible",
                             f"Replayed, what the model read {verb} {name} in {base.k} of {base.n} answers against "
                             f"{inv.live.k} of {inv.live.n} live, so the answer depends on more than what it read. "
                             "No test of the rewrite on the reading list would be fair.")
                return self.finish("complete")
            self.ask_replays(base, LOOKS[1])
            self.note(f"Replayed, the reading list {verb} {name} in {base.k} of {base.n}: close enough to live to test on.")
            self.test_rewrite()
            return self.finish("complete")
        except (OverBudget, access.PurseEmpty) as e:
            limit = f"the fleet's ${e.limit:.2f} budget" if isinstance(e, access.PurseEmpty) else f"the ${inv.budget_usd:.2f} budget"
            self.verdict("budget", f"Stopped at {limit} before the rewrite was decided.")
            return self.finish("stopped")
        except Cancelled:
            self.verdict("cancelled", "Stopped at the deadline before the rewrite was decided.")
            return self.finish("stopped")

    def test_rewrite(self) -> None:
        inv, name = self.inv, self.profile.name
        page, copy = self.rewrite
        read = [u for u in urls_of(inv.reading) if same_page(u, page)]
        if read:
            arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="edit", urls=[read[0]], text=[copy], hypothetical=True,
                                  label=f"Your rewrite leads {page_name(read[0])}, a page AI already read"),
                           lead_with(inv.reading, read[0], copy))
        else:
            arm = self.add(WhyArm(id=f"a{len(inv.arms)}", kind="inject", urls=[page], text=[copy], hypothetical=True,
                                  label=f"Your rewrite on {page_name(page)}, added to what AI's search returned"),
                           inject(inv.reading, page, name, copy))
        self.test(arm)
        rate = f"AI {inv.counts} {name} in {arm.k} of {arm.n} answers against {arm.base_k} of {arm.base_n} without it"
        if arm.decided == "effect" and arm.effect > 0:
            span = f"{arm.effect:+.0%} ({arm.interval[0]:+.0%} to {arm.interval[1]:+.0%})"
            if arm.kind == "edit":
                self.verdict("copy_fix", f"The rewrite works: with it leading {page_name(arm.urls[0])}, {rate}: "
                                         f"{span} once the page is re-crawled.", arm, "copy")
            else:
                self.verdict("authority_fix", f"The rewrite works once AI reads it: with it on {page_name(page)}, {rate}: "
                                              f"{span}. But AI's search did not return that page for this question, "
                                              "so the page also has to be found.", arm, "authority")
        elif arm.decided == "effect":
            self.verdict("copy_lowers", f"The rewrite makes it worse: {rate}, {arm.effect:+.0%} "
                                        f"({arm.interval[0]:+.0%} to {arm.interval[1]:+.0%}). Do not publish it.", arm, "none")
        elif arm.base_n and 1 - arm.base_k / arm.base_n < NO_EFFECT:
            self.verdict("ceiling", f"Already {self.said} in {arm.base_k} of {arm.base_n} replays without the rewrite: "
                                    "this question cannot show a gain.", arm)
        elif arm.decided == "no_effect":
            self.verdict("not_movable", f"The rewrite does not change it: {rate}. What it says is not what this "
                                        f"question needs to {'recommend' if inv.counts == 'recommends' else 'name'} you.",
                         arm, "none")
        else:
            self.verdict("undecided", f"The rewrite may change it, but not decidedly within the asks allowed: {rate}.", arm)


def same_page(a: str, b: str) -> bool:
    key = lambda u: ((urlparse(u).hostname or "").removeprefix("www."), urlparse(u).path.rstrip("/"))
    return key(a) == key(b)


def test_rewrite(run, attribute_id: str, probe_id: str, model: Optional[str] = None, lab: Optional[Lab] = None,
                 evaluator=None, emit: Callable[[str, dict], None] = lambda kind, payload: None,
                 budget_usd: Optional[float] = None, cancel: Optional[threading.Event] = None) -> Investigation:
    """One quick win's replay test: the rewrite for `attribute_id` against the buyer question `probe_id`
    it was written for. -> the Investigation (kind "buyer"), complete or stopped. It counts the gap the
    question has: names, or recommends when the question already named the company."""
    from agents.win_back import verdicts
    action = next((a for a in run.win_back if a.attribute_id == attribute_id), None)
    probe = next((p for p in run.probes if p.id == probe_id), None)
    if action is None or probe is None or probe.kind != "blind" or probe_id not in action.question_ids:
        raise ValueError("only a suggested rewrite, against a buyer question it was written for, can be tested")
    lab = lab or Lab(model or live.model_name(), live.search_tool())
    counts = "recommends" if verdicts(run).get(probe_id) == "named, not recommended" else "names"
    if counts == "recommends" and evaluator is None:
        from agents.evaluator_model import ModelEvaluator
        evaluator = ModelEvaluator(transport=lab.judge_transport)
    judge = buyer_judge(run, probe, counts, evaluator)
    inv = Investigation(id=uuid.uuid4().hex[:10], run_id=run.id, company=run.profile.name, question=probe.text,
                        probe_id=probe_id, attribute_id=attribute_id, claim=action.label, model=lab.model,
                        judge=judge.name, budget_usd=budget_usd or budget(), counts=counts, kind="buyer")
    attribute = next((a for a in run.attributes if a.id == attribute_id), None) or Attribute(id=attribute_id, label=action.label)
    agent = RewriteAgent(inv, lab, judge, attribute, run.profile, rewrite=(action.page_url, action.passage()),
                         emit=emit, cancel=cancel)
    return agent.run()


# A file the site serves from its media library or as a download (Sitecore's /-/media/, an investor
# site's /static-files/, a PDF, an .ashx), not a web page: it can be a source the model read, but it is
# never a page to rewrite or add, and is never called one.
ASSET = re.compile(r"/-/media/|/static-files/|\.(?:pdf|ashx|docx?|pptx?|xlsx?|png|jpe?g|gif|svg|webp|mp4|css|js|xml|json|zip)$",
                   re.I)


def is_asset(url: str) -> bool:
    return bool(ASSET.search(urlparse(url).path))


def page_name(url: str) -> str:
    u = urlparse(url)
    host = (u.hostname or "").removeprefix("www.")
    if is_asset(url):
        name = u.path.rstrip("/").rsplit("/", 1)[-1]
        return f"the {host} document {name if len(name) <= 40 else name[:37] + '…'}"
    path = u.path.rstrip("/")
    return host + (path if len(path) <= 40 else path[:37] + "…")


def named(urls: list[str], limit: int = 4) -> str:
    """The first few sources by name, then how many more: a verdict is read, not scanned."""
    shown = ", ".join(page_name(u) for u in urls[:limit])
    return shown + (f" and {len(urls) - limit} more" if len(urls) > limit else "")


def count_pages(urls: list[str]) -> str:
    """"2 pages and 1 document": sources the model read, named for what they are."""
    docs = sum(map(is_asset, urls))
    parts = [f"{n} {word}{'' if n == 1 else 's'}" for n, word in ((len(urls) - docs, "page"), (docs, "document")) if n]
    return " and ".join(parts)


def start(run, attribute_id: str, question: str, probe_id: Optional[str] = None, term: Optional[str] = None,
          model: Optional[str] = None, lab: Optional[Lab] = None, evaluator=None,
          emit: Callable[[str, dict], None] = lambda kind, payload: None,
          budget_usd: Optional[float] = None, cancel: Optional[threading.Event] = None) -> Investigation:
    """One investigation on a finished live run's claim. -> the Investigation, complete or stopped.
    `budget_usd` overrides WHY_BUDGET_USD (a fleet's re-dispatch with more budget); `cancel` is the
    fleet's flag to stop at the next batch."""
    attribute = next(a for a in run.attributes if a.id == attribute_id)
    lab = lab or Lab(model or live.model_name(), live.search_tool())
    if evaluator is None and not term:
        from agents.evaluator_model import ModelEvaluator
        evaluator = ModelEvaluator(transport=lab.judge_transport)
    judge = Judge(attribute, run.profile, question, term, evaluator, endorse=not attribute.discovered)
    action = next((a for a in run.win_back if a.attribute_id == attribute_id), None)
    inv = Investigation(id=uuid.uuid4().hex[:10], run_id=run.id, company=run.profile.name, question=question,
                        probe_id=probe_id, attribute_id=attribute_id, claim=attribute.label, term=term,
                        model=lab.model, judge=judge.name, budget_usd=budget_usd or budget(),
                        counts="mentions" if term or attribute.discovered else "endorsements")
    agent = Agent(inv, lab, judge, attribute, run.profile,
                  rewrite=(action.page_url, action.passage()) if action else None, emit=emit, cancel=cancel)
    return agent.run()
