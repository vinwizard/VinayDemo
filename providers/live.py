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

from schemas import Answer, Attribute, CompanyProfile, Probe, Topic

KEY_ENV = "OPENAI_API_KEY"
MODEL_ENV = "LIVE_MODEL"
# Cheap default that is VERIFIED to accept the Responses API web_search tool and to actually invoke
# it on buyer questions. Note: the *-search-preview models are Chat Completions only and 400 here
# ("not supported with the Responses API"), so they cannot be used. gpt-4.1-nano also rejects the
# tool. Override with LIVE_MODEL (gpt-5.5, gpt-4.1-mini, gpt-4o and gpt-5* all work).
DEFAULT_MODEL = "gpt-4o-mini"

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
                f"tool. Set LIVE_MODEL to one that does (gpt-4o-mini, gpt-4.1-mini, gpt-4o, "
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
    from openai import OpenAI  # imported lazily: the offline demo must not need the SDK
    client = OpenAI(api_key=os.environ[KEY_ENV], timeout=timeout)
    return client.responses.create(model=model, tools=[{"type": "web_search"}], input=messages)


class LiveProvider:
    """Live run on both axes: plan() returns the attribute-derived blind probes and the perception
    topic, and named probes are answered by the measured model too. Every answer is live_api, so a
    live run never mixes measured answers with fixture ones.
    """
    name = "openai"
    scenario = None
    concurrency = LIMITS["concurrency"]

    def __init__(self, attributes: list[Attribute], named_probes: list[Probe],
                 profile: Optional[CompanyProfile] = None, model: Optional[str] = None,
                 transport: Optional[Callable] = None, evaluator=None):
        if not attributes:
            raise ValueError("live run needs the attribute set being measured")
        self._attributes = attributes
        self._named = named_probes
        self._profile = profile
        self.model = model or model_name()
        self._transport = transport or default_transport
        self.evaluator = evaluator          # None -> answers come back unlabelled ("needs review")
        self.calls = 0
        self.skipped_questions: list[str] = []

    def plan(self, profile: CompanyProfile) -> tuple[list[Topic], list[Probe]]:
        """Both axes: attribute-derived blind probes (placebo) plus the perception container."""
        from agents.ana import blind_probes_from_attributes
        topics, blind, self.skipped_questions = blind_probes_from_attributes(self._attributes, profile)
        perception = Topic(id="perception", label="Brand perception", kind="perception",
                           buyer_need="How AI characterises the brand when asked about it directly",
                           positioning_point_ids=[], fit="strong")
        return topics + [perception], blind

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

    def answer(self, probe: Probe) -> Answer:
        self.calls += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        base = dict(probe_id=probe.id, provenance="live_api", provider=self.name,
                    model=self.model, collected_at=now)
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
