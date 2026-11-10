"""Every OpenAI call in the app: pacing under rate limits, prices, metering, and reading a reply.

`openai_response` and `openai_embedding` are the only doors. Each one asks core/access.py whether the
acting pass may spend (`access.hold`) before the call, waits out a 429 for the whole process, and
charges the usage the response reports afterwards. This module imports access to find who is
paying; access never imports it. Prompts and model choice stay with each caller: the measured model
must get only the neutral question, never the profile the judge sees.
"""
import contextlib
import json
import os
import threading
import time
from typing import Optional

from core import access
from core.schemas import utc_now

# USD per 1M tokens (input, output), OpenAI list prices as of 2026-09-21 for the models this app
# uses or documents (providers/live.py, judge/evaluator_model.py, onboard/onboarding_model.py).
# Cached input is charged at the full input price: overcounting is the safe direction.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    # OpenAI list prices read from the model reference on 2026-09-22, added with the move to a newer,
    # cheaper measured model (providers/live.py). gpt-6-luna is the default for both the measured
    # model and the judge; gpt-5-nano is the preflight fallback for both; the rest are the ones the
    # docs and the preflight message name, so a run on any of them is metered exactly, not estimated.
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
    "text-embedding-3-small": (0.02, 0.00),   # demand.py groups real buyer searches with it
}
UNKNOWN_PRICE = (10.00, 60.00)       # a model missing from the table is charged above all of them
# Per web_search_call. OpenAI lists two tiers (pricing page, read 2026-09-22): `web_search` at
# "$10.00 / 1k calls + Search content tokens billed at model rates", and `web_search_preview`
# (non-reasoning models) at "$25.00 / 1k calls + Search content tokens are free". This app sends
# `web_search` (providers/live.SEARCH_TOOL) and already charges the search content it pulls in as
# input_tokens, so $0.025 was the preview tier's per-call rate charged on top of the standard tier's
# tokens — the same search billed twice. A live run on 2026-09-22 made it the dominant error: 35
# searches charged $0.875 against $0.35 of real usage. Conservatism belongs in UNKNOWN_PRICE and
# UNKNOWN_USAGE, which are guesses; this is a published number.
SEARCH_CALL_USD = 0.01
UNKNOWN_USAGE = (30_000, 4_000)      # tokens charged when a response reports no usage


# ---------------------------------------------------------------- rate limits
# A 429 pauses every call in the process, not just the one refused: the limit is the key's, and the
# calls beside it would only be refused too. The pause is the API's own Retry-After when it sends one.
RATE_LIMIT_RETRIES = 4
MAX_PAUSE_S = 60.0
_calm_at = 0.0                  # time.monotonic() before which no call starts
_calm_lock = threading.Lock()


def rate_limited(e: Exception) -> bool:
    """A 429 that waiting cures. An exhausted quota is a 429 too, and no wait cures it."""
    return getattr(e, "status_code", None) == 429 and getattr(e, "code", None) != "insufficient_quota"


def retry_after(e: Exception) -> Optional[float]:
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    for name, per_s in (("retry-after-ms", 1000), ("retry-after", 1)):
        try:
            return float(headers.get(name)) / per_s
        except (TypeError, ValueError):
            pass
    return None


def pause(seconds: float) -> None:
    global _calm_at
    with _calm_lock:
        _calm_at = max(_calm_at, time.monotonic() + min(max(seconds, 0.0), MAX_PAUSE_S))


def _wait_calm() -> None:
    while (wait := _calm_at - time.monotonic()) > 0:
        time.sleep(wait)


