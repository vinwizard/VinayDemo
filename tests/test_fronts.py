"""Buyer visibility on two fronts, side by side: where AI already places the company (the attribute
its brand answers most endorse) and where the company's own site aims to be (the core category).

Also the defects from an earlier live run: every try is saved and scored, a set is flagged when
its control answer leaves the brand out, and a generic alias ("AI Marketer") is not the brand.
No key, no network: transports, the judge and the question writer are injected.
"""
from collections import Counter

from fakes import CAT_QS, Judge, openai_reply
import graph
import reports
import sampler
from agents import ana, evaluation
from providers import fixture, live
from schemas import Answer, CompanyProfile, Probe, distinctive_alias
from scoring import mentions_alias

F = fixture.FixtureProvider("A")
AIMING = "connected workspace software"
AIM_QS = CAT_QS
PLACED = next(a for a in F.attributes() if a.id == "ai_native")   # "AI-native workspace"
WRITTEN = [f"Which AI workspace can draft documents for a team of {n}?" for n in (3, 30, 300)]


# Brand answers endorse the AI-native claim, verbatim.
ENDORSE = ("ai_native", "an AI-native workspace")


def run_fronts(monkeypatch, aiming=AIMING, placed_says=lambda n: "Notion fits.", wobble=1,
               weighted=False):
    asked = Counter()
    profile = F.profile.model_copy(update=dict(core_category=aiming, category_questions=AIM_QS))
    placed_qs = set(PLACED.buyer_questions) | set(WRITTEN)

    def transport(messages, model, timeout):
        q = messages[-1]["content"]
        asked[q] += 1
        text = ("Notion, Coda and Linear lead." if q == f"Which companies lead in {PLACED.label}?"
                else "Linear, Asana and Coda lead." if q.startswith("Which companies lead in")
                else placed_says(asked[q]) if q in placed_qs
                else "Coda fits." if q in AIM_QS else "Notion is an AI-native workspace for teams.")
        return openai_reply(text, searched=True)

    # ±33 points: six questions frozen a front, four asked first — as many as the injected writer can
    # supply. These tests are about the fronts; test_sampler.py owns how many questions are asked.
    monkeypatch.setenv(sampler.MARGIN_ENV, "33")
    monkeypatch.setenv(sampler.WOBBLE_ENV, str(wobble))
    # unweighted unless asked: a weighted claim holds back a topic of its own (test_every_weighted_claim…)
    attributes = [a if weighted else a.model_copy(update=dict(intended_weight=None)) for a in F.attributes()]
    prov = live.LiveProvider(attributes, F.named_probes(), profile=profile, model="test-model",
                             transport=transport, evaluator=Judge(endorse=ENDORSE), writer=lambda l, d, n: WRITTEN[:n])
    prov.concurrency = 1
    return graph.execute(graph.new_run(profile, prov, mode="live_api"), prov), asked


def test_brand_answers_are_answered_before_buyer_questions_are_planned(monkeypatch):
    run, _ = run_fronts(monkeypatch)
    log = "\n".join(run.log)
    assert log.index("brand answers") < log.index("Where AI places Notion: AI-native workspace")
    assert "(endorsed in 8 of 8 brand answers)" in log
    assert "Where it aims to be: connected workspace software" in log


def test_two_fronts_are_measured_side_by_side_with_the_gap(monkeypatch):
    run, _ = run_fronts(monkeypatch)
    d = run.drift
    # every answer on a front agreed, so each stopped at look 1: four of its six frozen questions
    assert [(s.front, s.category, s.questions) for s in d.sets] == [
        ("placed", "AI-native workspace", 4), ("aiming", AIMING, 4)]
    placed, aiming = d.sets
    assert (placed.visibility, aiming.visibility, d.visibility_gap) == (50.0, 0.0, 50.0)
    assert (d.placed_category, d.aiming_category) == ("AI-native workspace", AIMING)
    # the same budget on each front: six frozen, split evenly; what neither needed is kept as unasked
    asked = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    assert len(asked) + len(run.sampler.unasked) == 2 * ana.set_questions() == 12
    assert [(f.front, f.pool, f.asked, f.stopped_early) for f in run.sampler.fronts] == [
        ("placed", 6, 4, True), ("aiming", 6, 4, True)]
    # each front has its own control, and only the one that leaves the brand out is flagged
    assert (placed.control_probe_id, aiming.control_probe_id) == ("ctl-2", "ctl-1")
    assert placed.low_confidence is None and "but not Notion" in aiming.low_confidence
    blind = [p for p in run.probes if p.kind == "blind"]
    assert not any(ana.brand_leaks(p.text, run.profile) for p in blind)


