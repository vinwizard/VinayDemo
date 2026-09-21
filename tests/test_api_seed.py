"""The preloaded Notion company, the server-only offline fallback, and what the stages are built from.

The UI has no mode switch any more, so two things only the server can guarantee are pinned here:
the seed ships with the repo, and the fixture path is reachable by environment alone — and when it
is used, every event it streams says it is replay.
"""
import json

import pytest
from fastapi import HTTPException

import api.main as main
import fetching
import reports
from agents import onboarding_model


def events(chunks):
    """SSE text -> [(event, payload)]."""
    out = []
    for c in chunks:
        head, data = c.strip().split("\n", 1)
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_the_seed_company_ships_with_the_repo_and_is_weighted():
    seed = reports.load_company(main.SEED_COMPANY)
    assert seed.profile.name == "Notion"
    assert seed.attributes and all(a.claim_quotes for a in seed.attributes)
    assert any(a.intended for a in seed.attributes)          # one click measures it
    assert main.health()["seed_company"] == main.SEED_COMPANY


def test_without_the_env_var_the_seed_never_falls_back_to_fixtures(monkeypatch):
    monkeypatch.delenv(main.OFFLINE_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        main.build_provider("live", company_id=main.SEED_COMPANY)
    assert "OPENAI_API_KEY" in e.value.detail


def test_offline_env_replays_the_seed_and_every_event_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv(main.OFFLINE_ENV, "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)     # no key, no network: still demoable
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    out = events(main.run_events("A", "live", main.SEED_COMPANY))

    nodes = [p for k, p in out if k == "node"]
    answers = [p for k, p in out if k == "answer"]
    assert nodes and all(n["mode"] == "demo_replay" for n in nodes)
    assert answers and all(a["provenance"] == "synthetic" for a in answers)
    planned = nodes[-1]["planned"]
    assert len(answers) == planned["buyer"] + planned["brand"] + planned["followup"]
    kind, done = out[-1]
    assert kind == "done" and done["run"]["mode"] == "demo_replay"


def test_the_offline_env_does_not_reach_any_other_company(monkeypatch):
    monkeypatch.setenv(main.OFFLINE_ENV, "1")
    with pytest.raises(HTTPException):
        main.build_provider("live", company_id="deadbeef")


def test_onboarding_streams_the_crawl_before_the_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "COMPANIES", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(fetching, "fetch_site",
                        lambda url, max_pages: [("https://acme.example/", "we set up in minutes")])
    monkeypatch.setattr(onboarding_model, "default_transport", lambda *_: json.dumps(
        {"name": "Acme", "attributes": [{"id": "fast", "label": "Fast to set up",
                                         "claim_quotes": ["we set up in minutes"]}]}))
    out = events(main.onboard_events("https://acme.example/", "Acme"))
    assert [k for k, _ in out] == ["pages", "company"]
    assert out[0][1]["pages"] == ["https://acme.example/"]
    assert out[1][1]["attributes"][0]["id"] == "fast"


def test_an_onboarding_failure_is_streamed_as_an_error_event(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = events(main.onboard_events("https://acme.example/", "Acme"))
    assert [k for k, _ in out] == ["error"]
    assert "OPENAI_API_KEY" in out[0][1]["message"]
