"""Buyer visibility you can trust: the core category is always asked about, the buyer budget goes on
distinct questions with a sample re-asked for the wobble, and a control question decides whether a 0
means anything.

No key, no network: transports and the evaluator are injected.
"""
import json
from collections import Counter

import pytest
from fastapi import HTTPException

import access
import api.main as main
import graph
import reports
from agents import ana, onboarding_model
from providers import fixture, live
from schemas import Company, QueryEvaluation, Answer
from scoring import MIN_CONTROL_VENDORS, low_confidence, visibility_by_question, visibility_over_tries

F = fixture.FixtureProvider("A")
CATEGORY = "connected workspace software"
CAT_QS = [f"Which workspace tool suits a team of {n}?" for n in (5, 10, 20, 50, 100, 200)]


def with_category(questions=CAT_QS, category=CATEGORY):
    return F.profile.model_copy(update=dict(core_category=category, category_questions=list(questions)))


# ---------------------------------------------------------------- 1. the core category is always asked
def test_without_a_category_or_a_placed_front_buyer_topics_follow_the_claims_as_before():
    old = ana.blind_probes_from_attributes(F.attributes(), F.profile)
    assert all(t.id.startswith("pos-") for t in old[0]) and len(old[0]) == 4  # the claims with questions
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=F.profile, model="m")
    topics, blind = prov.plan(F.profile)
    assert not [p for p in blind if p.phase == "control"] and "control" not in {t.kind for t in topics}


def test_a_category_question_naming_the_brand_is_skipped_not_asked():
    topics, probes, skipped, _ = ana.blind_probes_for_fronts(
        with_category(["Is Notion the best workspace?", *CAT_QS[:3]]), None, [])
    assert skipped[0].startswith("cat-1 (Notion") and not any("Notion" in p.text for p in probes)


def test_the_control_question_is_never_also_a_scored_question():
    control = ana.control_probe(with_category())
    _, probes, _, _ = ana.blind_probes_for_fronts(with_category([control.text, *CAT_QS[:5]]), None, [])
    assert [p.text for p in probes if p.phase == "baseline"] == CAT_QS[:5]
    assert control.phase == "control" and not ana.brand_leaks(control.text, F.profile)


# ---------------------------------------------------------------- 3 & 4. repeats, range, control
def test_visibility_weighs_every_question_once_however_often_it_was_asked():
    """A question re-asked three times must not get three votes, or the repeat sample would drag
    the whole number towards whatever those two questions happen to say."""
    assert visibility_by_question([[2, 2, 2], [0], [0], [0]]) == 25.0
    assert visibility_by_question([[2, 0, 1], [2]]) == 75.0   # (1 + 2) / 2 of a possible 2
    assert visibility_by_question([[1], []]) == 50.0          # a question with no answer is not a zero
    assert visibility_by_question([]) is None


def test_the_range_beside_the_number_is_the_per_try_wobble():
    assert visibility_over_tries([[2, 0, 0], [0, 0, 0], [1, 1, 0]]) == (22.2, [0.0, 33.3])
    assert visibility_over_tries([[2, 1, 0]]) == (50.0, [50.0, 50.0])   # one try is its own range
    assert visibility_over_tries([[1], []]) == (50.0, [50.0, 50.0])       # an empty try is not a zero
    assert visibility_over_tries([]) == (None, None)


class Judge:
    """Labels what the answer actually says, so the validators accept it."""
    model = "test-judge"

    def label(self, probe, answer, attributes, profile):
        named = profile.name in answer.text
        return dict(mentioned=named, recommended=False, negative_mention=False,
                    competitor_recommendations=[c for c in ("Linear", "Asana", "Coda") if c in answer.text],
                    evidence_quotes=[answer.text] if named else [], on_topic=True, attributes=[])

    def discover(self, profile, attributes, answers):
        return []