def test_every_weighted_claim_gets_its_own_buyer_questions_before_the_fronts_share_the_rest(monkeypatch):
    # Amgen on gpt-6-luna, 22 Sep 2026: the two fronts took all 24 questions, none of its three weighted
    # claims was asked about, and every Quick-wins fix it got cited no buyer question.
    run, _ = run_fronts(monkeypatch, weighted=True)
    weighted = [a.id for a in run.attributes if a.intended and a.buyer_questions and a.id != PLACED.id]
    buyer = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    topics = {t.id: t for t in run.topics}
    own = {p.topic_id[len("pos-"):] for p in buyer if topics[p.topic_id].front is None}
    held = min(len(weighted), ana.front_topics())
    assert len(own & set(weighted)) == held                      # the heaviest claims, one topic each
    assert [s.front for s in run.drift.sets][:2] == ["placed", "aiming"]
    assert [f.pool for f in run.sampler.fronts] == [ana.set_questions()] * 2   # held on top, not taken
    assert len(buyer) <= graph.max_baseline()


def test_three_weighted_claims_leave_each_front_its_look_2_pool_at_the_default_margin(monkeypatch):
    # Amgen, three weighted claims at ±20: each front was cut to 18 questions, short of the 23 that
    # look 2 needs, so a 50% front could never reach ±20 however many of them were asked.
    monkeypatch.delenv(sampler.MARGIN_ENV, raising=False)
    n2 = sampler.looks()[1]
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=[
        f"Which workspace tool suits a team of {n}?" for n in range(1, n2 + 1)]))
    placed_qs = [f"Which AI workspace can draft documents for a team of {n}?" for n in range(1, n2 + 1)]
    weighted = [a for a in F.attributes() if a.intended and a.buyer_questions and a.id != PLACED.id]
    assert len(weighted) == 3
    topics, probes, _, _ = ana.blind_probes_for_fronts(profile, PLACED, placed_qs, F.attributes())
    front = {t.id: t.front for t in topics}
    buyer = [p for p in probes if p.phase == "baseline"]
    assert Counter(front[p.topic_id] for p in buyer if front[p.topic_id]) == {"placed": n2, "aiming": n2}
    assert {t.id for t in topics if t.kind == "buyer" and not t.front} == {f"pos-{a.id}" for a in weighted}
    assert len(buyer) <= graph.max_baseline() and not ana.validate_probes(probes, topics, profile)


def test_the_same_category_on_both_fronts_is_asked_once_and_said_so(monkeypatch):
    run, _ = run_fronts(monkeypatch, aiming="AI-native workspace tools")
    assert [s.front for s in run.drift.sets] == ["both", None]
    assert any("so one set of unbranded questions was asked" in l for l in run.log)
    assert len([p for p in run.probes if p.phase == "control"]) == 1
    # the budget never shrinks: the claims' own questions fill the other half, counted in neither front
    both, claims = run.drift.sets
    # the front stopped at look 1; the claims' own questions are not a front, so all of them are asked
    assert (both.questions, claims.questions, claims.category) == (4, 6, None)
    topic = {t.id: t for t in run.topics}
    claim_ids = [p.topic_id for p in run.probes if p.phase == "baseline" and p.kind == "blind"
                 and topic[p.topic_id].front is None]
    assert claim_ids and all(t.startswith("pos-") for t in claim_ids)
    assert "pos-ai_native" not in claim_ids     # the placed claim is asked once, on its front


