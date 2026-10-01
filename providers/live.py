"""Live adapter — the measured model. OpenAI Responses API with the web_search tool.

The model under test receives ONE neutral question and a fixed neutral instruction, in a fresh
context, and nothing else. It never sees the company profile, the intended attributes, or any hint
of what is being measured; a model told what you want to hear will say it back to you.

`search_executed` is read from the response, never assumed: the Responses API emits a
`web_search_call` output item when a search actually runs. If that item is absent the answer is
ungrounded, and `scoring.eligible` excludes it from live scores rather than quietly counting it.

Transport is injectable so the whole adapter is testable with no API key and no network.
"""
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, NamedTuple, Optional

import dispatch
import sampler
import sharing
from agents.onboarding_model import buyer_category_for, buyer_questions_for
from schemas import Answer, Attribute, CompanyProfile, Probe, ReadResult, ReadStep, Topic

KEY_ENV = "OPENAI_API_KEY"
# The model that ANSWERS the questions — the one being measured. The judge is separate
# (EVALUATOR_MODEL, agents/evaluator_model.py). It must (a) accept the Responses API web_search tool
# and (b) know the present: gpt-4.1's training stops in 2024, so asked about a 2025-founded brand it
# searched for — and reasoned about — a world that brand was not in yet.
# Checked against OpenAI's model reference on 2026-09-22: gpt-6-luna lists web_search among its
# tools, has a 2026-05-18 knowledge cutoff and costs $0.10/$0.50 per 1M tokens — a twentieth of
# gpt-4.1's input and a sixteenth of its output. It is newer than the pinned SDK's model list
# (openai==3.16.2), but the Responses API takes the model as a plain string, so the client sends it;
# whether the ACCOUNT may call it is only knowable from a real call, which is what `preflight` and
# FALLBACK_MODEL below are for.
# Note: the *-search-preview models are Chat Completions only and 400 here ("not supported with the
# Responses API"), and gpt-4.1-nano rejects the web_search tool.
MODEL_ENV = "MEASURED_MODEL"
DEFAULT_MODEL = "gpt-6-luna"
# Where preflight drops to when the API refuses the model or the tool shape below, for the judge as
# well as the measured model. gpt-5-nano, read from the model reference on 2026-09-22: web_search
# among its tools, $0.05/$0.40 per 1M, and in the pinned SDK's model list. Its knowledge stops in
# May 2024 — the staleness this change was made to escape — but it is only ever reached when the
# account cannot call the real default, and forced search grounds each answer in pages fetched now.
# Never silently: /api/health reports the model and search mode actually in use.
FALLBACK_MODEL = "gpt-5-nano"
# Search is REQUIRED, not merely offered: an answer the model wrote from memory is excluded from
# live scores (scoring.eligible), so an optional search means paying for calls that are then thrown
# away. "required" forces a call to the one tool this adapter passes, which is web_search.
TOOL_CHOICE = "required"
# external_web_access asks for live internet rather than the tool's offline/cache-only mode. The
# pinned SDK documents it as defaulting to true when omitted, so stating it is an assertion, not a
# change of behaviour — and an API that does not know the field is a 400 the fallback catches.
SEARCH_TOOL = {"type": "web_search", "external_web_access": True}
FALLBACK_TOOL = {"type": "web_search"}
# What the model read rides on the same call, at no extra charge: `sources` are the URLs each search
# consulted and `results` the text it was handed — ranked snippets, the window of an opened page,
# the lines a find-in-page matched (reading_of). This is what the why agent replays (why.py).
INCLUDE = ["web_search_call.action.sources", "web_search_call.results"]
# How hard the model thinks before it answers: gpt-6-luna takes none/low/medium (its default)/high
# (model reference, read 2026-10-01). "low" was measured on 26 saved Amgen buyer and 11 brand
# questions: the companies named and the claim verdicts matched the saved answers as closely as a
# re-ask at the default did, at about half the latency (9 s against 15-17 s) and 60% of the cost.
# "none" was no faster (it searched more) and a lighter `search_context_size` changed nothing (WEB.md
# "Why a run takes the time it does"). The judge thinks at "low" too (agents/evaluator_model.py). A
# model outside REASONING_MODELS (gpt-4.1, gpt-4o) is sent no setting: it would refuse the field.
REASONING = {"effort": "low"}
REASONING_MODELS = ("gpt-5", "gpt-6")
# The record of the most recent successful `preflight`, for /api/health and status() only: the
# step-down reason, in words safe to show, and whether any web_search tool is sent at all. A run
# never reads it back — it uses the `Resolved` its own preflight returned, so a concurrent run's
# preflight cannot retarget it. `_search` False is the last resort: the fallback model would not
# take the tool either, so answers come back ungrounded and are excluded from the scores, which the
# report says plainly. No third model is tried — quietly measuring something nobody chose would be
# worse than measuring nothing.
_fallback: Optional[str] = None
_search: bool = True
# How many buyer questions a front asks, and when it may stop, is sampler-lite's (sampler.py): fresh
# questions up to a stated margin at 95%, plus WOBBLE_AUDIT re-asks per front for the wobble.

