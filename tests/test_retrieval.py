"""Simulate the retrieval, then test the fix: passages, similarity with deterministic fake vectors,
the win-back rewrite spliced into its page, metering of the embeddings call, and the re-ask. No page
is fetched and no model is called."""
import json

import pytest
from fastapi.testclient import TestClient

import access
import api.main as main
import embeddings
import graph
import reports
import retrieval
from providers import fixture, live
from schemas import WinBackAction

VOCAB = ["track", "task", "project", "meeting", "note", "wiki", "doc", "transcrib", "offline"]


def by_words(texts):
    """A vector per text: how often each VOCAB stem appears, so similarity follows shared topic."""
    return [[t.lower().count(w) + 0.01 for w in VOCAB] for t in texts]


def replay(scenario="A"):
    prov = fixture.FixtureProvider(scenario)
    return graph.execute(graph.new_run(prov.profile, prov), prov)


PAGES = {
    "https://example.com/demo-source-claim-2": ["All in one", "Write docs and wikis. " * 30],
    "https://example.com/demo-source-claim-1": ["Notion AI drafts a doc for you. " * 5],
    "https://example.com/demo-source-5": ["Track every project task on a board. " * 12],
    "https://example.com/demo-source-11": ["Transcribe each meeting without a bot and get meeting notes. " * 8],
}


def read(url):
    if url.endswith("demo-source-9"):
        raise retrieval.Skipped("its robots.txt does not allow it")
    if url not in PAGES:
        raise retrieval.Skipped("it could not be read (TimeoutError)")
    return PAGES[url]


def test_blocks_become_80_to_150_word_passages_on_block_boundaries():
    heading, para = "Pricing", " ".join(["word"] * 90)
    out = retrieval.split([heading, para, para, "Short tail."])
    assert out[0].startswith("Pricing word")                     # a heading joins the text after it
    assert all(80 <= len(p.split()) <= 150 for p in out)
    long = ". ".join(" ".join(["w"] * 20) for _ in range(20)) + "."   # 400 words, one block
    assert all(len(p.split()) <= 150 for p in retrieval.split([long]))
    assert all(len(p.split()) <= 150 for p in retrieval.split([" ".join(["w"] * 400)]))  # no sentences


def test_simulation_compares_your_best_passage_with_the_cited_one_and_re_scores_the_fix():
    run = replay()
    sim = retrieval.simulate(run, embed=by_words, read=read)
    rows = {r.probe_id: r for r in sim.rows}
    pt1 = rows["pt-1"]
    assert pt1.rival.url == "https://example.com/demo-source-5"   # a page AI cited for this question
    assert "claim" in pt1.yours.url and pt1.rival.score > pt1.yours.score   # one of your pages
    assert pt1.fix_attribute_id == "replaces_stack"               # the win-back fix that targets pt-1
    assert pt1.fixed.text == next(a.rewrite for a in run.win_back if a.attribute_id == "replaces_stack")
    assert pt1.fixed.score > pt1.yours.score                      # the rewrite talks about tasks
    assert rows["kb-1"].fixed is None                             # no fix targets it
    assert pt1.queries == 3 and pt1.rival.query in ["What are good project tracking tools for small teams?",
                                                    "project tracking tools for small teams",
                                                    "best project management software 2026"]
    assert rows["mtg-1"].rival is None                            # its only cited page was not read
    assert "demo-source-9 was not read: its robots.txt does not allow it." in " ".join(sim.skipped)
    # a page of yours that could not be read again falls back to the text saved at onboarding
    assert any("claim-3 could not be read again" in s for s in sim.skipped)
    assert sim.provenance == "live_api" and sim.model == embeddings.MODEL


def test_a_rewrite_replaces_its_copy_inside_the_passage_that_holds_it():
    run = replay()
    run.win_back = [WinBackAction(attribute_id="replaces_stack", label="x", zone="lost_claim",
                                  page_url="https://example.com/demo-source-claim-2",
                                  current_copy="All in one", rewrite="Tasks and projects live beside docs.",
                                  question_ids=["pt-1"], provenance="synthetic")]
    fixed = {r.probe_id: r for r in retrieval.simulate(run, embed=by_words, read=read).rows}["pt-1"].fixed
    assert fixed.text.startswith("Tasks and projects live beside docs. Write docs and wikis.")
    assert "All in one" not in fixed.text


def test_replay_carries_the_authored_sample_and_moves_no_score():
    for scenario, score in (("A", 21.4), ("B", 27.9)):
        run = replay(scenario)
        assert run.retrieval.provenance == "synthetic" and run.retrieval.model is None
        assert run.drift.alignment == score
        ids = {p.id for p in run.probes}
        fixes = {a.attribute_id: a for a in run.win_back}
        for r in run.retrieval.rows:
            assert r.probe_id in ids and r.yours and r.rival
            if r.fixed:
                assert r.fixed.text == fixes[r.fix_attribute_id].rewrite
                assert r.probe_id in fixes[r.fix_attribute_id].question_ids
        assert "authored, not computed" in " ".join(run.log)