def _call_paced(call, timeout: int, kwargs: dict):
    """`call`, retried after a 429 once the process-wide pause it set has passed."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        _wait_calm()
        try:
            return call(timeout, **kwargs)
        except Exception as e:
            if not rate_limited(e) or attempt == RATE_LIMIT_RETRIES:
                raise
            pause(retry_after(e) or 2.0 ** attempt)


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def cost(model: str, response) -> tuple[float, dict]:
    """-> (usd, ledger fields) from the usage the response reports; estimated when it reports none."""
    usage = _get(response, "usage") if response is not None else None
    tin, tout = (_get(usage, "input_tokens"), _get(usage, "output_tokens")) if usage is not None else (None, None)
    if tin is None and isinstance(_get(usage, "prompt_tokens"), int):   # an embedding reports only its input
        tin, tout = _get(usage, "prompt_tokens"), 0
    estimated = not isinstance(tin, int) or not isinstance(tout, int) or model not in PRICES
    if not isinstance(tin, int) or not isinstance(tout, int):
        tin, tout = UNKNOWN_USAGE
    pin, pout = PRICES.get(model, UNKNOWN_PRICE)
    searches = sum(_get(i, "type") == "web_search_call" for i in (_get(response, "output") or [])) \
        if response is not None else 0
    usd = tin * pin / 1e6 + tout * pout / 1e6 + searches * SEARCH_CALL_USD
    return usd, dict(model=model, input_tokens=tin, output_tokens=tout, searches=searches,
                     estimated=int(estimated))


def charge(pass_id: str, model: str, response) -> float:
    usd, f = cost(model, response)
    with access.db() as c:
        c.execute("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (pass_id, utc_now(), f["model"], f["input_tokens"], f["output_tokens"], f["searches"],
                   usd, f["estimated"]))
    return usd


def _create(timeout: int, **kwargs):
    """The one line in the app that talks to OpenAI. Tests replace it."""
    from openai import OpenAI  # lazy: the offline demo must not need the SDK
    return OpenAI(api_key=os.environ[access.KEY_ENV], timeout=timeout, max_retries=0).responses.create(**kwargs)


def _embed(timeout: int, **kwargs):
    """The one line in the app that asks OpenAI for embeddings. Tests replace it."""
    from openai import OpenAI
    return OpenAI(api_key=os.environ[access.KEY_ENV], timeout=timeout, max_retries=0).embeddings.create(**kwargs)


def openai_embedding(timeout: int, **kwargs):
    """embeddings.create, metered exactly like openai_response."""
    return _metered(_embed, timeout, kwargs)


def openai_response(timeout: int, **kwargs):
    """responses.create, metered: see _metered."""
    return _metered(_create, timeout, kwargs)


def _metered(call, timeout: int, kwargs: dict):
    """A model call refused before the call when the acting pass may not spend, and charged
    to it after. A call that fails without an HTTP status (a timeout, a dropped connection) may
    still have been billed, so it is charged the unknown-usage estimate. Inside a fleet the call
    also draws on its purse: an estimate is held before the call and the real cost settled after.
    A 429 is waited out and retried (`_call_paced`); it was not billed, so nothing is charged for it."""
    pass_id, purse = access.SPENDER.get(), access.PURSE.get()
    guess = estimate(kwargs)
    reserved = access.hold(pass_id, guess)
    try:
        held = purse.take(guess) if purse else 0.0
    except BaseException:
        access.release(pass_id, reserved)
        raise
    usd = 0.0
    bill = (lambda r: charge(pass_id, kwargs["model"], r)) if pass_id else (lambda r: cost(kwargs["model"], r)[0])
    try:
        with purse.slots if purse else contextlib.nullcontext():
            try:
                response = _call_paced(call, timeout, kwargs)
            except Exception as e:
                if getattr(e, "status_code", None) is None:
                    usd = bill(None)
                e.billed_usd = usd   # for the budgets kept beside the ledger (LiveProvider, why.Lab)
                raise
        usd = bill(response)
        return response
    finally:
        access.release(pass_id, reserved)   # after the charge: for a moment both count, never neither
        if purse:
            purse.settle(held, usd)


def estimate(kwargs: dict) -> float:
    """What a call may cost, held before it is made: its input at 3 characters a token, a 2,000-token
    answer, and three searches when it may search. Settled to the reported cost afterwards."""
    pin, pout = PRICES.get(kwargs.get("model"), UNKNOWN_PRICE)
    tokens = len(json.dumps(kwargs.get("input", ""), default=str)) / 3
    searches = 3 * any(isinstance(t, dict) and str(t.get("type", "")).startswith("web_search")
                       for t in kwargs.get("tools") or [])
    return tokens * pin / 1e6 + 2_000 * pout / 1e6 + searches * SEARCH_CALL_USD


def json_object(raw: str, what: str = "evaluator") -> dict:
    """The JSON object in a model's reply, around whatever prose it added. Tolerates a fenced code block."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.lstrip("`")
        text = text[4:] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"{what} returned no JSON object")
    return json.loads(text[start:end + 1])
