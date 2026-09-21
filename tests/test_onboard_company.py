"""Onboarding a company that is not a bundled fixture: persistence, intent, discovered competitors.

A company used to BE a fixture filename. These checks pin the properties that let an arbitrary
company be measured without letting it quietly inherit the demo's data or the demo's numbers.
"""
import pytest
from fastapi import HTTPException

import api.main as main
import graph
import reports
from agents import ana, onboarding
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

    def __init__(self, competitors):
        self.competitors = competitors

    def label(self, probe, answer, attributes, profile):
        return dict(mentioned=False, recommended=False, negative_mention=False,
                    competitor_recommendations=list(self.competitors), evidence_quotes=[],
                    on_topic=True, attributes=[])


def live_run(competitors, answer_text):
    from providers import live
    message = {"type": "message", "content": [{"type": "output_text", "text": answer_text,
                                               "annotations": []}]}
    transport = lambda *_: {"output": [{"type": "web_search_call"}, message]}
    f = fixture.FixtureProvider("A")
    prov = live.LiveProvider(f.attributes(), f.named_probes(), profile=f.profile,
                             model="test-model", transport=transport,
                             evaluator=FakeEvaluator(competitors))
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