def test_one_word_in_common_is_not_the_same_category():
    for a, b in [("Project management", "Product management"), ("AI visibility", "AI marketing"),
                 ("Answer engine optimization", "Search engine optimization")]:
        assert not ana.same_category(a, b)
    assert ana.same_category("AI search visibility", "AI search visibility tracking")


def test_the_placed_front_cites_only_its_own_claim_evidence():
    found = PLACED.model_copy(update=dict(claim_evidence_ids=[], claimed=False))
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=AIM_QS))
    topics, _, _, _ = ana.blind_probes_for_fronts(profile, found, WRITTEN, F.attributes())
    placed = [t for t in topics if t.front == "placed" and t.kind == "buyer"]
    assert placed and all(t.positioning_point_ids == [] for t in placed)
    aiming = [t for t in topics if t.front == "aiming" and t.kind == "buyer"]
    assert all(t.positioning_point_ids for t in aiming)   # the site's own category keeps its homepage


def test_a_front_with_no_questions_says_why_not_that_its_category_is_missing(monkeypatch):
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=[]))
    _, _, _, missing = ana.blind_probes_for_fronts(profile, PLACED, WRITTEN, F.attributes())
    assert list(missing) == ["aiming"] and "no unbranded questions are saved" in missing["aiming"]
    _, _, _, missing = ana.blind_probes_for_fronts(
        F.profile.model_copy(update=dict(core_category=AIMING, category_questions=AIM_QS)), PLACED, [])
    assert list(missing) == ["placed"] and "Where AI places Notion was not measured" in missing["placed"]
    run, _ = run_fronts(monkeypatch)
    assert run.drift.missing_fronts == {}


def test_missing_front_reasons_reach_the_report_when_no_front_survives(monkeypatch):
    # a category saved without questions and no endorsement: only the claims are asked
    monkeypatch.setattr(Judge, "label", lambda self, probe, answer, attributes, profile: dict(
        mentioned=profile.name in answer.text, recommended=False, negative_mention=False,
        competitor_recommendations=[], evidence_quotes=[], on_topic=True, attributes=[]))
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=[]))
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="test-model",
                             transport=lambda *_: openai_reply("Coda fits."), evaluator=Judge())
    prov.concurrency = 1
    run = graph.execute(graph.new_run(profile, prov, mode="live_api"), prov)
    assert not any(t.front for t in run.topics)
    assert set(run.drift.missing_fronts) == {"placed", "aiming"}
    assert "no unbranded questions are saved" in run.drift.missing_fronts["aiming"]
    assert run.drift.missing_fronts["aiming"] in run.drift.limitations


def test_one_question_a_front_is_re_asked_and_the_wobble_comes_from_it(monkeypatch, tmp_path):
    """The wobble audit: each front's first question is asked once more, every other question once,
    and the range beside the number is those re-asks' wobble — nothing else's. Regression it keeps:
    every try is saved and scored, not just the first."""
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    # the audited placed question names the brand on its first ask only: per-try 50, 0
    run, asked = run_fronts(monkeypatch, placed_says=lambda n: "Notion fits." if n < 2 else "Coda fits.")
    reports.save_run(run)
    run = reports.load_run(run.id)
    buyer = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    tries = {p.id: sorted(a.try_no for a in run.answers + run.repeat_answers if a.probe_id == p.id)
             for p in buyer}
    audited = [p for p in buyer if tries[p.id] == [1, 2]]
    assert [p.id for p in audited] == run.sampler.wobble and {p.topic_id[:6] for p in audited} == {"placed", "cat-1"}
    assert all(tries[p.id] == [1] for p in buyer if p not in audited)
    assert all(asked[p.text] == (2 if p in audited else 1) for p in buyer)
    evals = Counter(e.probe_id for e in run.evaluations + run.repeat_evaluations)
    assert all(evals[p.id] == len(tries[p.id]) for p in buyer)
    placed = run.drift.sets[0]
    # four questions named the brand, the audited one on one of its two tries
    assert (placed.tries, placed.repeat_sample) == (2, 1)
    assert (placed.visibility, placed.visibility_range) == (43.8, [0.0, 50.0])
    # the sampler's rate counts each question's first ask only: fresh questions, one vote each
    assert (run.sampler.fronts[0].named, run.sampler.fronts[0].judged) == (4, 4)