def test_a_test_transport_never_runs_the_simulation():
    assert live.LiveProvider([object()], [], transport=lambda *a: None).retrieval is None


def test_embeddings_are_cached_by_text_and_charged_to_the_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DATA", tmp_path)            # the access database
    access.create_pass("t", 5)
    pid = access.all_passes()[0]["id"]
    calls = []
    monkeypatch.setattr(access, "_embed", lambda timeout, **kw: calls.append(kw["input"]) or {
        "data": [{"embedding": [1.0, 0.0]} for _ in kw["input"]],
        "usage": {"prompt_tokens": 1_000_000, "total_tokens": 1_000_000}})
    with access.spending(pid):
        assert embeddings.embed(["a", "b", "a"]) == [[1.0, 0.0]] * 3
        embeddings.embed(["b", "a"])                            # all cached: no second call
    assert calls == [["a", "b"]]
    assert access.get_pass(pid)["spent_usd"] == pytest.approx(0.02)   # $0.02 per 1M input tokens
    assert embeddings.cosine([1, 0], [0, 1]) == 0 and embeddings.cosine([2, 0], [1, 0]) == pytest.approx(1)


def test_embeddings_on_the_public_demo_need_a_pass(monkeypatch):
    monkeypatch.setenv(access.PUBLIC_ENV, "1")
    with pytest.raises(access.Refused):
        embeddings.embed(["never sent"])


# --- asking again with the rewritten passage as a source ------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(reports, "DATA", tmp_path)
    monkeypatch.setattr(reports, "RUNS", runs)
    monkeypatch.setattr(main, "RUNS", runs)
    monkeypatch.setenv(live.KEY_ENV, "sk-fake-never-sent")
    monkeypatch.delenv(access.PUBLIC_ENV, raising=False)
    run = replay()
    run.mode = "live_api"
    run.id = "ae5c000001"
    reports.save_run(run)
    return TestClient(main.app, raise_server_exceptions=False), run


def test_asking_again_supplies_both_passages_and_reads_whether_you_are_named(api, monkeypatch):
    c, run = api
    sent = []
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: sent.append(kw) or {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Try Notion for this."}]}]})
    r = c.post(f"/api/runs/{run.id}/reask", json={"probe_id": "pt-1"})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["retrieval"]["rows"] if x["probe_id"] == "pt-1")
    assert row["reask"]["named"] is True
    (kw,) = sent
    assert "tools" not in kw                                      # no web search: the sources are given
    user = kw["input"][1]["content"]
    assert user.index(row["rival"]["text"]) < user.index(row["fixed"]["text"])   # cited page first
    saved = json.loads((reports.RUNS / f"{run.id}.json").read_text())
    assert next(x for x in saved["retrieval"]["rows"] if x["probe_id"] == "pt-1")["reask"]["named"]
    assert c.post(f"/api/runs/{run.id}/reask", json={"probe_id": "kb-1"}).status_code == 404  # no fix


def test_asking_again_keeps_weights_saved_while_the_model_answered(api, monkeypatch):
    c, run = api
    claim = run.attributes[0].id

    def rescore_meanwhile(timeout, **kw):
        c.post(f"/api/runs/{run.id}/rescore", json={"weights": {claim: 0.5}})
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Try Notion."}]}]}

    monkeypatch.setattr(access, "_create", rescore_meanwhile)
    assert c.post(f"/api/runs/{run.id}/reask", json={"probe_id": "pt-1"}).status_code == 200
    saved = reports.load_run(run.id)
    assert next(a for a in saved.attributes if a.id == claim).intended_weight == 0.5
    assert next(x for x in saved.retrieval.rows if x.probe_id == "pt-1").reask.named


def test_asking_again_is_refused_without_a_pass_and_on_a_replay(api, monkeypatch):
    c, run = api
    monkeypatch.setattr(access, "_create", lambda *a, **k: pytest.fail("no model call expected"))
    sample = replay()
    reports.save_run(sample)
    assert c.post(f"/api/runs/{sample.id}/reask", json={"probe_id": "pt-1"}).status_code == 400
    monkeypatch.setenv(access.PUBLIC_ENV, "1")
    monkeypatch.setenv(access.SECRET_ENV, "s")
    r = c.post(f"/api/runs/{run.id}/reask", json={"probe_id": "pt-1"})
    assert r.status_code == 403 and "public demo" in r.json()["detail"]