LIMITS = dict(per_call_timeout_s=90, investigation_deadline_s=600)

NEUTRAL_INSTRUCTION = ("Answer the user's question as a helpful assistant. Use web search. "
                       "Recommend specific products where appropriate and cite sources.")


def reasoning_for(model: str) -> Optional[dict]:
    """The `reasoning` field a call to `model` carries, or None to send none."""
    return REASONING if model.startswith(REASONING_MODELS) else None


def measured_prompt(probe: Probe) -> list[dict]:
    """Fresh context: one fixed neutral instruction + one neutral unbranded question. Nothing else."""
    return [{"role": "system", "content": NEUTRAL_INSTRUCTION},
            {"role": "user", "content": probe.text}]


def configured_model() -> str:
    """What MEASURED_MODEL asks for, before preflight has tried it."""
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def model_name() -> str:
    """The model actually in use: the configured one, or the fallback preflight proved it needed."""
    return FALLBACK_MODEL if _fallback else configured_model()


def search_tool() -> Optional[dict]:
    """The web_search tool as it is actually sent, or None when no tool is sent at all."""
    if not _search:
        return None
    return FALLBACK_TOOL if _fallback else SEARCH_TOOL


def search_mode() -> str:
    """Which search mode is in use, for /api/health and the report."""
    if not _search:
        return "none — answers are ungrounded and excluded from the scores"
    return "web_search" if _fallback else "web_search with external_web_access"


def fallback_reason() -> Optional[str]:
    """Why the fallback model and search mode are in use, or None while the configured pair works."""
    return _fallback


class Resolved(NamedTuple):
    """What one preflight proved: the measured model, the tool sent with it (None: no tool at all),
    the judge model that follows, and why the configured pair was dropped (None if it was not)."""
    model: str
    tool: Optional[dict]
    judge: str
    reason: Optional[str]


def current() -> Resolved:
    """The most recent preflight's record, for a provider built without one."""
    from agents import evaluator_model
    return Resolved(model_name(), search_tool(), evaluator_model.model_name(), _fallback)


def status() -> str:
    if not os.environ.get(KEY_ENV):
        return f"Disabled: no {KEY_ENV} configured."
    required = " required on every answer" if _search else ""
    return (f"Ready: OpenAI Responses API, model {model_name()}, {search_mode()}{required}."
            + (f" {_fallback}" if _fallback else ""))


def available() -> bool:
    return bool(os.environ.get(KEY_ENV))


class PreflightFailed(RuntimeError):
    """A preflight refusal whose message is safe to show the user: it never carries the provider's
    response body, which can quote part of the key back."""


class ModelUnsupported(PreflightFailed):
    """Strictly the 400 a model returns when it will not take the web_search tool."""


