"""Onboarding a company that is not a bundled fixture: persistence, intent, discovered competitors.

A company used to BE a fixture filename. These checks pin the properties that let an arbitrary
company be measured without letting it quietly inherit the demo's data or the demo's numbers.
"""
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import api.main as main
import drift
import fetching
import graph
import reports
from agents import ana, onboarding, onboarding_model
from providers import fixture
from providers.company import CompanyProvider
from schemas import Attribute, Company, CompanyProfile, TopicEvaluation

PROFILE = CompanyProfile(name="Acme", domain="acme.example", aliases=["Acme"])


def mk_company(cid="abc123", attrs=None, pages=("https://acme.example/",)):
    return Company(id=cid, profile=PROFILE, pages=list(pages),
                   attributes=attrs if attrs is not None else
                   [Attribute(id="fast", label="Fast to set up", claim_evidence_ids=["pg1"],
                              claim_quotes=["set up in minutes"], claim_pages=1,
                              claim_pages_total=len(pages))])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "COMPANIES", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- persistence
def test_company_roundtrip(store):
    c = mk_company()
    reports.save_company(c)
    assert [p.stem for p in reports.list_companies()] == ["abc123"]
    assert reports.load_company("abc123").profile.name == "Acme"


def test_a_company_id_cannot_walk_out_of_the_directory(store):
    with pytest.raises(ValueError):
        reports.load_company("../../etc/passwd")


# ---------------------------------------------------------------- named probes
def test_named_probes_are_templated_on_the_brand_name_alone():
    probes = onboarding.named_probes_for(PROFILE)
    assert len(probes) == 7
    assert all(p.kind == "named" and p.phase == "baseline" and "Acme" in p.text for p in probes)
    # the competitor comparison is discovered later, never asked up front
    assert not any("compare" in p.text.lower() for p in probes)


def test_named_probes_never_name_the_attribute_being_measured():
    attrs = [Attribute(id="fast", label="Fast to set up"), Attribute(id="ent", label="Enterprise ready")]
    assert not ana.validate_named_probes(onboarding.named_probes_for(PROFILE), attrs)


def test_company_provider_supplies_attributes_and_probes_but_cannot_answer(store):
    p = CompanyProvider(mk_company())
    assert [a.id for a in p.attributes()] == ["fast"]
    assert len(p.named_probes()) == 7
    assert not hasattr(p, "answer")   # LiveProvider measures; there is no fixture to fall back to


# ---------------------------------------------------------------- build_provider
def test_demo_mode_refuses_an_onboarded_company_instead_of_replaying_someone_elses_answers(store):
    reports.save_company(mk_company())
    with pytest.raises(HTTPException) as e:
        main.build_provider("demo", company_id="abc123")
    assert e.value.status_code == 400
    assert "OPENAI_API_KEY" in e.value.detail and "Acme" in e.value.detail


def test_unknown_company_is_a_404_not_a_fixture(store):
    with pytest.raises(HTTPException) as e:
        main.build_provider("live", company_id="deadbeef")
    assert e.value.status_code == 404


