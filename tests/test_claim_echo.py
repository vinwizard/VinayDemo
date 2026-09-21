"""Lens 1 (claim echo, no human input) and lens 2 (intent weights re-scored after the run).

A run with no weight set must still produce a report: buyer questions go to the most-stated claims,
claim echo is the headline, zones read against the claims, and alignment is absent with a reason.
Weights set afterwards re-score the saved answers without asking any model.
"""
import json

import pytest
from fastapi.testclient import TestClient

import api.main as main
import graph
import reports
from agents import ana, onboarding_model
from providers import fixture, live
from providers.fixture import FixtureProvider
from schemas import Company


def unweighted(provider):
    attrs = [a.model_copy(update={"intended_weight": None}) for a in provider.attributes()]
    provider.attributes = lambda: [a.model_copy() for a in attrs]
    return provider


def run_scenario(scenario, strip=False):
    p = FixtureProvider(scenario)
    if strip:
        unweighted(p)
    return graph.execute(graph.new_run(p.profile, p), p)


def test_zero_weights_still_plan_buyer_questions_by_claim_prominence():
    c = Company(**json.loads((reports.COMPANIES / f"{main.SEED_COMPANY}.json").read_text()))
    for a in c.attributes:
        a.intended_weight = None
    topics, probes, _ = ana.blind_probes_from_attributes(c.attributes, c.profile)
    assert len(topics) == ana.MAX_TOPICS and probes
    by_pages = sorted((a for a in c.attributes if a.buyer_questions), key=lambda a: -a.claim_pages)
    assert [t.id for t in topics] == [f"pos-{a.id}" for a in by_pages[:ana.MAX_TOPICS]]


def test_weights_still_pick_heaviest_intent_first():
    c = Company(**json.loads((reports.COMPANIES / f"{main.SEED_COMPANY}.json").read_text()))
    topics, _, _ = ana.blind_probes_from_attributes(c.attributes, c.profile)
    weighted = sorted((a for a in c.attributes if a.intended), key=lambda a: -a.intended_weight)
    assert [t.id for t in topics] == [f"pos-{a.id}" for a in weighted[:ana.MAX_TOPICS]]


def test_claim_lens_report_is_not_empty():
    base, run = run_scenario("A"), run_scenario("A", strip=True)
    d = run.drift
    assert d.lens == "claim" and base.drift.lens == "intent"
    assert d.alignment is None and "weighted" in d.na_reasons["alignment"]
    assert d.claim_echo is not None and d.claim_echo == base.drift.claim_echo
    zones = {s.attribute_id: (s.zone, s.owner) for s in d.scores}
    assert "unprioritised" not in {z for z, _ in zones.values()}
    assert zones["connected_docs"] == ("landed", "none")
    assert zones["ai_native"] == ("lost_claim", "authority_gap")      # stated on 6 of 8 pages
    assert zones["enterprise"] == ("lost_claim", "messaging_gap")     # stated on 1 of 8 pages
    assert zones["templates"] == ("imposed", "imposed_identity")


def test_claim_echo_is_prominence_weighted_supportive_echo():
    d = run_scenario("A").drift
    rows = {s.attribute_id: s for s in d.scores}
    claims = [rows[i] for i in ("ai_native", "replaces_stack", "connected_docs", "enterprise")]
    expected = sum(s.claim_pages * s.echo_rate for s in claims) / sum(s.claim_pages for s in claims)
    assert d.claim_echo == pytest.approx(100 * expected, abs=0.1)


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(reports, "RUNS", runs)
    monkeypatch.setattr(main, "RUNS", runs)
    monkeypatch.delenv(live.KEY_ENV, raising=False)
    return TestClient(main.app, raise_server_exceptions=False)


def forbid_model_calls(monkeypatch):
    fail = lambda *a, **k: pytest.fail("re-score must not call a provider or model")
    monkeypatch.setattr(FixtureProvider, "answer", fail)
    monkeypatch.setattr(live.LiveProvider, "answer", fail)
    monkeypatch.setattr(live, "default_transport", fail)
    monkeypatch.setattr(onboarding_model, "default_transport", fail)
    monkeypatch.setattr(main, "build_provider", fail)


def test_rescore_sets_intent_with_zero_provider_calls(client, monkeypatch):
    base = run_scenario("A")
    run = run_scenario("A", strip=True)
    reports.save_run(run)
    forbid_model_calls(monkeypatch)
    calls = fixture.CALLS["answer"]
    weights = {a.id: a.intended_weight for a in FixtureProvider("A").attributes() if a.intended}
    r = client.post(f"/api/runs/{run.id}/rescore", json={"weights": weights})
    assert r.status_code == 200, r.text
    assert fixture.CALLS["answer"] == calls
    d = r.json()["drift"]
    assert d["lens"] == "intent" and d["alignment"] == base.drift.alignment == 21.4
    assert d["claim_echo"] == base.drift.claim_echo
    assert {s["attribute_id"]: s["zone"] for s in d["scores"]} == \
           {s.attribute_id: s.zone for s in base.drift.scores}
    assert len(r.json()["answers"]) == len(run.answers)           # nothing re-asked
    # saved in place, and zeroing every weight returns it to the claim lens
    back = client.post(f"/api/runs/{run.id}/rescore", json={"weights": {k: 0 for k in weights}})
    assert back.json()["drift"]["lens"] == "claim" and back.json()["drift"]["alignment"] is None


def test_rescore_rejects_unknown_attribute_and_missing_run(client):
    run = run_scenario("B", strip=True)
    reports.save_run(run)
    assert client.post(f"/api/runs/{run.id}/rescore", json={"weights": {"nope": 1}}).status_code == 400
    assert client.post("/api/runs/0000000000/rescore", json={"weights": {}}).status_code == 404


def test_rescore_refuses_a_run_saved_before_observations_were_stored(client, monkeypatch):
    run = run_scenario("A", strip=True)
    data = json.loads(run.model_dump_json())
    del data["observations"]
    (reports.RUNS / f"{run.id}.json").write_text(json.dumps(data))
    forbid_model_calls(monkeypatch)
    weights = {a.id: a.intended_weight for a in FixtureProvider("A").attributes() if a.intended}
    r = client.post(f"/api/runs/{run.id}/rescore", json={"weights": weights})
    assert r.status_code == 409 and "measure again" in r.json()["detail"]


def test_rescore_of_empty_but_present_observations(monkeypatch):
    run, n_named = run_scenario("A", strip=True), run_scenario("A").drift.n_named
    run.observations = {}
    forbid_model_calls(monkeypatch)
    weights = {a.id: a.intended_weight for a in FixtureProvider("A").attributes() if a.intended}
    d = graph.rescore(run, weights).drift
    assert d.lens == "intent" and d.n_named == n_named