class CredentialRejected(PreflightFailed):
    pass


class AccessDenied(PreflightFailed):
    pass


def safe_error(e: Exception) -> str:
    """Exception type and HTTP status only. str(e) is the provider's raw body and is never used."""
    status = getattr(e, "status_code", None)
    return f"{type(e).__name__} (HTTP {status})" if status else type(e).__name__


PING = [{"role": "user", "content": "hi"}]


def preflight(model: Optional[str] = None, transport: Optional[Callable] = None) -> Resolved:
    """One trivial call before a run, so an unusable setup fails once with a clear message.
    -> the pair that worked, which the caller hands to its own provider and judge.

    Without this, a model that cannot take the web_search tool produces N identical 400s — one per
    probe — and the report is an unreadable wall of the same error. Failures are classified on the
    HTTP status and error code, never the message text: OpenAI's 401 body also says
    "invalid_request_error", and its 403 region block also says "not supported".

    A 400 is the one failure worth retrying: it means this model, or this tool shape, is not
    accepted — not that the key, the account or the network is wrong. So it steps down, at most
    twice, and returns where it landed; the run uses that pair, and it is also recorded so
    /api/health reports which model and which search mode is in use.

      1. the configured model, web_search with external_web_access
      2. FALLBACK_MODEL, plain web_search
      3. FALLBACK_MODEL, no tool at all — answers then come back ungrounded and `scoring.eligible`
         excludes them, which the report says plainly. This is deliberately the end of the line: a
         third model nobody chose would be a quiet substitution, and measuring the wrong model is
         worse than measuring nothing.
    """
    from agents import evaluator_model
    model = model or configured_model()

    def step(m: str, tool: Optional[dict]) -> Optional[Exception]:
        """-> None if this pair works, the 400 if it does not; anything else is raised as itself."""
        try:
            if transport:
                transport(PING, m, 30)
            else:
                default_transport(PING, m, 30, tool=tool)
            return None
        except Exception as e:
            status, code = getattr(e, "status_code", None), getattr(e, "code", None)
            if status == 401 or code == "invalid_api_key":
                raise CredentialRejected(
                    f"OpenAI refused your API key ({safe_error(e)}). Check that {KEY_ENV} is correct "
                    f"and has not been revoked.") from e
            if status == 403:
                raise AccessDenied(
                    f"OpenAI refused the request ({safe_error(e)}). This is an account-level refusal — "
                    f"most often OpenAI not serving your country or region, or your project lacking "
                    f"access to model {m!r} — not a problem with the model or the key's format.") from e
            if status != 400:
                raise
            return e

    def done(m: str, tool: Optional[dict], reason: Optional[str]) -> Resolved:
        global _fallback, _search
        _fallback, _search = reason, tool is not None
        return Resolved(m, tool, evaluator_model.judge_for(model if reason else None), reason)

    refused = step(model, SEARCH_TOOL)
    if refused is None:
        return done(model, SEARCH_TOOL, None)
    if step(FALLBACK_MODEL, FALLBACK_TOOL) is None:
        return done(FALLBACK_MODEL, FALLBACK_TOOL,
                    f"OpenAI would not take {model!r} with live web search ({safe_error(refused)}), "
                    f"so this run used {FALLBACK_MODEL!r} with the plain web_search tool instead.")
    if step(FALLBACK_MODEL, None) is None:   # last resort: no tool at all, and nothing is hidden
        return done(FALLBACK_MODEL, None,
                    f"OpenAI would not take {model!r} with live web search, and {FALLBACK_MODEL!r} "
                    f"would not take the web_search tool either ({safe_error(refused)}). This run "
                    f"asked {FALLBACK_MODEL!r} with NO web search, so every answer is ungrounded "
                    f"and excluded from the scores. Set {MODEL_ENV} to a model your account can "
                    f"call with web search to measure anything.")
    raise ModelUnsupported(
        f"Model {model!r} cannot be used, and neither could the fallback {FALLBACK_MODEL!r}, with or "
        f"without the web_search tool. Set {MODEL_ENV} to a model your account can call "
        f"(gpt-6-luna, gpt-5.6-luna, gpt-5-nano, gpt-5.4-mini, gpt-4.1-mini, gpt-4.1). Note the "
        f"*-search-preview models are Chat Completions only. ({safe_error(refused)})")