def test_live_mode_for_a_company_still_needs_a_key(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reports.save_company(mk_company())
    with pytest.raises(HTTPException) as e:
        main.build_provider("live", company_id="abc123")
    assert e.value.status_code == 400 and "OPENAI_API_KEY" in e.value.detail


# ---------------------------------------------------------------- customer intent
def test_a_slider_left_at_zero_does_not_create_an_intent(store):
    reports.save_company(mk_company())
    out = main.patch_company("abc123", main.CompanyPatch(weights={"fast": 0.0}))
    assert out["attributes"][0]["intended_weight"] is None


def test_patch_sets_weights_and_adds_an_unstated_claim(store):
    reports.save_company(mk_company(pages=["p1", "p2"]))
    out = main.patch_company("abc123", main.CompanyPatch(
        weights={"fast": 0.8},
        added=[main.AddedAttribute(label="Secure by default", intended_weight=1.0)]))
    by_label = {a["label"]: a for a in out["attributes"]}
    assert by_label["Fast to set up"]["intended_weight"] == 0.8
    added = by_label["Secure by default"]
    # their own copy never states it: zero of the known pages, which is the finding itself
    assert added["intended_weight"] == 1.0
    assert (added["claim_pages"], added["claim_pages_total"]) == (0, 2)
    assert added["claim_quotes"] == []


def test_patch_rejects_an_unknown_attribute(store):
    reports.save_company(mk_company())
    with pytest.raises(HTTPException) as e:
        main.patch_company("abc123", main.CompanyPatch(weights={"nope": 0.5}))
    assert e.value.status_code == 400


# ---------------------------------------------------------------- discovered competitors
def te(topic_id, competitors, phase="baseline"):
    return TopicEvaluation(topic_id=topic_id, phase=phase, provenance="live_api", n=3, excluded=0,
                           status="candidate gap", top_competitors=competitors)


def test_competitors_come_from_the_answers_and_the_comparison_names_them():
    names = ana.discovered_competitors([te("t1", ["Linear", "Asana"]), te("t2", ["Linear"])])
    assert names == ["Linear", "Asana"]
    p = ana.comparison_probe(PROFILE, names, ["t1-b1"])
    assert p.text == "How does Acme compare to Linear and Asana?"
    assert p.kind == "named" and p.phase == "followup" and p.parent_probe_ids == ["t1-b1"]


def test_a_followup_round_finding_nobody_is_asked_nothing():
    assert ana.discovered_competitors([te("t1", [])]) == []


def test_the_comparison_question_never_reaches_a_replay_run():
    """A fixture provider can only answer authored probe ids, so demo runs must not ask it."""
    prov = fixture.FixtureProvider("A")
    run = graph.execute(graph.new_run(prov.profile, prov), prov)
    assert not [p for p in run.probes if p.id == ana.COMPARISON_PROBE_ID]
    assert all(p.phase == "baseline" for p in run.probes if p.kind == "named")


# ---------------------------------------------------------------- live round two
class FakeEvaluator:
    """Labels every answer the same way. The validators still check them against the text."""
    model = "test-evaluator"

    def __init__(self, competitors, mentioned=False, quotes=()):
        self.competitors = competitors
        self.mentioned = mentioned
        self.quotes = list(quotes)

    def label(self, probe, answer, attributes, profile):
        return dict(mentioned=self.mentioned, recommended=False, negative_mention=False,
                    competitor_recommendations=list(self.competitors), evidence_quotes=self.quotes,
                    on_topic=True, attributes=[])


def live_run(competitors, answer_text, mentioned=False, quotes=()):
    from providers import live
    message = {"type": "message", "content": [{"type": "output_text", "text": answer_text,
                                               "annotations": []}]}
    transport = lambda *_: {"output": [{"type": "web_search_call"}, message]}
    f = fixture.FixtureProvider("A")
    prov = live.LiveProvider(f.attributes(), f.named_probes(), profile=f.profile,
                             model="test-model", transport=transport,
                             evaluator=FakeEvaluator(competitors, mentioned, quotes))
    return graph.execute(graph.new_run(f.profile, prov, mode="live_api"), prov)


def test_round_two_compares_against_the_names_ai_actually_gave():
    run = live_run(["Linear"], "Linear is a good option for this.")
    cmp = next(p for p in run.probes if p.id == ana.COMPARISON_PROBE_ID)
    assert cmp.text == "How does Notion compare to Linear?"
    assert any(a.probe_id == cmp.id and a.status == "ok" for a in run.answers)
    assert any("Competitors discovered, not asked for: Linear." in l for l in run.log)


def test_the_comparison_answer_does_not_move_the_baseline_alignment():
    """It is chosen using the baseline results, so counting it would let round two grade itself."""
    run = live_run(["Linear"], "Linear is a good option for this.")
    named = [p for p in run.probes if p.kind == "named"]
    assert len(named) == 9 and run.drift.n_named == 8   # the eight baseline brand questions only


def test_no_competitor_named_means_no_comparison_question_and_a_stated_limitation():
    run = live_run([], "Several tools could work here.")
    assert not [p for p in run.probes if p.id == ana.COMPARISON_PROBE_ID]
    assert any("no comparison question was asked" in l for l in run.drift.limitations)


# ---------------------------------------------------------------- planning budgets
def weighted(n):
    return [Attribute(id=f"a{i}", label=f"Claim {i}", intended_weight=0.5,
                      buyer_questions=[f"Which tool number {i} option {j} suits a small team?"
                                       for j in (1, 2, 3)])
            for i in range(1, n + 1)]


def test_weighting_more_claims_than_there_are_topics_still_plans_a_valid_run():
    """Truncating to MAX_TOPICS must drop the questions too, or every probe of the 5th claim is an
    orphan and `validate_and_freeze` kills the run with an unreadable id-shaped error."""
    attrs = weighted(6)
    topics, probes = ana.blind_probes_from_attributes(attrs, PROFILE)
    assert len(topics) == ana.MAX_TOPICS
    assert {p.topic_id for p in probes} == {t.id for t in topics}
    assert len(probes) == ana.MAX_TOPICS * ana.PER_TOPIC <= graph.MAX_BASELINE
    assert ana.validate_probes(probes, topics, PROFILE) == []


def test_a_brand_question_colliding_with_an_attribute_is_dropped_at_onboarding(store):
    """'What kind of TEAM…' against the alias 'team' used to pass onboarding and then abort every
    later run in validate_and_freeze, with no way to repair the saved company from the UI."""
    attrs = [Attribute(id="collab", label="Built for collaboration", aliases=["team", "people"])]
    probes = onboarding.named_probes_for(PROFILE, attrs)
    assert probes and len(probes) < len(onboarding.NAMED_TEMPLATES)
    assert ana.validate_named_probes(probes, attrs) == []
    # and the company a run is built from carries the same, already-vetted set
    reports.save_company(mk_company(attrs=attrs))
    assert [p.id for p in CompanyProvider(reports.load_company("abc123")).named_probes()] \
        == [p.id for p in probes]


def test_onboard_vetting_drops_brand_leaking_buyer_questions_and_says_so():
    attrs = [Attribute(id="fast", label="Fast to set up",
                       buyer_questions=["Which tool sets up fastest?", "Is Acme quick to set up?"])]
    warnings = main.vet_questions(PROFILE, attrs)
    assert attrs[0].buyer_questions == ["Which tool sets up fastest?"]
    assert any("named you" in w and "Fast to set up" in w for w in warnings)


def test_onboard_vetting_says_how_many_brand_questions_are_left():
    attrs = [Attribute(id=f"a{i}", label=f"Claim {i}",
                       aliases=["describe", "use", "strengths", "recommend", "changed", "team"])
             for i in range(1, 3)]
    warnings = main.vet_questions(PROFILE, attrs)
    assert any("brand question(s) remain" in w for w in warnings)


# ---------------------------------------------------------------- added claims
def test_an_added_claim_is_intended_by_construction_and_survives_into_the_report(store):
    reports.save_company(mk_company(pages=["p1", "p2"]))
    out = main.patch_company("abc123", main.CompanyPatch(added=[main.AddedAttribute(label="Secure by default")]))
    added = next(a for a in out["attributes"] if a["label"] == "Secure by default")
    assert added["intended_weight"] == 0.5
    company = reports.load_company("abc123")
    attr = next(a for a in company.attributes if a.id == "secure_by_default")
    assert attr.intended and drift.relevant(attr, None)


def test_an_added_claim_gets_buyer_questions_from_the_same_model_interface(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(onboarding_model, "default_transport",
                        lambda *_: '{"buyer_questions": ["What keeps customer data safe?", '
                                   '"Is Acme secure?"]}')
    reports.save_company(mk_company())
    out = main.patch_company("abc123", main.CompanyPatch(added=[main.AddedAttribute(label="Secure by default")]))
    added = next(a for a in out["attributes"] if a["label"] == "Secure by default")
    # the brand-leaking one is refused, not rewritten, and the refusal is visible
    assert added["buyer_questions"] == ["What keeps customer data safe?"]
    assert any("named you" in w for w in out["warnings"])


def test_an_added_claim_without_a_key_is_still_added_and_the_omission_is_stated(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reports.save_company(mk_company())
    out = main.patch_company("abc123", main.CompanyPatch(added=[main.AddedAttribute(label="Secure by default")]))
    added = next(a for a in out["attributes"] if a["label"] == "Secure by default")
    assert added["buyer_questions"] == []
    assert any("brand axis only" in w for w in out["warnings"])


# ---------------------------------------------------------------- thin sites
def test_a_thin_site_is_saved_with_a_warning_rather_than_refused(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(fetching, "fetch_site",
                        lambda url, max_pages: [("https://acme.example/", "we set up in minutes")])
    monkeypatch.setattr(onboarding_model, "default_transport", lambda *_: json.dumps(
        {"name": "Acme", "one_liner": "Acme sets up fast.", "attributes": [
            {"id": "fast", "label": "Fast to set up", "description": "New accounts are usable in "
             "minutes without a migration project.", "claim_quotes": ["we set up in minutes"],
             "buyer_questions": ["Which tool sets up fastest?"]}]}))
    out = main.onboard(url="https://acme.example/", name="Acme")
    assert reports.load_company(out["id"]).id == out["id"]   # the paid crawl is not discarded
    assert any("too little for a reliable claim percentage" in w for w in out["warnings"])


def test_a_repeated_buyer_question_is_dropped_before_the_company_is_saved():
    """Two claims sharing one generic question used to pass onboarding and then abort every run in
    validate_and_freeze with 'duplicates an earlier question'."""
    shared = "What is the best project management tool for a small team?"
    attrs = [Attribute(id="project_tracking", label="Project tracking", intended_weight=0.5,
                       buyer_questions=[shared, "Which tool tracks work across teams?"]),
             Attribute(id="task_management", label="Task management", intended_weight=0.5,
                       buyer_questions=[shared.upper(), "Which tool keeps a backlog tidy?"])]
    warnings = main.vet_questions(PROFILE, attrs)
    assert attrs[1].buyer_questions == ["Which tool keeps a backlog tidy?"]
    assert any("repeated one already asked" in w and "Task management" in w for w in warnings)
    topics, probes = ana.blind_probes_from_attributes(attrs, PROFILE)
    assert ana.validate_probes(probes, topics, PROFILE) == []


def test_a_claim_the_customer_added_cannot_be_weighted_away(store):
    reports.save_company(mk_company())
    out = main.patch_company("abc123", main.CompanyPatch(added=[main.AddedAttribute(label="Secure by default")]))
    assert next(a for a in out["attributes"] if a["id"] == "secure_by_default")["added_by_user"] is True
    with pytest.raises(HTTPException) as e:
        main.patch_company("abc123", main.CompanyPatch(weights={"secure_by_default": 0.0}))
    assert e.value.status_code == 400 and "Delete it instead" in e.value.detail
    assert reports.load_company("abc123").attributes[-1].intended


def test_removing_an_added_claim_is_an_explicit_delete_and_extracted_claims_are_not_deletable(store):
    reports.save_company(mk_company())
    main.patch_company("abc123", main.CompanyPatch(added=[main.AddedAttribute(label="Secure by default")]))
    with pytest.raises(HTTPException) as e:
        main.delete_attribute("abc123", "fast")
    assert e.value.status_code == 400
    out = main.delete_attribute("abc123", "secure_by_default")
    assert [a["id"] for a in out["attributes"]] == ["fast"]
    assert [a.id for a in reports.load_company("abc123").attributes] == ["fast"]


# ---------------------------------------------------------------- zones
def test_a_claim_the_company_states_but_never_weighted_is_unprioritised_not_imposed():
    """The default state of every onboarded attribute until a slider moves. Calling it 'imposed'
    tells the company AI asserts something they never claimed, beside their own validated quote."""
    claimed = Attribute(id="fast", label="Fast to set up", claim_evidence_ids=["pg1"],
                        claim_quotes=["set up in minutes"], claim_pages=3, claim_pages_total=4)
    assert claimed.claimed and not claimed.intended
    assert drift.classify(claimed, 0.75, drift.claim_strength(claimed)) == ("unprioritised", "unprioritised_claim")
    # an attribute no page states keeps the original meaning of imposed
    never = Attribute(id="pricey", label="Expensive", claim_pages=0, claim_pages_total=4)
    assert drift.classify(never, 0.75, drift.claim_strength(never)) == ("imposed", "imposed_identity")


def test_a_claim_mentioned_too_little_to_count_as_echoed_is_still_never_imposed():
    """The ordinary band: mentioned in 2 of 7 answers, above IMPOSED_MIN and below ECHO_THRESHOLD.
    Gating the zone on the echo left this reading 'AI asserts this about you without you claiming
    it' next to that same row's '50% of pages (3 of 6)'."""
    claimed = Attribute(id="fast", label="Fast to set up", claim_evidence_ids=["pg1", "pg3", "pg5"],
                        claim_quotes=["set up in minutes"], claim_pages=3, claim_pages_total=6)
    echo_rate = 2 / 7
    assert drift.IMPOSED_MIN <= echo_rate < drift.ECHO_THRESHOLD
    assert drift.relevant(claimed, echo_rate)
    assert drift.classify(claimed, echo_rate, drift.claim_strength(claimed)) \
        == ("unprioritised", "unprioritised_claim")


def test_an_added_claim_cannot_be_created_unintended():
    """The floor lives on the contract, not only on the slider: a client posting 0 is refused."""
    with pytest.raises(ValidationError):
        main.AddedAttribute(label="Secure by default", intended_weight=0.0)
    assert main.AddedAttribute(label="Secure by default").intended_weight == 0.5


def test_the_target_is_never_its_own_competitor(store):
    """An evaluator listing the target among "other brands" is a routine slip, and this list reaches
    both the report table and a paid question: "How does Notion compare to Notion and Linear?"."""
    text = "Notion and Linear are good options for this."
    run = live_run(["Notion", "Linear"], text, mentioned=True, quotes=[text])
    named = {c for te in run.topic_evaluations for c in te.top_competitors}
    assert named == {"Linear"}
    cmp = next(p for p in run.probes if p.id == ana.COMPARISON_PROBE_ID)
    assert cmp.text == "How does Notion compare to Linear?"
    # dropping the self-reference is a correction, not an evidence failure: the answer still scores
    assert all(e.valid for e in run.evaluations if e.probe_id.endswith("-b1"))


def test_a_claim_you_never_weighted_is_not_filed_under_gaps():
    """`unprioritised` is the company's own claim being repeated back. Both report surfaces read the
    same list, so neither can quietly start calling it somebody's problem."""
    assert "unprioritised" not in drift.GAP_ZONES and "landed" not in drift.GAP_ZONES
    claimed = Attribute(id="fast", label="Fast to set up", claim_evidence_ids=["pg1"],
                        claim_quotes=["set up in minutes"], claim_pages=3, claim_pages_total=6)
    zone, _ = drift.classify(claimed, 0.75, drift.claim_strength(claimed))
    assert zone not in drift.GAP_ZONES
