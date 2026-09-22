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


# --- search is required of the model, not merely offered ---------------------
def test_the_request_forces_the_web_search_tool(monkeypatch):
    """An answer written from memory is excluded from live scores, so a call that did not search is
    money spent for nothing. tool_choice makes the tool the only way to answer."""
    import access
    sent = {}
    monkeypatch.setenv(access.KEY_ENV, "test-key")
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: sent.update(kw) or response())
    live.default_transport(live.measured_prompt(PROBE), "test-model", 30)
    assert sent["tools"] == [{"type": "web_search"}]
    assert sent["tool_choice"] == live.TOOL_CHOICE == "required"


def test_an_answer_that_still_did_not_search_is_asked_once_more():
    calls = []

    def flaky(messages, model, timeout):
        calls.append(1)
        return response(searched=len(calls) > 1, text=f"Answer {len(calls)}.")

    p = provider(transport=flaky)
    a = p.answer(PROBE)
    assert len(calls) == 2 and p.calls == 2
    assert a.search_executed is True and a.text == "Answer 2." and a.status == "ok"


def test_the_retry_is_tried_once_and_the_answer_is_then_ungrounded_as_before():
    calls = []

    def never(messages, model, timeout):
        calls.append(1)
        return response(searched=False)

    p = provider(transport=never)
    a = p.answer(PROBE)
    assert len(calls) == 2 and a.search_executed is False and a.status == "ok"


def test_a_retry_that_fails_keeps_the_ungrounded_answer_rather_than_losing_it():
    calls = []

    def once_then_boom(messages, model, timeout):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("connection reset")
        return response(searched=False, text="From memory.")

    a = provider(transport=once_then_boom).answer(PROBE)
    assert a.status == "ok" and a.text == "From memory." and a.search_executed is False


def test_a_grounded_answer_is_never_asked_twice():
    calls = []
    p = provider(transport=lambda *_: (calls.append(1), response())[1])
    p.answer(PROBE)
    assert len(calls) == 1


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
    assert a.status == "timeout" and a.text == "" and a.error == "APITimeoutError"


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


def test_every_search_the_model_ran_is_kept_in_order():
    r = response()
    r["output"][:0] = [{"type": "web_search_call", "action": {"type": "open_page", "url": "https://a.example"}},
                       {"type": "web_search_call", "action": {"type": "search", "query": "best wiki 2026",
                                                              "queries": ["best wiki 2026", "wiki pricing"]}},
                       {"type": "web_search_call"}]
    a = provider(transport=lambda *_: r).answer(PROBE)
    assert a.searches == ["best wiki 2026", "wiki pricing", "notion"]
    assert provider(transport=lambda *_: response(searched=False)).answer(PROBE).searches == []


# --- provenance never pools --------------------------------------------------
def test_live_answers_are_marked_live_api():
    a = provider(transport=lambda *_: response()).answer(PROBE)
    assert a.provenance == "live_api" and a.provider == "openai" and a.collected_at


def test_live_plan_includes_attribute_derived_blind_probes():
    """The placebo axis without a category: one buyer topic per intended attribute. The perception
    container is the graph's (plan_brand), made before any buyer question is planned."""
    p = provider(transport=lambda *_: response())
    profile = fixture.bundled_profile("A")
    topics, probes = p.plan(profile)
    assert "perception" not in [t.kind for t in topics]
    buyer = [t for t in topics if t.kind == "buyer"]
    assert len(buyer) == 4                      # four intended attributes
    assert all(pr.kind == "blind" for pr in probes)
    assert len(probes) == 12                    # three questions each: scoring needs n=3 per topic
    assert len(p.named_probes()) == 8


def test_placebo_questions_never_name_the_brand():
    from agents import ana
    p = provider(transport=lambda *_: response())
    profile = fixture.bundled_profile("A")
    _, probes = p.plan(profile)
    for pr in probes:
        assert not ana.brand_leaks(pr.text, profile), f"{pr.id} leaks: {pr.text}"


def test_aspiration_alone_is_not_strong_product_fit():
    """.claude/skills/product-workflow: a claim their own copy does not state cannot count as strong fit."""
    p = provider(transport=lambda *_: response())
    topics, _ = p.plan(fixture.bundled_profile("A"))
    fits = {t.id: t.fit for t in topics if t.kind == "buyer"}
    assert fits["pos-enterprise"] == "partial"   # Notion barely states enterprise readiness
    assert fits["pos-replaces_stack"] == "strong"