def live_run(buyer_text, control_text, tries=3, sample=2, questions=6, monkeypatch=None):
    """buyer_text(ask number of that question) -> answer text. Named questions get a plain answer."""
    asked = Counter()
    profile = with_category()
    buyer = {q for q in CAT_QS} | {q for a in F.attributes() for q in a.buyer_questions}

    def transport(messages, model, timeout):
        q = messages[-1]["content"]
        asked[q] += 1
        text = (control_text if q.startswith("What are the leading tools") else
                buyer_text(asked[q]) if q in buyer else "A workspace tool.")
        return {"output": [{"type": "web_search_call"},
                           {"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    monkeypatch.setenv(live.TRIES_ENV, str(tries))
    monkeypatch.setenv(live.SAMPLE_ENV, str(sample))
    monkeypatch.setenv(ana.QUESTIONS_ENV, str(questions))
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="test-model",
                             transport=transport, evaluator=Judge())
    prov.concurrency = 1
    return graph.execute(graph.new_run(profile, prov, mode="live_api"), prov), asked


def test_the_budget_buys_questions_once_each_with_a_small_repeat_sample(monkeypatch):
    """The captain's change: one try on many questions, three tries on a couple, so the same money
    narrows the confidence interval instead of re-asking what barely moves."""
    run, asked = live_run(lambda n: "Notion fits." if n == 2 else "Coda fits.", "Linear, Asana and Coda.",
                          monkeypatch=monkeypatch)
    buyer = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    sampled = graph.repeat_sampled(buyer, 2)
    assert len(sampled) == 2 and all(asked[p.text] == 3 for p in sampled)
    assert all(asked[p.text] == 1 for p in buyer if p not in sampled)
    assert all(asked[p.text] == 1 for p in run.probes if p.kind == "named" or p.phase == "control")
    assert len(run.answers) == len(run.probes) and len(run.repeat_answers) == 2 * len(sampled)
    assert Counter(a.try_no for a in run.repeat_evaluations) == {2: 2, 3: 2}
    d = run.drift
    # every question is named on its second ask only: the once-asked ones score 0, the sampled two
    # score 1 of 3 tries each, and the wobble is read off those two alone
    assert (d.tries, d.repeat_sample, d.visibility_range) == (3, 2, [0.0, 50.0])
    assert d.visibility == 2.8 and d.n_blind == len(buyer) + 2 * len(sampled)
    named = Counter(e.probe_id for e in run.evaluations + run.repeat_evaluations if e.mentioned)
    assert set(named.values()) == {1}   # "named in 1 of 3 tries" on the sampled ones


def test_repeat_asks_are_spread_across_the_fronts_not_taken_off_the_front_of_the_list():
    """The fronts are contiguous in plan order, so the first two questions are the same category."""
    buyer = [f"q{i}" for i in range(12)]
    assert graph.repeat_sampled(buyer, 2) == ["q0", "q6"]
    assert graph.repeat_sampled(buyer, 3) == ["q0", "q4", "q8"]
    assert graph.repeat_sampled(buyer, 0) == [] and graph.repeat_sampled([], 2) == []
    assert graph.repeat_sampled(["q0"], 5) == ["q0"]      # never more questions than there are


def test_the_control_question_never_moves_visibility(monkeypatch):
    run, _ = live_run(lambda n: "Coda fits.", "Notion, Linear and Asana lead.", monkeypatch=monkeypatch)
    control = next(p for p in run.probes if p.phase == "control")
    assert next(e for e in run.evaluations if e.probe_id == control.id).mentioned
    aiming = run.drift.sets[0]
    assert (aiming.front, aiming.visibility, aiming.n_blind) == ("aiming", 0.0, 6 + 2)
    assert run.drift.visibility == 0.0 and run.drift.n_blind == 12 + 4   # the claims fill the other half
    # the model knows the brand as a category leader and still never offers it to buyers: a real 0
    assert run.drift.low_confidence is None
    assert control.id not in {e.probe_id for e in run.repeat_evaluations}
    assert all(t.topic_id != "control" for t in run.topic_evaluations)
    assert main.run_payload(run)["insights"]["voice"]["questions"] == 12   # buyer questions, first try


def test_a_zero_is_low_confidence_when_the_control_names_too_few_tools(monkeypatch):
    run, _ = live_run(lambda n: "Coda fits.", "Hard to say; Coda maybe.", monkeypatch=monkeypatch)
    assert run.drift.visibility == 0.0
    assert "does not seem to know this category" in run.drift.low_confidence


def test_a_zero_is_low_confidence_when_even_the_control_leaves_the_brand_out(monkeypatch):
    run, _ = live_run(lambda n: "Coda fits.", "Linear, Asana and Coda lead.", monkeypatch=monkeypatch)
    assert "named Linear, Asana, Coda but not Notion" in run.drift.low_confidence


def test_a_brand_named_in_some_buyer_answers_is_still_flagged_when_the_control_leaves_it_out(monkeypatch):
    # the live Profound run: named once by chance, absent from 38 category leaders, and never flagged
    run, _ = live_run(lambda n: "Notion fits." if n == 3 else "Coda fits.", "Linear, Asana and Coda.",
                      monkeypatch=monkeypatch)
    assert run.drift.visibility > 0 and "but not Notion" in run.drift.low_confidence
    run, _ = live_run(lambda n: "Notion fits." if n == 3 else "Coda fits.", "Coda.", monkeypatch=monkeypatch)
    assert "does not seem to know this category" in run.drift.low_confidence


def test_the_flag_rule():
    ok = Answer(probe_id="ctl-1", text="x", provenance="live_api", provider="openai", model="m",
                collected_at="t", search_executed=True)
    ev = lambda names, mentioned=False: QueryEvaluation(
        probe_id="ctl-1", valid=True, mentioned=mentioned, competitor_recommendations=names, strength=0,
        explanation="")
    assert MIN_CONTROL_VENDORS == 2
    assert "only Coda" in low_confidence("Notion", CATEGORY, ev(["Coda"]), ok)
    assert "but not Notion" in low_confidence("Notion", CATEGORY, ev(["Coda", "Linear"]), ok)
    assert low_confidence("Notion", CATEGORY, ev(["Coda", "Linear"], mentioned=True), ok) is None
    failed = QueryEvaluation(probe_id="ctl-1", valid=False, explanation="Collection failed")
    assert "could not be scored" in low_confidence("Notion", CATEGORY, failed, ok)


# ---------------------------------------------------------------- offline replay is one try, unchanged
@pytest.mark.parametrize("scenario,alignment", [("A", 21.4), ("B", 27.9)])
def test_offline_replay_is_one_try_and_its_numbers_do_not_move(scenario, alignment):
    p = fixture.FixtureProvider(scenario)
    run = graph.execute(graph.new_run(p.profile, p), p)
    d = run.drift
    assert (d.alignment, d.visibility, d.n_blind) == (alignment, 54.2, 12)
    # one authored answer per question: nothing was re-asked, so there is no wobble to show
    assert (d.tries, d.repeat_sample, d.visibility_range, d.low_confidence) == (1, 0, None, None)
    assert run.repeat_answers == [] and not [x for x in run.probes if x.phase == "control"]


# ---------------------------------------------------------------- 2. the answering model is a setting
def test_the_answering_model_defaults_to_a_recent_searching_model_and_is_priced_exactly(monkeypatch):
    """gpt-4.1's training stopped in 2024, so it answered about brands it had never heard of. The
    default is a 2026 model that takes web_search and costs a fraction of it."""
    monkeypatch.delenv(live.MODEL_ENV, raising=False)
    assert live.model_name() == "gpt-6-luna" and live.MODEL_ENV == "MEASURED_MODEL"
    assert access.PRICES["gpt-6-luna"] < access.PRICES["gpt-4.1"]
    assert all(access.UNKNOWN_PRICE[i] > max(p[i] for p in access.PRICES.values()) for i in (0, 1))
    monkeypatch.setenv(live.MODEL_ENV, "gpt-4o")
    assert live.model_name() == "gpt-4o"


def test_every_model_the_app_can_be_pointed_at_is_priced(monkeypatch):
    """A model missing from the table is metered at UNKNOWN_PRICE, which would bill a pass for far
    more than it spent; the defaults and the models the error message offers must all be listed."""
    from agents import evaluator_model, onboarding_model
    offered = {live.DEFAULT_MODEL, live.FALLBACK_MODEL, evaluator_model.DEFAULT_MODEL,
               onboarding_model.DEFAULT_MODEL,
               "gpt-6-luna", "gpt-5-nano", "gpt-5.6-luna", "gpt-5.4-mini", "gpt-5.5",
               "gpt-4.1-mini", "gpt-4.1"}
    assert offered <= set(access.PRICES)


@pytest.mark.parametrize("raw,tries", [(None, 3), ("5", 5), ("0", 1), ("lots", 3)])
def test_buyer_tries_setting(monkeypatch, raw, tries):
    monkeypatch.delenv(live.TRIES_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(live.TRIES_ENV, raw)
    assert live.buyer_tries() == tries


@pytest.mark.parametrize("raw,sample", [(None, 2), ("4", 4), ("0", 0), ("some", 2)])
def test_repeat_sample_setting(monkeypatch, raw, sample):
    monkeypatch.delenv(live.SAMPLE_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(live.SAMPLE_ENV, raw)
    assert live.repeat_sample() == sample and live.SAMPLE_ENV == "REPEAT_SAMPLE"


@pytest.mark.parametrize("raw,per_front", [(None, 12), ("20", 20), ("1", 3), ("many", 12)])
def test_buyer_questions_setting(monkeypatch, raw, per_front):
    monkeypatch.delenv(ana.QUESTIONS_ENV, raising=False)
    if raw is not None:
        monkeypatch.setenv(ana.QUESTIONS_ENV, raw)
    assert ana.set_questions() == per_front and ana.QUESTIONS_ENV == "BUYER_QUESTIONS"
    assert graph.max_baseline() == 2 * ana.PER_TOPIC * -(-per_front // ana.PER_TOPIC)


def test_health_names_both_models_the_budget_and_that_search_is_forced(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for env in (live.MODEL_ENV, live.TRIES_ENV, live.SAMPLE_ENV, ana.QUESTIONS_ENV):
        monkeypatch.delenv(env, raising=False)
    h = main.health()
    assert (h["measured_model"], h["buyer_tries"]) == ("gpt-6-luna", 3)
    assert (h["buyer_questions"], h["repeat_sample"], h["forced_search"]) == (12, 2, True)
    assert h["search_mode"] == "web_search with external_web_access" and h["model_fallback"] is None
    assert h["configured_measured_model"] == h["measured_model"] == h["evaluator_model"]
    # the captain's default points both halves at one cheap model; the bias is surfaced, not hidden
    assert h["same_model_warning"] is True


def test_progress_counts_every_ask(monkeypatch):
    monkeypatch.setenv(ana.QUESTIONS_ENV, "6")
    run = graph.new_run(with_category(), F)
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=with_category(), model="m")
    run.topics, blind = prov.plan(run.profile)
    run.probes = blind + F.named_probes()
    planned = main.progress(run, 3, 2)["planned"]
    # no brand answer yet: the category's own front and the claims, 12 questions once each, two of
    # them twice more, plus one control
    assert planned["buyer"] == 12 + 2 * 2 + 1 and planned["brand"] == len(F.named_probes())


# ---------------------------------------------------------------- onboarding and the claims screen
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "COMPANIES", tmp_path)
    return tmp_path


def company():
    return Company(id="abc123", profile=F.profile, attributes=F.attributes(), pages=["https://notion.com/"])


def test_the_category_is_corrected_on_the_claims_screen_and_gets_new_questions(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(onboarding_model, "default_transport",
                        lambda *_: json.dumps({"buyer_questions": CAT_QS + ["Can your platform sync?"]}))
    reports.save_company(company())
    out = main.patch_company("abc123", main.CompanyPatch(core_category="  AI  search visibility tracking "))
    assert out["profile"]["core_category"] == "AI search visibility tracking"
    assert out["profile"]["category_questions"] == CAT_QS          # the vendor-addressed one is dropped
    assert reports.load_company("abc123").profile.category_questions == CAT_QS


def test_a_category_naming_the_brand_is_refused(store):
    reports.save_company(company())
    with pytest.raises(HTTPException) as e:
        main.patch_company("abc123", main.CompanyPatch(core_category="Notion alternatives"))
    assert e.value.status_code == 400


def test_without_a_key_the_category_is_kept_and_the_missing_questions_are_stated(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reports.save_company(company())
    out = main.patch_company("abc123", main.CompanyPatch(core_category=CATEGORY))
    assert out["profile"]["core_category"] == CATEGORY and out["profile"]["category_questions"] == []
    assert any("where you aim to be is not measured" in w for w in out["warnings"])


def test_onboarding_names_the_core_category(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    page = "Acme runs payroll for startups in minutes, with taxes filed for you."
    monkeypatch.setattr(main.fetching, "fetch_site", lambda url, max_pages: ([("https://acme.example/", page)], None))

    def transport(prompt, model, timeout):
        if "buyer is shopping" in prompt:
            return json.dumps({"buyer_questions": ["Which payroll software suits a small startup?"]})
        return json.dumps({"name": "Acme", "one_liner": "Payroll for startups.",
                           "core_category": "payroll software for startups", "attributes": []})
    monkeypatch.setattr(onboarding_model, "default_transport", transport)
    out = main.onboard(url="https://acme.example/", name="Acme")
    assert out["profile"]["core_category"] == "payroll software for startups"
    assert out["profile"]["category_questions"] == ["Which payroll software suits a small startup?"]


def test_an_old_run_without_the_new_fields_still_reads():
    p = fixture.FixtureProvider("A")
    run = graph.execute(graph.new_run(p.profile, p), p)
    raw = json.loads(run.model_dump_json())
    for k in ("tries", "visibility_range", "low_confidence"):
        raw["drift"].pop(k)
    raw.pop("repeat_answers"), raw.pop("repeat_evaluations")
    old = type(run).model_validate(raw)
    assert old.drift.tries == 1 and old.drift.visibility_range is None
