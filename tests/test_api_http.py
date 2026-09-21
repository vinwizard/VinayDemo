"""The API over HTTP, through fastapi's TestClient: routing, status codes, JSON and SSE on the wire.

test_api_stream.py and test_api_seed.py call the stream generators directly; this file is the only
one that goes through the ASGI app, so it covers the endpoints those do not — and the two intent
rules on PATCH /api/companies/{id} that the product rests on:
  * intent weights are the customer's input, never derived: a zero on an extracted claim means
    not intended;
  * a claim the customer ADDED is intended by construction: it can never be stored as unintended.
Every test runs against tmp_path copies of data/companies and data/runs, with no network.
"""
import json

import pytest
from fastapi.testclient import TestClient

import api.main as main
import reports
from agents import onboarding_model
from providers import live

SENTINEL = "sk-SENTINEL-do-not-leak-7f3a9c"
CO = "abcdef0123"            # a copy of the seed company under an id with no offline special case


@pytest.fixture
def client(tmp_path, monkeypatch):
    companies, runs = tmp_path / "companies", tmp_path / "runs"
    companies.mkdir()
    runs.mkdir()
    seed = json.loads((reports.COMPANIES / f"{main.SEED_COMPANY}.json").read_text())
    (companies / f"{CO}.json").write_text(json.dumps(seed | {"id": CO}))
    monkeypatch.setattr(reports, "COMPANIES", companies)
    monkeypatch.setattr(reports, "RUNS", runs)
    monkeypatch.setattr(main, "RUNS", runs)          # list_all globs its own imported name
    monkeypatch.delenv(main.OFFLINE_ENV, raising=False)
    monkeypatch.delenv(live.KEY_ENV, raising=False)  # api.main loaded any local .env at import
    # an unexpected model call fails loudly instead of reaching the network
    monkeypatch.setattr(onboarding_model, "default_transport",
                        lambda *_: pytest.fail("unexpected model call"))
    return TestClient(main.app, raise_server_exceptions=False)


def weights(body):
    return {a["id"]: a["intended_weight"] for a in body["attributes"]}


def added_by_user(body):
    return {a["id"] for a in body["attributes"] if a["added_by_user"]}


# --- health ---------------------------------------------------------------------------------------

