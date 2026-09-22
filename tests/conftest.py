"""No test reaches the network or the real data directory: the real-demand fetch refuses and its
harvests cache in a temp dir; the retrieval simulation skips the pages it would fetch, the
embeddings call returns fixed vectors, and their cache lives in the test's own tmp_path. A test
that exercises one of these replaces the stub itself."""
import hashlib

import pytest

import access
import demand
import embeddings
import retrieval


@pytest.fixture(autouse=True)
def no_demand_network(tmp_path, monkeypatch):
    def refuse(url):
        raise ConnectionError("no network in tests")
    monkeypatch.setattr(demand, "_fetch_json", refuse)
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
