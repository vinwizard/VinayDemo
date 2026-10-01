"""The why agent over HTTP (api/why.py): who may ask, what may be asked, and the record it keeps.
The model is the fake one from test_why; every file lives under tmp_path."""

import pytest
from fastapi.testclient import TestClient

import access
import api.main as main
import reports
import why
from providers import live
from schemas import Probe, Run
from test_why import AI, DIFFERENT, PROFILE, Fake, ai_model
from fakes import sse_events as events

RUN = "a1b2c3d4e5"
NAMED = Probe(id="np-3", topic_id="perception", text="What makes Amgen different from other biotech companies?",
              kind="named", phase="baseline", purpose="perception")


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs, invs = tmp_path / "runs", tmp_path / "investigations"
    runs.mkdir()
    for mod, name, value in ((reports, "DATA", tmp_path), (reports, "RUNS", runs),
                             (reports, "INVESTIGATIONS", invs)):
        monkeypatch.setattr(mod, name, value)
    run = Run(id=RUN, mode="live_api", profile=PROFILE, attributes=[AI], probes=[NAMED], status="complete")
    reports.save_run(run)
    reports.save_run(run.model_copy(update={"id": "0000aaaa11", "mode": "demo_replay"}))
    monkeypatch.setenv(live.KEY_ENV, "test-key")
    monkeypatch.setattr(live, "preflight", lambda: live.Resolved("gpt-6-luna", live.SEARCH_TOOL, "gpt-6-luna", None))
    fake = Fake(DIFFERENT, ai_model())
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: fake(**kw))
    return TestClient(main.app, raise_server_exceptions=False)


def stream(client, **params):
    return events(client.get(f"/api/runs/{params.pop('run', RUN)}/why/stream", params=params).text)


def test_an_investigation_streams_and_is_kept_beside_the_run(client):
    got = stream(client, attribute=AI.id, probe="np-3", term="AI")
    kinds = [k for k, _ in got]
    assert kinds[0] == "start" and kinds[-1] == "done" and "arm" in kinds and "log" in kinds
    assert got[0][1]["budget_usd"] == why.DEFAULT_BUDGET
    inv = got[-1][1]
    assert inv["question"] == NAMED.text and inv["provenance"] == "counterfactual_replay"
    listed = client.get(f"/api/runs/{RUN}/why").json()
    assert [i["id"] for i in listed] == [inv["id"]]
    assert listed[0]["verdicts"] == inv["verdicts"]
    assert reports.load_run(RUN).answers == []    # the run itself is untouched


def test_its_own_question_must_name_the_company_and_not_the_claim(client):
    assert "must name Amgen" in stream(client, attribute=AI.id, question="What makes it different?")[0][1]["message"]
    for question in ["Is it true Amgen uses AI and advanced technology in research and development?",
                     "Does Amgen use AI and advanced technology in research and development?",
                     "Does Amgen use advanced AI technologies for development and research?"]:
        leak = stream(client, attribute=AI.id, question=question)
        assert "names the claim" in leak[0][1]["message"]


def test_only_a_live_run_and_a_known_claim(client):
    assert "Only a live run" in stream(client, run="0000aaaa11", attribute=AI.id, probe="np-3")[0][1]["message"]
    assert "unknown claim" in stream(client, attribute="nope", probe="np-3")[0][1]["message"]
    assert "not a branded question" in stream(client, attribute=AI.id, probe="np-9")[0][1]["message"]


def test_no_key_no_investigation(client, monkeypatch):
    monkeypatch.delenv(live.KEY_ENV)
    assert "needs OPENAI_API_KEY" in stream(client, attribute=AI.id, probe="np-3")[0][1]["message"]


def test_the_public_demo_refuses_without_a_pass(client, monkeypatch):
    monkeypatch.setenv(access.PUBLIC_ENV, "1")
    assert "public demo" in stream(client, attribute=AI.id, probe="np-3")[0][1]["message"]


def test_health_shows_the_budget(client, monkeypatch):
    monkeypatch.setenv(why.BUDGET_ENV, "0.5")
    assert client.get("/api/health").json()["why_budget_usd"] == 0.5


def test_a_model_that_cannot_search_is_refused(client, monkeypatch):
    monkeypatch.setattr(live, "preflight", lambda: live.Resolved("gpt-5-nano", None, "gpt-5-nano", "no tool"))
    assert "search the web" in stream(client, attribute=AI.id, probe="np-3")[0][1]["message"]