def test_health_without_a_key_says_live_is_unavailable(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["live_available"] is False
    assert body["measured_model"] is None and body["evaluator_model"] is None
    assert body["seed_company"] == main.SEED_COMPANY


def test_health_with_a_key_reports_availability_never_the_key(client, monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, SENTINEL)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["live_available"] is True
    assert SENTINEL not in r.text
    assert SENTINEL[3:] not in r.text        # not even with its prefix trimmed


# --- runs -----------------------------------------------------------------------------------------

def sse_events(text):
    out = []
    for block in text.strip().split("\n\n"):
        head, data = block.split("\n", 1)
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_a_run_streamed_over_http_is_listed_and_reopens(client):
    with client.stream("GET", "/api/stream", params={"scenario": "A"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = sse_events(r.read().decode())
    assert evs[-1][0] == "done"
    run = evs[-1][1]["run"]

    listed = client.get("/api/runs")
    assert listed.status_code == 200
    assert [x["id"] for x in listed.json()] == [run["id"]]
    assert listed.json()[0]["alignment"] == 21.4

    got = client.get(f"/api/runs/{run['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == run["id"] and got.json()["mode"] == "demo_replay"


def test_runs_list_is_empty_with_no_saved_runs(client):
    r = client.get("/api/runs")
    assert r.status_code == 200 and r.json() == []


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/0123456789").status_code == 404


def test_malformed_run_id_is_404_not_500(client):
    assert client.get("/api/runs/not-a-run").status_code == 404


# --- companies ------------------------------------------------------------------------------------

def test_companies_list_and_get(client):
    r = client.get("/api/companies")
    assert r.status_code == 200
    [row] = r.json()
    assert row["id"] == CO and row["name"] == "Notion" and row["intended"] == 4

    got = client.get(f"/api/companies/{CO}")
    assert got.status_code == 200
    assert got.json()["id"] == CO and got.json()["replay"] is False


@pytest.mark.parametrize("cid", ["0123456789", "not-a-company"])
def test_unknown_company_is_404(client, cid):
    assert client.get(f"/api/companies/{cid}").status_code == 404
    assert client.patch(f"/api/companies/{cid}", json={}).status_code == 404
    assert client.delete(f"/api/companies/{cid}/attributes/ai_tools").status_code == 404


# --- PATCH: intent is the customer's, and adding a claim is intending it --------------------------

def test_an_empty_patch_derives_no_intent(client):
    before = weights(client.get(f"/api/companies/{CO}").json())
    r = client.patch(f"/api/companies/{CO}", json={})
    assert r.status_code == 200
    assert weights(r.json()) == before
    assert weights(r.json())["meeting_notes"] is None        # untouched stays unintended


def test_zero_on_an_extracted_claim_means_not_intended_and_persists(client):
    r = client.patch(f"/api/companies/{CO}", json={"weights": {"ai_tools": 0, "meeting_notes": 0.3}})
    assert r.status_code == 200
    w = weights(client.get(f"/api/companies/{CO}").json())   # re-read from disk, not the echo
    assert w["ai_tools"] is None                            # zero is "not intended", not 0.0
    assert w["meeting_notes"] == 0.3
    assert w["knowledge_base"] == 1.0                       # only what was sent changed
    assert reports.load_company(CO).attributes[0].intended is False


def test_patch_rejects_out_of_range_and_unknown_weights_without_saving(client):
    before = weights(client.get(f"/api/companies/{CO}").json())
    assert client.patch(f"/api/companies/{CO}", json={"weights": {"ai_tools": 1.5}}).status_code == 400
    assert client.patch(f"/api/companies/{CO}", json={"weights": {"ai_tools": -0.1}}).status_code == 400
    assert client.patch(f"/api/companies/{CO}", json={"weights": {"nope": 0.5}}).status_code == 400
    assert weights(client.get(f"/api/companies/{CO}").json()) == before


def add(client, **attr):
    r = client.patch(f"/api/companies/{CO}", json={"added": [attr]})
    assert r.status_code == 200, r.text
    [new] = added_by_user(r.json())
    return new, r.json()


def test_an_added_claim_is_intended_by_default(client):
    aid, body = add(client, label="Offline first")
    assert aid == "offline_first"
    assert weights(body)[aid] == 0.5
    stored = next(a for a in reports.load_company(CO).attributes if a.id == aid)
    assert stored.added_by_user and stored.intended
    # no key: still added, measured on the brand axis only, and the omission is stated
    assert stored.buyer_questions == []
    assert any("Offline first" in w and live.KEY_ENV in w for w in body["warnings"])


@pytest.mark.parametrize("weight", [0, 0.05])
def test_an_added_claim_cannot_be_created_unintended(client, weight):
    r = client.patch(f"/api/companies/{CO}", json={"added": [{"label": "Offline first",
                                                             "intended_weight": weight}]})
    assert r.status_code == 422
    assert not added_by_user(client.get(f"/api/companies/{CO}").json())


@pytest.mark.parametrize("weight", [0, 0.05])
def test_an_added_claim_cannot_be_patched_to_unintended(client, weight):
    aid, _ = add(client, label="Offline first", intended_weight=0.8)
    r = client.patch(f"/api/companies/{CO}", json={"weights": {aid: weight}})
    assert r.status_code == 400
    assert "Delete it" in r.json()["detail"]
    assert weights(client.get(f"/api/companies/{CO}").json())[aid] == 0.8   # nothing stored


def test_an_added_claim_gets_vetted_buyer_questions_with_a_key(client, monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, SENTINEL)
    monkeypatch.setattr(onboarding_model, "default_transport", lambda *_: json.dumps(
        {"buyer_questions": ["Which note apps work without a connection?",
                             "Is Notion good offline?"]}))           # names the brand: dropped
    aid, body = add(client, label="Offline first")
    attr = next(a for a in body["attributes"] if a["id"] == aid)
    assert attr["buyer_questions"] == ["Which note apps work without a connection?"]
    assert SENTINEL not in json.dumps(body)


# --- DELETE: removal is how an added claim is dropped --------------------------------------------

def test_delete_removes_an_added_claim(client):
    aid, _ = add(client, label="Offline first")
    r = client.delete(f"/api/companies/{CO}/attributes/{aid}")
    assert r.status_code == 200
    assert aid not in weights(r.json())
    assert aid not in {a.id for a in reports.load_company(CO).attributes}


def test_delete_refuses_an_extracted_claim(client):
    r = client.delete(f"/api/companies/{CO}/attributes/ai_tools")
    assert r.status_code == 400
    assert "ai_tools" in weights(client.get(f"/api/companies/{CO}").json())


def test_delete_of_an_unknown_attribute_is_404(client):
    assert client.delete(f"/api/companies/{CO}/attributes/nope").status_code == 404


# --- the key never leaves the server --------------------------------------------------------------

def test_the_key_appears_in_no_response_body_or_header(client, monkeypatch):
    monkeypatch.setenv(live.KEY_ENV, SENTINEL)

    def leaky(*_):          # a provider error that echoes the key must not reach the browser
        raise RuntimeError(f"401 invalid api key {SENTINEL}")

    monkeypatch.setattr(onboarding_model, "default_transport", leaky)
    responses = [
        client.get("/api/health"),
        client.get("/api/runs"),
        client.get("/api/runs/0123456789"),
        client.get("/api/runs/not-a-run"),
        client.get("/api/companies"),
        client.get(f"/api/companies/{CO}"),
        client.get("/api/companies/0123456789"),
        client.patch(f"/api/companies/{CO}", json={"weights": {"meeting_notes": 0.4}}),
        client.patch(f"/api/companies/{CO}", json={"weights": {"ai_tools": 7}}),
        client.patch(f"/api/companies/{CO}", json={"added": [{"label": "Offline first"}]}),
        client.patch(f"/api/companies/{CO}", json={"added": [{"label": "x", "intended_weight": 0}]}),
        client.delete(f"/api/companies/{CO}/attributes/offline_first"),
        client.delete(f"/api/companies/{CO}/attributes/nope"),
        client.get("/api/stream", params={"scenario": "A"}),
    ]
    assert responses[9].status_code == 200           # the leaky generation failed soft
    for r in responses:
        assert SENTINEL not in r.text, r.request.url
        assert not any(SENTINEL in f"{k}: {v}" for k, v in r.headers.items()), r.request.url


def test_a_failure_during_a_run_streams_without_its_detail(client, monkeypatch):
    from providers import fixture

    def build(mode, scenario=None, company_id=None):
        prov = fixture.FixtureProvider("A")

        def answer(probe):
            raise RuntimeError(f"401 invalid api key {SENTINEL}")

        prov.answer = answer
        return prov, prov.profile, 1, "demo_replay"

    monkeypatch.setattr(main, "build_provider", build)
    r = client.get("/api/stream", params={"scenario": "A"})
    assert sse_events(r.text)[-1][0] == "error"
    assert SENTINEL not in r.text
