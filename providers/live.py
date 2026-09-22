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
from schemas import Answer, Attribute, CompanyProfile, Probe, Topic

KEY_ENV = "OPENAI_API_KEY"
# The model that ANSWERS the questions — the one being measured. The judge is separate
# (EVALUATOR_MODEL, agents/evaluator_model.py). gpt-4o-mini with web search named obscure tools for a
# category leader's own category (a saved tryprofound.com run), so the default is gpt-4.1. Note: the
# *-search-preview models are Chat Completions only and 400 here ("not supported with the Responses
# API"), and gpt-4.1-nano rejects the web_search tool. gpt-4o-mini, gpt-4.1-mini, gpt-4o and gpt-5*
# all take it.
MODEL_ENV = "MEASURED_MODEL"
DEFAULT_MODEL = "gpt-4.1"
# Each buyer question is asked this many times, fresh each time: one ask is one draw from a model
# that answers differently on every run, so visibility is the mean with its range. Brand questions
# are asked once.
TRIES_ENV = "BUYER_TRIES"
DEFAULT_TRIES = 3

LIMITS = dict(max_unique_probes=16, max_probe_retries=4, max_model_attempts=40, concurrency=3,
              per_call_timeout_s=90, investigation_deadline_s=600)

NEUTRAL_INSTRUCTION = ("Answer the user's question as a helpful assistant. Use web search. "
                       "Recommend specific products where appropriate and cite sources.")


def measured_prompt(probe: Probe) -> list[dict]:
    """Fresh context: one fixed neutral instruction + one neutral buyer question. Nothing else."""
    return [{"role": "system", "content": NEUTRAL_INSTRUCTION},
            {"role": "user", "content": probe.text}]


def model_name() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def buyer_tries() -> int:
    """BUYER_TRIES, at least 1; anything unreadable is the default rather than a crash at run time."""
    try:
        return max(1, int(os.environ.get(TRIES_ENV) or DEFAULT_TRIES))
    except ValueError:
        return DEFAULT_TRIES


def status() -> str:
    if not os.environ.get(KEY_ENV):
        return f"Disabled: no {KEY_ENV} configured."
    return f"Ready: OpenAI Responses API, model {model_name()}, web_search enabled."


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


def preflight(model: Optional[str] = None, transport: Optional[Callable] = None) -> None:
    """One trivial call before a run, so an unusable setup fails once with a clear message.

    Without this, a model that cannot take the web_search tool produces N identical 400s — one per
    probe — and the report is an unreadable wall of the same error. Failures are classified on the
    HTTP status and error code, never the message text: OpenAI's 401 body also says
    "invalid_request_error", and its 403 region block also says "not supported".
    """
    model = model or model_name()
    try:
        (transport or default_transport)([{"role": "user", "content": "hi"}], model, 30)
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
                f"access to model {model!r} — not a problem with the model or the key's format.") from e
        if status == 400:
            raise ModelUnsupported(
                f"Model {model!r} cannot be used: it does not accept the Responses API web_search "
                f"tool. Set {MODEL_ENV} to one that does (gpt-4.1, gpt-4o-mini, gpt-4.1-mini, gpt-4o, "
                f"gpt-5-mini, gpt-5.5). Note the *-search-preview models are Chat Completions only. "
                f"({safe_error(e)})") from e
        raise


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


def default_transport(messages: list[dict], model: str, timeout: int):
    import access  # metered: refused at a pass's cap, charged to it after
    return access.openai_response(timeout, model=model, tools=[{"type": "web_search"}], input=messages)


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
                 writer: Optional[Callable] = None):
        if not attributes:
            raise ValueError("live run needs the attribute set being measured")
        self._attributes = attributes
        self._named = named_probes
        self._profile = profile
        self.model = model or model_name()
        self.tries = buyer_tries()
        self._transport = transport or default_transport
        self.evaluator = evaluator          # None -> answers come back unlabelled ("needs review")
        self.calls = 0
        self.skipped_questions: list[str] = []
        self.notes: list[str] = []
        # (label, description, n) -> buyer questions for the category where AI places the company,
        # which is often one nobody wrote questions for (an attribute discovered in the answers)
        self._writer = writer or (lambda label, description, n: buyer_questions_for(label, description, n=n))

    def plan(self, profile: CompanyProfile, placed: Optional[Attribute] = None
             ) -> tuple[list[Topic], list[Probe]]:
        """Buyer questions on two fronts, each with its control question: where AI places the
        company (`placed`, read off the brand answers) and the site's core category. With neither,
        the claims' own buyer questions, as for a company saved before categories existed."""
        from agents.ana import SET_QUESTIONS, blind_probes_for_fronts, blind_probes_from_attributes
        self.notes = []
        questions = list(placed.buyer_questions) if placed else []
        if placed and len(questions) < SET_QUESTIONS:
            try:
                questions += self._writer(placed.label, placed.description, SET_QUESTIONS - len(questions))
            except Exception as e:                  # stated, never swallowed: the front is smaller
                self.notes.append(f"Buyer questions for {placed.label} could not be written "
                                  f"({type(e).__name__}); its own {len(questions)} were asked.")
        if got := blind_probes_for_fronts(profile, placed, questions):
            topics, blind, self.skipped_questions, notes = got
            self.notes += notes
            return topics, blind
        topics, blind, self.skipped_questions = blind_probes_from_attributes(self._attributes, profile)
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

    def answer(self, probe: Probe, try_no: int = 1) -> Answer:
        self.calls += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        base = dict(probe_id=probe.id, provenance="live_api", provider=self.name,
                    model=self.model, collected_at=now, try_no=try_no)
        try:
            raw = self._transport(measured_prompt(probe), self.model,
                                  LIMITS["per_call_timeout_s"])
        except Exception as e:                      # surfaced as a failed answer, never swallowed
            kind = "timeout" if "timeout" in type(e).__name__.lower() else "error"
            return Answer(**base, text="", status=kind, error=safe_error(e),
                          search_executed=False)
        text, citations, searched = parse_response(raw)
        if not text:
            return Answer(**base, text="", status="error", error="empty response",
                          search_executed=searched)
        answer = Answer(**base, text=text, citations=citations, search_executed=searched, status="ok")
        if self.evaluator is not None and self._profile is not None:
            # Agent 3 runs here, on a separate model, seeing the company. The measured call above
            # has already returned, so nothing about the target could have reached it.
            labels = self.evaluator.label(probe, answer, self._attributes, self._profile)
            if labels is not None:
                answer = answer.model_copy(update=dict(evaluator_labels=labels,
                                                       evaluator_model=self.evaluator.model))
        return answer
