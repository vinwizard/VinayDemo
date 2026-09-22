"""No test reaches the network or the real data directory through the retrieval simulation: the
pages it would fetch are skipped, the embeddings call returns fixed vectors, and their cache lives in
the test's own tmp_path. A test that exercises one of these replaces the stub itself."""
import hashlib

import pytest

import access
import embeddings
import retrieval


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