# ---------------------------------------------------------------- response parsing
def _output_items(response) -> list:
    """Accepts the SDK object or a plain dict, so tests can inject fixtures."""
    if isinstance(response, dict):
        return response.get("output") or []
    return getattr(response, "output", None) or []


def _item(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def parse_response(response) -> tuple[str, list[str], bool]:
    """-> (answer_text, citation_urls, search_executed).

    search_executed is True only when a `web_search_call` item is present. Citations alone do not
    prove a search ran — the model can emit a URL from memory — so the two are read separately.
    """
    text_parts, citations, searched = [], [], False
    for item in _output_items(response):
        itype = _item(item, "type")
        if itype == "web_search_call":
            searched = True
        elif itype == "message":
            for block in _item(item, "content", []) or []:
                if _item(block, "type") in ("output_text", "text", None):
                    text_parts.append(_item(block, "text", "") or "")
                for ann in _item(block, "annotations", []) or []:
                    if _item(ann, "type") == "url_citation":
                        url = _item(ann, "url")
                        if url and url not in citations:
                            citations.append(url)
    return "\n".join(t for t in text_parts if t).strip(), citations, searched


def searches_of(response) -> list[str]:
    """The queries the model actually searched, in order: every web_search_call "search" action.
    Other actions (opening or finding in a page) carry no query and are not searches."""
    out = []
    for item in _output_items(response):
        action = _item(item, "action") if _item(item, "type") == "web_search_call" else None
        if action is not None and _item(action, "type") == "search":
            for q in [_item(action, "query"), *(_item(action, "queries") or [])]:
                if isinstance(q, str) and q.strip() and q.strip() not in out:
                    out.append(q.strip())
    return out


# The Responses API wraps each snippet's citation handle in private-use characters
# ("\ue200cite\ue202turn0search0\ue201") and prefixes a quoting limit; neither is text the page said.
MARKUP = re.compile(r"\ue200[^\ue201]*\ue201\s*|\[wordlim: \d+\]\s*")
CRAWLED = re.compile(r"Crawled: ([^;\n]+);")
TRACE_CAP = 600   # characters of each result a run keeps: enough to show; the why agent keeps its own whole
READ_KINDS = {"search": "search", "open_page": "open_page", "find_in_page": "find_in_page", "find": "find_in_page"}


def reading_of(response, cap: Optional[int] = TRACE_CAP) -> Optional[list[ReadStep]]:
    """-> every web_search_call as a ReadStep, in order, with the text the model was handed; None when
    no search ran. `results` is the record to trust, not `action`: one call can bundle several finds
    while its action names only one of them."""
    steps = []
    for item in _output_items(response):
        if _item(item, "type") != "web_search_call":
            continue
        action = _item(item, "action") or {}
        queries = [q.strip() for q in [_item(action, "query"), *(_item(action, "queries") or [])]
                   if isinstance(q, str) and q.strip()]
        results = []
        for r in _item(item, "results") or []:
            url = _item(r, "url")
            if not isinstance(url, str) or not url:
                continue
            text = MARKUP.sub("", _item(r, "snippet") or _item(r, "text") or "").strip()
            crawled = CRAWLED.search(text)
            results.append(ReadResult(url=url, title=_item(r, "title"), text=text[:cap] if cap else text,
                                      crawled=crawled.group(1).strip() if crawled else None))
        steps.append(ReadStep(kind=READ_KINDS.get(_item(action, "type"), "search"),
                              queries=list(dict.fromkeys(queries)), url=_item(action, "url"),
                              pattern=_item(action, "pattern"), results=results))
    return steps or None


def default_transport(messages: list[dict], model: str, timeout: int,
                      tool: Optional[dict] = SEARCH_TOOL):
    import access  # metered: refused at a pass's cap, charged to it after
    # tool_choice is the whole point of forcing search: with "auto" the model decides, and the
    # answers it decides not to search for are paid for and then excluded from the score.
    extra = dict(tools=[tool], tool_choice=TOOL_CHOICE, include=INCLUDE) if tool else {}
    if reasoning := reasoning_for(model):
        extra["reasoning"] = reasoning
    return access.openai_response(timeout, model=model, input=messages, **extra)


class LiveProvider:
    """Live run on both axes: named probes are answered first, then plan() returns the buyer
    questions for the category those answers place the company in and the site's own category. Every answer is live_api, so a
    live run never mixes measured answers with fixture ones.
    """
    name = "openai"
    scenario = None

    def __init__(self, attributes: list[Attribute], named_probes: list[Probe],
                 profile: Optional[CompanyProfile] = None, model: Optional[str] = None,
                 transport: Optional[Callable] = None, evaluator=None,
                 writer: Optional[Callable] = None, demand: Optional[Callable] = None,
                 categorize: Optional[Callable] = None,
                 retrieval: Optional[Callable] = None, positioning: Optional[Callable] = None,
                 resolved: Optional[Resolved] = None, share=None):
        if not attributes:
            raise ValueError("live run needs the attribute set being measured")
        self._attributes = attributes
        self._named = named_probes
        self._profile = profile
        resolved = resolved or current()
        self.model = model or resolved.model
        # asks go to the process-wide dispatcher, whose LIVE_CONCURRENCY workers every run shares
        self.concurrency = dispatch.live_concurrency()
        self.search_tool = resolved.tool
        self.fallback = resolved.reason
        # sampler-lite (sampler.py) sizes the buyer fronts; a wobble-audited question is asked `tries` times
        self.sampler = True
        self.tries = 1 + sampler.wobble_audit()
        self.repeat_sample = 0
        self.spent = 0.0      # what the measured calls cost, for RUN_BUDGET_USD
        self.asked = 0        # the measured asks in `spent`, each one or two calls
        self._spent_lock = threading.Lock()
        # buyer questions shared with every run in the same category today, and answers reused from
        # the last 24 hours (sharing.py); an injected transport (a test) gets none unless it injects one
        self._share = share if share is not None else (sharing.Store() if transport is None else None)
        self.fresh = False    # a Fresh run reuses nothing (its answers are still kept for later runs)
        self.shared = 0       # answers reused, of which `near` for a near-identical question
        self.near = 0
        # the mode an answer is reused within: the same model, search tool and reasoning effort
        self._mode = json.dumps([self.model, self.search_tool, reasoning_for(self.model)], sort_keys=True)
        self._origin = uuid.uuid4().hex   # this run's own answers are never reused within it
        self._reuse: dict[str, sharing.Hit] = {}   # probe id -> the stored answer its first ask reuses
        self._firsts = 0                  # first asks planned, the reuse cap's denominator
        self._vecs: dict[str, list[float]] = {}   # buyer question -> its embedding
        self._wrote: set[str] = set()     # questions the app's writer wrote: the only ones another pass may reuse
        self._transport = transport or (lambda msgs, model, timeout: default_transport(
            msgs, model, timeout, tool=self.search_tool))
        # run -> RetrievalSim. The real one fetches pages and embeds them, so an injected transport
        # (a test) gets none unless it injects one too.
        if retrieval is None and transport is None:
            import retrieval as sim
            retrieval = sim.simulate
        self.retrieval = retrieval
        if positioning is None and transport is None:  # run -> PositioningMap, embeds like retrieval
            import positioning as pos
            positioning = pos.build
        self.positioning = positioning
        self.evaluator = evaluator          # None -> answers come back unlabelled ("needs review")
        self.calls = 0
        self.skipped_questions: list[str] = []
        self.notes: list[str] = []
        self.missing_fronts: dict[str, str] = {}
        # (label, description, n) -> buyer questions for the category where AI places the company,
        # which is often one nobody wrote questions for (an attribute discovered in the answers)
        self._writer = writer or (lambda label, description, n: buyer_questions_for(label, description, n=n))
        # (label, description) -> the buyer category for where AI places the company. Like
        # retrieval, an injected transport (a test) gets none unless it injects one: the label stands.
        self._categorize = categorize or (buyer_category_for if transport is None else None)
        # demand.ground, or None: every buyer question is the model-written one, as before grounding
        self._demand = demand
        self.demand_notes: list[str] = []
        self._real: dict[str, object] = {}       # question text -> the real demand it came from
        self._aimed: Optional[tuple] = None      # (profile, aiming_front's plan) once plan_aiming ran

    def plan_aiming(self, profile: CompanyProfile) -> tuple[list[Topic], list[Probe]]:
        """The site's own core category and its control, planned before any brand answer is in:
        nothing in it reads one, so the run asks it beside the brand questions. plan() then plans
        the other fronts around it rather than again."""
        topics, blind = self._plan_aiming(profile)
        self._save_pools(topics, blind)
        return topics, blind

    def _plan_aiming(self, profile: CompanyProfile) -> tuple[list[Topic], list[Probe]]:
        from agents.ana import aiming_front
        self.notes = [self.fallback] if self.fallback else []
        self.demand_notes, self._real = [], {}
        aiming = profile.core_category
        if aiming:
            # real ones first: the fronts keep the first `per_front`, so written ones only fill a shortfall
            questions = self._shared(aiming) or [*self._ground(aiming, profile), *profile.category_questions]
            questions += self._written(aiming, "Any product in this category, for the buyer's own situation.",
                                       questions)
            profile = profile.model_copy(update=dict(category_questions=questions))
        topics, blind, skipped, missing = aiming_front(profile)
        blind = [p.model_copy(update=dict(demand=self._real.get(p.text.strip().lower()))) for p in blind]
        self._aimed = (profile, (topics, blind, skipped, missing))
        self.skipped_questions, self.missing_fronts = skipped, missing
        return topics, blind

    def plan(self, profile: CompanyProfile, placed: Optional[Attribute] = None
             ) -> tuple[list[Topic], list[Probe]]:
        """Buyer questions on two fronts, each with its control question: where AI places the
        company (`placed`, read off the brand answers) and the site's core category. The claims'
        own buyer questions fill whatever budget the fronts leave: all of it with neither front.
        After plan_aiming, its front is kept as planned and returned with the rest."""
        from agents.ana import blind_probes_for_fronts, brand_leaks, same_category
        aimed = None
        if self._aimed:
            profile, aimed = self._aimed
        else:
            self._plan_aiming(profile)
            profile, _ = self._aimed
            self._aimed = None   # planned here, all at once: the fronts share one plan, placed first
        aiming = profile.core_category
        placed_as = placed.label if placed else None
        if placed and self._categorize:
            try:
                got = self._categorize(placed.label, placed.description)
                if brand_leaks(got, profile):
                    raise ValueError(f"it named {profile.name}")
                placed_as = got
            except Exception as e:                  # stated: the attribute's label is asked about instead
                self.notes.append(f"No buyer category could be written for where AI places "
                                  f"{profile.name} ({placed.label}: {type(e).__name__}), so its label was used.")
        questions = list(placed.buyer_questions) if placed else []
        if placed and not (aiming and same_category(placed_as, aiming)):
            questions = self._shared(placed_as) or [*self._ground(placed_as, profile), *questions]
        if placed:
            questions += self._written(placed_as, placed.description, questions)
        topics, blind, skipped, self.missing_fronts = blind_probes_for_fronts(
            profile, placed, questions, self._attributes, placed_as, aimed)
        self.skipped_questions = skipped
        blind = [p if p.demand else p.model_copy(update=dict(demand=self._real.get(p.text.strip().lower())))
                 for p in blind]
        self._save_pools(topics, blind)
        return topics, blind

    def _ground(self, category: str, profile: CompanyProfile) -> list[str]:
        """Real searches for the category, heaviest group first; [] with a stated reason if none."""
        if not self._demand:
            return []
        from agents.ana import set_questions
        found, note = self._demand(category, profile, set_questions())
        self.demand_notes.append(note)
        self._real.update({q.strip().lower(): d for q, d in found})
        return [q for q, _ in found]

    def _shared(self, category: str) -> list[str]:
        """Today's questions for this category from another run, if any (sharing.py)."""
        pool = self._share.pool(category) if self._share else []
        if pool:
            self.demand_notes.append(f"{category}: asked the same {len(pool)} questions another run in this "
                                     "category asked today, so their answers are shared too.")
        return pool

    def _written(self, category: str, description: Optional[str], have: list[str]) -> list[str]:
        """What the writer adds to reach a full pool; stated, never swallowed, when it cannot."""
        from agents.ana import set_questions
        if len(have) >= set_questions():
            return []
        try:
            wrote = self._writer(category, description, set_questions() - len(have))
            self._wrote.update(q.strip().lower() for q in wrote)
            return wrote
        except Exception as e:
            self.notes.append(f"Unbranded questions for {category} could not be written "
                              f"({type(e).__name__}); its own {len(have)} were asked.")
            return []

    def _save_pools(self, topics: list[Topic], blind: list[Probe]) -> None:
        if self._share:
            front = {t.id: t for t in topics if t.front and t.kind == "buyer"}
            for label in dict.fromkeys(t.label for t in front.values()):
                self._share.save_pool(label, [p.text for p in blind if p.phase == "baseline"
                                              and p.topic_id in front and front[p.topic_id].label == label])

    def attributes(self) -> list[Attribute]:
        return self._attributes

    def named_probes(self) -> list[Probe]:
        return self._named

    def followup_bank(self) -> dict[str, list[dict]]:
        return {}

    def discover(self, attributes: list[Attribute], answers: list[tuple[Probe, Answer]]):
        """Raw emergent-attribute proposals from the evaluator model, or None when there is none."""
        if self.evaluator is None or self._profile is None:
            return None
        return self.evaluator.discover(self._profile, attributes, answers)

    def win_back(self, prompt: str):
        """Raw action-plan proposals from the evaluator model, or None when there is none."""
        ask = getattr(self.evaluator, "win_back", None)  # a stub evaluator may not offer it
        return ask(prompt) if ask else None

    def _call(self, probe: Probe) -> tuple[object, Optional[Exception]]:
        """One measured call: -> (response, None) or (None, the exception it raised)."""
        with self._spent_lock:
            self.calls += 1
        try:
            raw = self._transport(measured_prompt(probe), self.model, LIMITS["per_call_timeout_s"])
        except Exception as e:                      # surfaced as a failed answer, never swallowed
            with self._spent_lock:                  # what the ledger charged for it counts here too
                self.spent += getattr(e, "billed_usd", 0.0)
            return None, e
        import access
        cost = access.cost(self.model, raw)[0]
        with self._spent_lock:
            self.spent += cost
        return raw, None

    def per_ask(self) -> float:
        """What one measured ask has cost on average, over the asks already made."""
        with self._spent_lock:
            return self.spent / self.asked if self.asked else 0.0

    def plan_reuse(self, jobs: list[tuple[Probe, int]]) -> None:
        """Which of these asks reuse a stored answer instead (sharing.py), decided on the graph thread
        as they are submitted, so a saved run never depends on which worker got there first. Only a
        first ask: a re-ask for the wobble is a fresh draw by definition. A stored answer is reused
        at most once a run and never one this run asked, so no answer counts twice; at most
        sharing.MAX_SHARE of the run's first asks are reused, so each run still samples fresh."""
        if not self._share:
            return
        firsts = [p for p, t in jobs if t == 1 and p.id not in self._reuse]
        buyer = [p.text for p in firsts if p.kind == "blind" and p.phase == "baseline" and p.text not in self._vecs]
        if buyer:
            import embeddings
            try:
                self._vecs.update(zip(buyer, embeddings.embed(buyer)))
            except Exception as e:      # stated: exact reuse still works, near-identical does not
                self.notes.append(f"Buyer questions could not be embedded ({type(e).__name__}), so no answer "
                                  "was reused for a near-identical question.")
        used = {h.id for h in self._reuse.values()}
        for p in firsts:
            self._firsts += 1
            if self.fresh or len(self._reuse) + 1 > sharing.MAX_SHARE * self._firsts:
                continue
            hit = self._share.exact(p.text, self._mode, self._origin, used)
            if hit is None and p.text in self._vecs:
                hit = self._share.near(self._vecs[p.text], self._mode, self._origin, used, sharing.SIMILARITY)
            if hit:
                self._reuse[p.id] = hit
                used.add(hit.id)

    def answer(self, probe: Probe, try_no: int = 1) -> Answer:
        # A first ask plan_reuse matched is answered by the stored answer, judged again below for this
        # run. Every fresh first ask is stored for later runs.
        hit = self._reuse.get(probe.id) if try_no == 1 else None
        if hit:
            with self._spent_lock:
                self.shared += 1
                self.near += hit.similarity is not None
            near = ({} if hit.similarity is None else
                    dict(reused_question=hit.question, reused_similarity=round(hit.similarity, 3)))
            return self._labelled(probe, hit.answer.model_copy(update=dict(probe_id=probe.id, shared=True, **near)))
        answer = self._ask(probe, try_no)
        if self._share and try_no == 1:
            self._share.save(probe.text, answer, self._mode, self._origin, vec=self._vecs.get(probe.text),
                             open=probe.kind == "blind" and probe.phase == "baseline"
                             and probe.text.strip().lower() in self._wrote)
        return self._labelled(probe, answer)

    def _labelled(self, probe: Probe, answer: Answer) -> Answer:
        if answer.status == "ok" and self.evaluator is not None and self._profile is not None:
            # Agent 3 runs here, on a separate model, seeing the company. The measured call above
            # has already returned, so nothing about the target could have reached it.
            labels = self.evaluator.label(probe, answer, self._attributes, self._profile)
            if labels is not None:
                answer = answer.model_copy(update=dict(evaluator_labels=labels,
                                                       evaluator_model=self.evaluator.model))
        return answer

    def _ask(self, probe: Probe, try_no: int) -> Answer:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        base = dict(probe_id=probe.id, provenance="live_api", provider=self.name,
                    model=self.model, collected_at=now, try_no=try_no)
        raw, err = self._call(probe)
        if raw is not None and self.search_tool is not None and not parse_response(raw)[2]:
            # tool_choice asked for a search and none ran. One retry: a model that skips a forced
            # tool once usually searches on the next draw, and an ungrounded answer is excluded from
            # the score anyway (scoring.eligible), so the first call is already spent for nothing.
            again, _ = self._call(probe)
            if again is not None and parse_response(again)[2]:
                raw, err = again, None
        with self._spent_lock:
            self.asked += 1
        if raw is None:
            kind = "timeout" if "timeout" in type(err).__name__.lower() else "error"
            return Answer(**base, text="", status=kind, error=safe_error(err),
                          search_executed=False)
        text, citations, searched = parse_response(raw)
        if not text:
            return Answer(**base, text="", status="error", error="empty response",
                          search_executed=searched)
        return Answer(**base, text=text, citations=citations, search_executed=searched, status="ok",
                      searches=searches_of(raw), trace=reading_of(raw))
