"""No test reaches the network or the real data directory: the site audit's and real demand's one
fetch functions refuse, unless a test records responses; demand harvests cache in a temp dir; the
retrieval simulation skips the pages it would fetch, the embeddings call returns fixed vectors, and
their cache lives in the test's own tmp_path. A test that exercises one of these replaces the stub
itself.

Nor does any test read the developer's own settings: a real `.env` — loaded on import by
`api.main` — would otherwise decide what the model and budget tests assert. A machine with
EVALUATOR_MODEL pinned in .env failed `test_health_names_...` while CI passed, which is the wrong
way round for a check whose whole job is to pin the defaults."""
import hashlib

import pytest

import access
import audit
import demand
import embeddings
import retrieval

# Every setting the app reads from the environment (providers/live.py, agents/*_model.py,
# agents/ana.py). A test that wants one sets it itself with monkeypatch.
APP_SETTINGS = ("MEASURED_MODEL", "EVALUATOR_MODEL", "ONBOARDING_MODEL", "LIVE_MODEL",
                "BUYER_QUESTIONS", "REPEAT_SAMPLE", "BUYER_TRIES", "OPENAI_API_KEY", "DATA_DIR",
                "VISEXP_PUBLIC_DEMO", "VISEXP_OFFLINE_REPLAY")


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    """The defaults in the code, not whatever this machine happens to have exported or put in .env."""
    for name in APP_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_network(tmp_path, monkeypatch):
    def refuse(url, accept=None):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(audit, "get", refuse)

    def refuse_demand(url):
        raise ConnectionError("no network in tests")
    monkeypatch.setattr(demand, "_fetch_json", refuse_demand)
    monkeypatch.setattr(demand, "_cache", lambda category, real=demand._cache: tmp_path / "demand" / real(category).name)


def fake_vector(text: str) -> list[float]:
    return [b / 255 for b in hashlib.sha256(text.encode()).digest()[:8]]


def fake_embed(timeout, **kw):
    return {"data": [{"embedding": fake_vector(t)} for t in kw["input"]],
            "usage": {"prompt_tokens": 10 * len(kw["input"]), "total_tokens": 10 * len(kw["input"])}}


def offline_page(url):
    raise retrieval.Skipped("offline test")


@pytest.fixture(autouse=True)
def offline_retrieval(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "read_page", offline_page)
    monkeypatch.setattr(access, "_embed", fake_embed)
    monkeypatch.setattr(embeddings, "_path", lambda: tmp_path / "embeddings.db")