def test_no_wobble_audit_measures_every_question_once_and_has_no_wobble(monkeypatch):
    run, asked = run_fronts(monkeypatch, wobble=0)
    buyer = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    assert run.repeat_answers == [] and all(asked[p.text] == 1 for p in buyer)
    assert run.drift.repeat_sample == 0 and run.drift.visibility_range is None
    assert run.drift.visibility == 25.0          # four questions named, four not


def test_offline_replay_stays_one_unlabelled_set():
    run = graph.execute(graph.new_run(F.profile, F), F)
    [s] = run.drift.sets
    assert (s.front, s.visibility, s.tries, s.questions) == (None, 54.2, 1, 12)
    assert run.drift.visibility_gap is None


# ---------------------------------------------------------------- generic aliases are not the brand
def test_generic_phrases_are_not_aliases():
    for generic in ("AI Marketer", "AI Agents", "Agents", "AI"):
        assert not distinctive_alias(generic, "Acme")
    for kept in ("Acme", "Acme Agents", "Jira", "Conversation Explorer"):
        assert distinctive_alias(kept, "Acme")
    p = CompanyProfile(name="Acme", domain="acme.example",
                       aliases=["Acme", "AI Marketer", "Acme Agents", "Conversation Explorer"])
    assert p.names() == ["Acme", "Acme Agents", "Conversation Explorer"]
    assert ana.brand_leaks("Is Conversation Explorer any good?", p) == ["Conversation Explorer"]
    assert ana.brand_leaks("Which AI marketer tool suits a startup?", p) == []


def test_a_different_product_is_not_a_mention():
    assert not mentions_alias("Try AiMarketer for campaigns.", ["AI Marketer"])
    p = CompanyProfile(name="Acme", domain="acme.example", aliases=["AI Marketer"])
    probe = Probe(id="b1", topic_id="t", text="q", phase="baseline", purpose="p")
    a = Answer(probe_id="b1", text="AiMarketer and AI Marketer tools help.", provenance="synthetic",
               fixture_labels=dict(mentioned=False, recommended=False, negative_mention=False,
                                   competitor_recommendations=[], evidence_quotes=[]))
    e = evaluation.evaluate(probe, a, p)
    assert e.valid and not e.mentioned and e.strength == 0


def test_onboarding_keeps_only_distinctive_aliases():
    from agents.onboarding_model import build_profile
    p = build_profile({"name": "Acme", "aliases": ["AI Marketer", "Acme Agents", "AI Agents"]},
                      [], "acme.example")
    assert p.aliases == ["Acme", "Acme Agents"]


def test_the_placed_front_is_asked_as_a_buyer_category_not_a_claim_label(monkeypatch):
    # Amgen, 22 Sep 2026: AI placed it at the claim "Focus on key therapy areas". Searched, written
    # about and controlled as if it were a category, it asked "Which software supports oncology
    # treatment planning?" and "What are the leading tools for Focus on key therapy areas?".
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=AIM_QS))
    monkeypatch.setenv(sampler.MARGIN_ENV, "33")   # six a front: the category's own six fill it, unwritten
    written_for = []

    def provider(category):
        return live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="m",
                                 transport=lambda *a: None, categorize=lambda label, description: category,
                                 writer=lambda l, d, n: written_for.append(l) or WRITTEN[:n])
    prov = provider("ai writing assistants for teams")
    topics, probes = prov.plan(profile, PLACED)
    assert {t.label for t in topics if t.front == "placed" and t.kind == "buyer"} == {"ai writing assistants for teams"}
    assert written_for == ["ai writing assistants for teams"] and prov.notes == []
    assert "Which companies lead in ai writing assistants for teams?" in {p.text for p in probes}
    # a category that names the brand is not asked: the claim's label stands, and the report says why
    leaky = provider("Notion alternatives")
    topics, _ = leaky.plan(profile, PLACED)
    assert {t.label for t in topics if t.front == "placed" and t.kind == "buyer"} == {PLACED.label}
    assert any("No buyer category could be written" in n for n in leaky.notes)