def test_brand_leaking_buyer_question_is_rejected_not_rewritten():
    from agents import ana
    from schemas import Attribute
    profile = fixture.bundled_profile("A")
    bad = [Attribute(id="x", label="X", intended_weight=1.0,
                     buyer_questions=["Is Notion the best wiki?"])]
    with pytest.raises(ValueError, match="leak the brand"):
        ana.blind_probes_from_attributes(bad, profile)


def test_a_saved_vendor_addressed_question_is_named_in_the_run_log_not_fatal():
    """A company saved before the vendor guard still runs, without that question, and says so."""
    import graph
    prov = provider(transport=lambda *_: response(text="Notion is a notes app."))
    a = prov._attributes[0]
    a.buyer_questions = ["How does your platform help teams share docs?", *a.buyer_questions[1:]]
    run = graph.execute(graph.new_run(fixture.bundled_profile("A"), prov, mode="live_api"), prov)
    assert run.status == "complete"
    assert not any(p.text.startswith("How does your platform") for p in run.probes)
    assert any("1 buyer question(s) dropped" in l and f"{a.id}-1 (your platform)" in l
               for l in run.log)


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


# --- preflight: an unusable model must fail once, with a usable message ------
class StatusError(Exception):
    """Shaped like openai.APIStatusError: the body is the message, status and code are attributes."""
    def __init__(self, status_code, body, code=None):
        super().__init__(body)
        self.status_code, self.code = status_code, code


KEY_FRAGMENT = "sk-proj-****abcd"
# OpenAI's real 401 body for a bad key: its type is invalid_request_error and it quotes the key.
BAD_KEY = StatusError(401, "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
                      f"{KEY_FRAGMENT}.', 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}}}",
                      code="invalid_api_key")
REGION = StatusError(403, "Error code: 403 - {'error': {'code': 'unsupported_country_region_territory', "
                     "'message': 'Country, region, or territory not supported', "
                     "'type': 'request_forbidden'}}", code="unsupported_country_region_territory")


def raising(exc):
    def boom(*_):
        raise exc
    return boom


def test_preflight_rejects_a_model_that_cannot_take_the_tool():
    """Regression: gpt-4o-mini-search-preview 400s on the Responses API, producing 20 identical
    errors and an unreadable report. Preflight turns that into one clear message."""
    exc = StatusError(400, "Error code: 400 - {'error': {'message': \"The requested model "
                      "'gpt-4o-mini-search-preview' is not supported with the Responses API.\"}}")
    with pytest.raises(live.ModelUnsupported, match="does not accept the Responses API"):
        live.preflight("gpt-4o-mini-search-preview", transport=raising(exc))


def test_preflight_bad_key_is_a_credential_error_not_an_unsupported_model():
    with pytest.raises(live.PreflightFailed) as info:
        live.preflight("gpt-4o-mini", transport=raising(BAD_KEY))
    assert type(info.value) is live.CredentialRejected
    assert "refused your API key" in str(info.value)
    assert "does not accept" not in str(info.value) and live.MODEL_ENV not in str(info.value)


def test_preflight_invalid_api_key_code_alone_is_a_credential_error():
    with pytest.raises(live.CredentialRejected):
        live.preflight("gpt-4o-mini", transport=raising(StatusError(None, "bad", code="invalid_api_key")))


def test_preflight_region_block_is_not_an_unsupported_model():
    with pytest.raises(live.PreflightFailed) as info:
        live.preflight("gpt-4o-mini", transport=raising(REGION))
    assert type(info.value) is live.AccessDenied
    assert "region" in str(info.value) and "does not accept" not in str(info.value)


@pytest.mark.parametrize("exc", [BAD_KEY, REGION])
def test_no_payload_carries_the_provider_body_or_a_key_fragment(exc):
    with pytest.raises(live.PreflightFailed) as info:
        live.preflight("gpt-4o-mini", transport=raising(exc))
    a = provider(transport=raising(exc)).answer(PROBE)
    for text in (str(info.value), a.error, a.model_dump_json()):
        assert KEY_FRAGMENT not in text and "abcd" not in text and "Error code" not in text


def test_preflight_passes_a_working_model():
    assert live.preflight("gpt-4o-mini", transport=lambda *_: response()) is None


def test_preflight_reraises_unrelated_failures():
    def boom(*_):
        raise RuntimeError("Connection reset by peer")
    with pytest.raises(RuntimeError, match="Connection reset"):
        live.preflight("gpt-4o-mini", transport=boom)
