"""Optional live adapter — DISABLED. Not implemented or tested: no credentials were available.

When a key is supplied later: verify the provider's current official docs, implement `answer()`
with search grounding, and keep these limits. The measured model receives only
`measured_prompt(probe)` — never the company profile.
"""
import os

from schemas import Probe

KEY_ENV = "GEMINI_API_KEY"
MODEL_ENV = "LIVE_MODEL"
LIMITS = dict(max_unique_probes=16, max_probe_retries=4, max_model_attempts=40, concurrency=3,
              per_call_timeout_s=25, investigation_deadline_s=240)
NEUTRAL_INSTRUCTION = ("Answer the user's question as a helpful assistant. Use web search. "
                       "Recommend specific products where appropriate and cite sources.")


def measured_prompt(probe: Probe) -> list[dict]:
    """Fresh context: one fixed neutral instruction + one neutral buyer question. Nothing else."""
    return [{"role": "system", "content": NEUTRAL_INSTRUCTION}, {"role": "user", "content": probe.text}]


def status() -> str:
    if not os.environ.get(KEY_ENV):
        return f"Disabled: no {KEY_ENV} configured."
    return "Key detected, but the live adapter is not implemented/tested yet; replay only."


def available() -> bool:
    return False  # flip only after implementing and verifying against official docs
