"""Onboarding end to end with the sources the name-first flow adds: search copies of a site that
turns our reader away, third-party pages kept apart, and uploaded documents. The search responses
are recorded (tests/discovery_fixtures/), the extraction model is a stub, nothing reaches the network."""
import json

import pytest
from fastapi.testclient import TestClient

import access
import api.main as main
import discovery
import fetching
import reports
from agents import onboarding_model
from providers import live
from test_discovery import recorded
from test_documents import make_pdf

SITE_QUOTE = "Find reliable sources on the web. Get verifiable, straightforward answers to any question"
DOC_QUOTE = "Harbor Loom bakes sourdough for cafes"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DATA", tmp_path)
    monkeypatch.setattr(reports, "COMPANIES", tmp_path / "companies")
    monkeypatch.setenv(live.KEY_ENV, "test-key")
    prompts = []

    def extraction(prompt, model, timeout):
        prompts.append(prompt)
        claims = [("web_answers", "Verifiable web answers", SITE_QUOTE,
                   "{n} finds reliable sources on the web and gives verifiable answers to any question."),
                  ("early_bread", "Sourdough for cafes", DOC_QUOTE,
                   "{n} bakes sourdough for cafes and delivers it before six every morning.")]
        return json.dumps({"name": "Acme", "attributes": [
            {"id": i, "label": label, "description": d.format(n="Acme"), "claim_quotes": {"1": q}}
            for i, label, q, d in claims]})
    monkeypatch.setattr(onboarding_model, "default_transport", extraction)
    return prompts


def blocked_site(url, max_pages):
    raise fetching.FetchError("www.perplexity.ai turns automated readers away (HTTP 403 for https://www.perplexity.ai/)")


def test_a_site_that_turns_us_away_is_onboarded_from_search_copies(env, monkeypatch):
    monkeypatch.setattr(fetching, "fetch_site", blocked_site)
    monkeypatch.setattr(fetching, "fetch", lambda url: blocked_site(url, 0))
    monkeypatch.setattr(discovery, "default_transport", recorded("gather-perplexity"))
    out = main.onboard(url="perplexity.ai", name="Perplexity")
    kinds = {s["kind"] for s in out["sources"]}
    assert kinds == {"search_copy"} and all(s["saved"] for s in out["sources"])
    assert out["pages"] == [s["url"] for s in out["sources"]]         # the audit re-reads them all
    assert [a["id"] for a in out["attributes"]] == ["web_answers"]      # its quote is on a search copy
    # third-party pages are shown, and never reach the extraction model
    assert "https://en.wikipedia.org/wiki/Perplexity_AI" in [t["url"] for t in out["third_party"]]
    assert "wikipedia.org" not in env[0] and "reddit.com" not in env[0]
    assert any("search copies" in w and "turns automated readers away" in w for w in out["warnings"])
    saved = reports.load_company(out["id"])
    assert {e.source_type for e in saved.profile.evidence} == {"search_copy"}
    assert {e.source_type for e in saved.third_party} == {"third_party"}


def test_a_site_that_cannot_be_read_at_all_says_why_in_plain_words(env, monkeypatch):
    """Reproduced 2026-09-28: a link that timed out showed "Onboarding failed: TimeoutError"."""
    def timeout(url, max_pages):
        raise fetching.FetchError("anthropic.co did not answer within 10 seconds")
    monkeypatch.setattr(fetching, "fetch_site", timeout)
    events = "".join(main.onboard_events("http://anthropic.co", "Anthropic"))
    assert "Could not read anthropic.co: anthropic.co did not answer within 10 seconds" in events
    assert "Web search is not available right now" in events and "Upload documents" in events
    assert "TimeoutError" not in events


def test_a_company_with_no_website_is_onboarded_from_its_documents(env):
    client = TestClient(main.app, raise_server_exceptions=False)
    doc = client.post("/api/onboard/documents?filename=positioning.pdf",
                      content=make_pdf(DOC_QUOTE + " and delivers before 6am.")).json()
    assert doc["filename"] == "positioning.pdf" and doc["chars"] > 0
    out = client.get(f"/api/onboard?name=Harbor%20Loom&docs={doc['id']}").json()
    assert out["profile"]["domain"] == "" and out["pages"] == [] and out["audit"] is None
    assert out["sources"] == [dict(url=None, title="positioning.pdf", kind="uploaded_document",
                                   saved=None, private=True)]
    [claim] = out["attributes"]
    assert claim["id"] == "early_bread" and claim["private_only"]      # AI can read none of it
    assert "uploaded document: positioning.pdf" in env[0]


def test_documents_add_to_the_site_and_only_their_own_claims_are_private(env, monkeypatch):
    monkeypatch.setattr(fetching, "fetch_site", lambda url, max_pages: (
        [(f"https://acme.example/{p}", f"Acme. {SITE_QUOTE}.") for p in ("", "about", "product")], None))
    doc = main.documents.save(None, "plan.txt", DOC_QUOTE.encode())
    out = main.onboard(url="acme.example", name="Acme", docs=doc["id"])
    assert [s["kind"] for s in out["sources"]] == ["page_fetch"] * 3 + ["uploaded_document"]
    assert {a["id"]: a["private_only"] for a in out["attributes"]} == {"web_answers": False, "early_bread": True}
    assert [c["attribute_id"] for c in out["audit"]["claims"]] == ["web_answers"]   # no page holds the other


def test_only_my_documents_leaves_the_website_unread(env, monkeypatch):
    monkeypatch.setattr(fetching, "fetch_site", lambda *a, **k: pytest.fail("the site was read"))
    doc = main.documents.save(None, "plan.txt", DOC_QUOTE.encode())
    out = main.onboard(url="https://www.acme.example/", name="Acme", docs=doc["id"], only_docs=True)
    assert out["profile"]["domain"] == "acme.example" and out["pages"] == []


@pytest.mark.parametrize("query,words", [
    ("", "find it by name, or upload documents"),
    ("url=acme.example&only_docs=true", "Upload at least one document"),
    ("docs=0123456789", "no longer available"),
])
def test_onboarding_says_what_is_missing(env, query, words):
    r = TestClient(main.app).get(f"/api/onboard?{query}")
    assert r.status_code == 400 and words in r.json()["detail"]


def test_find_offers_the_companies_a_name_could_mean(env, monkeypatch):
    monkeypatch.setattr(discovery, "default_transport", recorded("find-mercury"))
    r = TestClient(main.app).get("/api/onboard/find?name=Mercury")
    assert [c["domain"] for c in r.json()["candidates"]] == ["mercury.com", "mercuryinsurance.com"]


def test_find_needs_a_key_and_on_the_public_demo_a_pass(env, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.delenv(live.KEY_ENV)
    assert "Enter the company's website instead" in client.get("/api/onboard/find?name=Acme").json()["detail"]
    monkeypatch.setenv(access.PUBLIC_ENV, "1")
    assert client.get("/api/onboard/find?name=Acme").status_code == 403
    assert client.post("/api/onboard/documents?filename=a.txt", content=b"text").status_code == 403


def test_an_upload_too_large_or_unreadable_is_refused_in_plain_words(env):
    client = TestClient(main.app)
    big = client.post("/api/onboard/documents?filename=big.txt", content=b"a" * (main.documents.MAX_BYTES + 1))
    assert big.status_code == 413 and "larger than 10 MB" in big.json()["detail"]
    scan = client.post("/api/onboard/documents?filename=deck.pdf", content=make_pdf())
    assert scan.status_code == 422 and "scanned images" in scan.json()["detail"]
