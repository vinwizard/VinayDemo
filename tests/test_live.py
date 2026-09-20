"""Live adapter checks. No API key, no network: the transport is injected.

These prove the honesty rules hold before a real key is ever used — especially that an ungrounded
answer cannot reach a live score.
"""
import pytest

import drift
from agents import evaluation
from providers import fixture, live
from schemas import Probe
from scoring import eligible

PROBE = Probe(id="np-1", topic_id="perception", text="What is Notion, and who is it for?",
              kind="named", phase="baseline", purpose="perception")


def response(text="Notion is a notes app.", searched=True, citations=("https://example.com/a",)):
    message = {"type": "message", "content": [{
        "type": "output_text", "text": text,
        "annotations": [{"type": "url_citation", "url": u, "title": "t"} for u in citations]}]}
    out = [{"type": "web_search_call", "action": {"type": "search", "query": "notion"}}] if searched else []
    return {"output": out + [message]}


def provider(**kw):
    f = fixture.FixtureProvider("A")
    return live.LiveProvider(f.attributes(), f.named_probes(), model="test-model", **kw)


# --- the measured model must stay blind -------------------------------------
def test_measured_prompt_contains_only_the_question():
    msgs = live.measured_prompt(PROBE)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[1]["content"] == PROBE.text
    blob = " ".join(m["content"] for m in msgs).lower()
    for leak in ("ai-native", "workspace", "positioning", "attribute", "notion.com", "intended"):
        assert leak not in blob, f"measured prompt leaks {leak!r}"


def test_transport_receives_nothing_but_the_neutral_prompt():
    seen = {}

    def spy(messages, model, timeout):
        seen["messages"], seen["model"] = messages, model
        return response()

    provider(transport=spy).answer(PROBE)
    assert seen["messages"] == live.measured_prompt(PROBE)
    assert seen["model"] == "test-model"


# --- grounding is read, never assumed ---------------------------------------
def test_search_executed_true_only_when_web_search_call_present():
    a = provider(transport=lambda *_: response(searched=True)).answer(PROBE)
    assert a.search_executed is True and a.status == "ok"
    b = provider(transport=lambda *_: response(searched=False)).answer(PROBE)
    assert b.search_executed is False and b.status == "ok"


def test_ungrounded_live_answer_is_excluded_from_scores():
    """The whole point: an answer with no search behind it must not become a number."""
    a = provider(transport=lambda *_: response(searched=False)).answer(PROBE)
    ev = evaluation.evaluate(PROBE, a, fixture.bundled_profile("A"))
    assert not ev.valid
    ok, why = eligible(a, ev)
    assert not ok and "ungrounded" in why


def test_citations_are_not_treated_as_proof_of_search():
    """Citations can be emitted from memory; only web_search_call proves a search ran."""
    a = provider(transport=lambda *_: response(searched=False, citations=("https://notion.com/x",))).answer(PROBE)
    assert a.citations == ["https://notion.com/x"] and a.search_executed is False


# --- failures degrade honestly ----------------------------------------------
def test_timeout_becomes_a_failed_answer_not_a_zero():
    class Timeout(Exception):
        pass
    Timeout.__name__ = "APITimeoutError"

    def boom(*_):
        raise Timeout("took too long")

    a = provider(transport=boom).answer(PROBE)
    assert a.status == "timeout" and a.text == "" and "took too long" in a.error


def test_empty_response_is_an_error_not_an_absence():
    a = provider(transport=lambda *_: {"output": []}).answer(PROBE)
    assert a.status == "error" and a.error == "empty response"


def test_parse_handles_multiple_messages_and_dedupes_citations():
    r = {"output": [
        {"type": "web_search_call"},
        {"type": "message", "content": [{"type": "output_text", "text": "One.",
            "annotations": [{"type": "url_citation", "url": "https://a.example"}]}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Two.",
            "annotations": [{"type": "url_citation", "url": "https://a.example"},
                            {"type": "url_citation", "url": "https://b.example"}]}]}]}
    text, cites, searched = live.parse_response(r)
    assert text == "One.\nTwo." and cites == ["https://a.example", "https://b.example"] and searched


# --- provenance never pools --------------------------------------------------
def test_live_answers_are_marked_live_api():
    a = provider(transport=lambda *_: response()).answer(PROBE)
    assert a.provenance == "live_api" and a.provider == "openai" and a.collected_at


def test_live_plan_has_no_blind_probes_so_visibility_stays_null():
    p = provider(transport=lambda *_: response())
    topics, probes = p.plan(fixture.bundled_profile("A"))
    assert probes == [] and [t.kind for t in topics] == ["perception"]
    assert len(p.named_probes()) == 8


def test_adapter_is_disabled_without_a_key(monkeypatch):
    monkeypatch.delenv(live.KEY_ENV, raising=False)
    assert not live.available() and "Disabled" in live.status()


def test_live_run_is_not_labelled_synthetic():
    """Regression: measure_drift hardcoded 'synthetic', so a live run published a synthetic label."""
    import graph
    prov = provider(transport=lambda *_: response(text="Notion is a notes app."))
    run = graph.execute(graph.new_run(fixture.bundled_profile("A"), prov, mode="live_api"), prov)
    assert run.drift.provenance == "live_api"
    assert {a.provenance for a in run.answers} == {"live_api"}
    assert any("Collected" in l and "openai" in l for l in run.log)
    assert not any("from fixtures" in l for l in run.log)


def test_fixture_run_is_still_labelled_synthetic():
    import graph
    f = fixture.FixtureProvider("A")
    run = graph.execute(graph.new_run(fixture.bundled_profile("A"), f), f)
    assert run.drift.provenance == "synthetic"
    assert any("Replayed" in l and "fixtures" in l for l in run.log)


def test_mixed_provenance_named_answers_are_refused():
    import graph
    f = fixture.FixtureProvider("A")
    prov = provider(transport=lambda *_: response(text="Notion is a notes app."))
    run = graph.new_run(fixture.bundled_profile("A"), prov, mode="live_api")
    run.attributes = f.attributes()
    run.probes = f.named_probes()
    run.answers = [prov.answer(run.probes[0])] + [f.answer(p) for p in run.probes[1:]]
    with pytest.raises(graph.ValidationError, match="mix provenance"):
        graph.measure_drift({"run": run, "provider": prov, "rounds": 0})


def test_fixture_answers_never_claim_search_executed():
    """A synthetic answer must not be able to satisfy the live grounding check."""
    f = fixture.FixtureProvider("A")
    for pr in f.named_probes():
        assert f.answer(pr).search_executed is None
