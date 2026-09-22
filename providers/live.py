"""Live adapter — the measured model. OpenAI Responses API with the web_search tool.

The model under test receives ONE neutral question and a fixed neutral instruction, in a fresh
context, and nothing else. It never sees the company profile, the intended attributes, or any hint
of what is being measured; a model told what you want to hear will say it back to you.

`search_executed` is read from the response, never assumed: the Responses API emits a
`web_search_call` output item when a search actually runs. If that item is absent the answer is
ungrounded, and `scoring.eligible` excludes it from live scores rather than quietly counting it.

Transport is injectable so the whole adapter is testable with no API key and no network.
"""
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from agents.onboarding_model import buyer_questions_for
from config import setting
from schemas import Answer, Attribute, CompanyProfile, Probe, Topic

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
# Set by `preflight` when it had to drop from the configured pair: the reason, in words safe to
# show, and whether any web_search tool is sent at all. Process-wide on purpose — one deployment
# talks to one account, and every later call in that process must use what was proven to work.
# `_search` False is the last resort: the fallback model would not take the tool either, so answers
# come back ungrounded and are excluded from the scores, which the report says plainly. No third
# model is tried — quietly measuring something nobody chose would be worse than measuring nothing.
_fallback: Optional[str] = None
_search: bool = True
# The buyer budget, spent on distinct questions rather than repeats. Re-asking one question moves
# the number by a few points; different questions disagree by tens, so questions — not tries — are
# what narrows the confidence interval. BUYER_QUESTIONS per front are asked once each; REPEAT_SAMPLE
# of them are also asked BUYER_TRIES times, which is all the wobble estimate needs.
# BUYER_QUESTIONS lives in agents/ana.py, where the questions are planned.
TRIES_ENV = "BUYER_TRIES"
DEFAULT_TRIES = 3
SAMPLE_ENV = "REPEAT_SAMPLE"
DEFAULT_SAMPLE = 2

LIMITS = dict(max_unique_probes=16, max_probe_retries=4, max_model_attempts=40, concurrency=3,
              per_call_timeout_s=90, investigation_deadline_s=600)

NEUTRAL_INSTRUCTION = ("Answer the user's question as a helpful assistant. Use web search. "
                       "Recommend specific products where appropriate and cite sources.")


def measured_prompt(probe: Probe) -> list[dict]:
    """Fresh context: one fixed neutral instruction + one neutral buyer question. Nothing else."""
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


def buyer_tries() -> int:
    """BUYER_TRIES: how many times a repeat-sampled buyer question is asked. At least 1."""
    return setting(TRIES_ENV, DEFAULT_TRIES, floor=1)


def repeat_sample() -> int:
    """REPEAT_SAMPLE: how many buyer questions are asked BUYER_TRIES times instead of once. 0 turns
    repeats off, and with them the wobble estimate."""
    return setting(SAMPLE_ENV, DEFAULT_SAMPLE)


def status() -> str:
    if not os.environ.get(KEY_ENV):
        return f"Disabled: no {KEY_ENV} configured."
    return (f"Ready: OpenAI Responses API, model {model_name()}, {search_mode()} required on every "
            f"answer." + (f" {_fallback}" if _fallback else ""))


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


def preflight(model: Optional[str] = None, transport: Optional[Callable] = None) -> Optional[str]:
    """One trivial call before a run, so an unusable setup fails once with a clear message.
    -> None normally, or the reason the fallback pair is now in use.

    Without this, a model that cannot take the web_search tool produces N identical 400s — one per
    probe — and the report is an unreadable wall of the same error. Failures are classified on the
    HTTP status and error code, never the message text: OpenAI's 401 body also says
    "invalid_request_error", and its 403 region block also says "not supported".

    A 400 is the one failure worth retrying: it means this model, or this tool shape, is not
    accepted — not that the key, the account or the network is wrong. So it steps down, at most
    twice, and records where it landed; every later call in this process uses the pair that actually
    worked, and /api/health reports which model and which search mode that is.

      1. the configured model, web_search with external_web_access
      2. FALLBACK_MODEL, plain web_search
      3. FALLBACK_MODEL, no tool at all — answers then come back ungrounded and `scoring.eligible`
         excludes them, which the report says plainly. This is deliberately the end of the line: a
         third model nobody chose would be a quiet substitution, and measuring the wrong model is
         worse than measuring nothing.
    """
    global _fallback, _search
    _fallback, _search = None, True
    model = model or configured_model()
    call = transport or default_transport

    def step(m: str) -> Optional[Exception]:
        """-> None if this pair works, the 400 if it does not; anything else is raised as itself."""
        try:
            call(PING, m, 30)
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

    try:
        refused = step(model)
        if refused is None:
            return None
        _fallback = (f"OpenAI would not take {model!r} with live web search ({safe_error(refused)}), "
                     f"so this run used {FALLBACK_MODEL!r} with the plain web_search tool instead.")
        if step(FALLBACK_MODEL) is None:   # _fallback is set: default_transport sends FALLBACK_TOOL
            return _fallback
        _search = False                    # last resort: no tool at all, and nothing is hidden
        _fallback = (f"OpenAI would not take {model!r} with live web search, and {FALLBACK_MODEL!r} "
                     f"would not take the web_search tool either ({safe_error(refused)}). This run "
                     f"asked {FALLBACK_MODEL!r} with NO web search, so every answer is ungrounded "
                     f"and excluded from the scores. Set {MODEL_ENV} to a model your account can "
                     f"call with web search to measure anything.")
        if step(FALLBACK_MODEL) is None:
            return _fallback
    except Exception:
        _fallback, _search = None, True    # a failed step-down is never left switched on
        raise
    _fallback, _search = None, True
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


def default_transport(messages: list[dict], model: str, timeout: int, tool=...):
    import access  # metered: refused at a pass's cap, charged to it after
    # tool_choice is the whole point of forcing search: with "auto" the model decides, and the
    # answers it decides not to search for are paid for and then excluded from the score.
    tool = search_tool() if tool is ... else tool
    extra = dict(tools=[tool], tool_choice=TOOL_CHOICE) if tool else {}
    return access.openai_response(timeout, model=model, input=messages, **extra)


class LiveProvider:
    """Live run on both axes: named probes are answered first, then plan() returns the buyer
    questions for the category those answers place the company in and the site's own category. Every answer is live_api, so a
    live run never mixes measured answers with fixture ones.
    """
    name = "openai"
    scenario = None
    concurrency = LIMITS["concurrency"]

    def __init__(self, attributes: list[Attribute], named_probes: list[Probe],
                 profile: Optional[CompanyProfile] = None, model: Optional[str] = None,
                 transport: Optional[Callable] = None, evaluator=None,
                 writer: Optional[Callable] = None, demand: Optional[Callable] = None,
                 retrieval: Optional[Callable] = None, positioning: Optional[Callable] = None):
        if not attributes:
            raise ValueError("live run needs the attribute set being measured")
        self._attributes = attributes
        self._named = named_probes
        self._profile = profile
        # The model, the tool and the reason for them are fixed per run: a concurrent run's preflight
        # rewrites the module state, and must not retarget calls this run already has in flight.
        self.model = model or model_name()
        self.search_tool = search_tool()
        self.fallback = _fallback
        self.tries = buyer_tries()
        self.repeat_sample = repeat_sample()
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
        # demand.ground, or None: every buyer question is the model-written one, as before grounding
        self._demand = demand
        self.demand_notes: list[str] = []

    def plan(self, profile: CompanyProfile, placed: Optional[Attribute] = None
             ) -> tuple[list[Topic], list[Probe]]:
        """Buyer questions on two fronts, each with its control question: where AI places the
        company (`placed`, read off the brand answers) and the site's core category. The claims'
        own buyer questions fill whatever budget the fronts leave: all of it with neither front."""
        from agents.ana import blind_probes_for_fronts, same_category, set_questions
        # A preflight step-down is a caveat on the whole report, not a server-log line: graph puts
        # `notes` into run.log AND run.drift_notes, so it reaches the report's limitations.
        self.notes = [self.fallback] if self.fallback else []
        self.demand_notes = []
        per_front = set_questions()
        real: dict[str, object] = {}              # question text -> the real demand it came from

        def ground(category: str) -> list[str]:
            """Real searches for the category, heaviest group first; [] with a stated reason if none."""
            if not self._demand:
                return []
            found, note = self._demand(category, profile, per_front)
            self.demand_notes.append(note)
            real.update({q.strip().lower(): d for q, d in found})
            return [q for q, _ in found]

        aiming = profile.core_category
        if aiming:
            # real ones first: the fronts keep the first `per_front`, so written ones only fill a shortfall
            profile = profile.model_copy(update=dict(
                category_questions=[*ground(aiming), *profile.category_questions]))
        questions = list(placed.buyer_questions) if placed else []
        if placed and not (aiming and same_category(placed.label, aiming)):
            questions = [*ground(placed.label), *questions]
        if placed and len(questions) < per_front:
            try:
                questions += self._writer(placed.label, placed.description, per_front - len(questions))
            except Exception as e:                  # stated, never swallowed: the front is smaller
                self.notes.append(f"Buyer questions for {placed.label} could not be written "
                                  f"({type(e).__name__}); its own {len(questions)} were asked.")
        topics, blind, self.skipped_questions, self.missing_fronts = blind_probes_for_fronts(
            profile, placed, questions, self._attributes)
        blind = [p.model_copy(update=dict(demand=real.get(p.text.strip().lower()))) for p in blind]
        return topics, blind

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
        self.calls += 1
        try:
            return self._transport(measured_prompt(probe), self.model,
                                   LIMITS["per_call_timeout_s"]), None
        except Exception as e:                      # surfaced as a failed answer, never swallowed
            return None, e

    def answer(self, probe: Probe, try_no: int = 1) -> Answer:
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
        if raw is None:
            kind = "timeout" if "timeout" in type(err).__name__.lower() else "error"
            return Answer(**base, text="", status=kind, error=safe_error(err),
                          search_executed=False)
        text, citations, searched = parse_response(raw)
        if not text:
            return Answer(**base, text="", status="error", error="empty response",
                          search_executed=searched)
        answer = Answer(**base, text=text, citations=citations, search_executed=searched, status="ok",
                        searches=searches_of(raw))
        if self.evaluator is not None and self._profile is not None:
            # Agent 3 runs here, on a separate model, seeing the company. The measured call above
            # has already returned, so nothing about the target could have reached it.
            labels = self.evaluator.label(probe, answer, self._attributes, self._profile)
            if labels is not None:
                answer = answer.model_copy(update=dict(evaluator_labels=labels,
                                                       evaluator_model=self.evaluator.model))
        return answer
