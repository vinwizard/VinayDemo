"""Buyer visibility on two fronts, side by side: where AI already places the company (the attribute
its brand answers most endorse) and where the company's own site aims to be (the core category).

Also the defects from a live Profound run: every try is saved and scored, a set is flagged when
its control answer leaves the brand out, and a generic alias ("AI Marketer") is not the brand.
No key, no network: transports, the judge and the question writer are injected.
"""
from collections import Counter

import graph
import reports
from agents import ana, evaluation
from providers import fixture, live
from schemas import Answer, CompanyProfile, Probe, distinctive_alias
from scoring import mentions_alias

F = fixture.FixtureProvider("A")
AIMING = "connected workspace software"
AIM_QS = [f"Which workspace tool suits a team of {n}?" for n in (5, 10, 20, 50, 100, 200)]
PLACED = next(a for a in F.attributes() if a.id == "ai_native")   # "AI-native workspace"
WRITTEN = [f"Which AI workspace can draft documents for a team of {n}?" for n in (3, 30, 300)]


class Judge:
    """Labels what the answer says. Brand answers endorse the AI-native claim, verbatim."""
    model = "test-judge"

    def label(self, probe, answer, attributes, profile):
        named = profile.name in answer.text
        quote = "an AI-native workspace"
        return dict(mentioned=named, recommended=False, negative_mention=False,
                    competitor_recommendations=[c for c in ("Linear", "Asana", "Coda") if c in answer.text],
                    evidence_quotes=[answer.text] if named else [], on_topic=True,
                    attributes=[dict(attribute_id="ai_native", quote=quote, polarity="positive")]
                    if probe.kind == "named" and quote in answer.text else [])

    def discover(self, profile, attributes, answers):
        return []


def run_fronts(monkeypatch, aiming=AIMING, placed_says=lambda n: "Notion fits.", tries=3):
    asked = Counter()
    profile = F.profile.model_copy(update=dict(core_category=aiming, category_questions=AIM_QS))
    placed_qs = set(PLACED.buyer_questions) | set(WRITTEN)

    def transport(messages, model, timeout):
        q = messages[-1]["content"]
        asked[q] += 1
        text = ("Notion, Coda and Linear lead." if q == f"What are the leading tools for {PLACED.label}?"
                else "Linear, Asana and Coda lead." if q.startswith("What are the leading tools")
                else placed_says(asked[q]) if q in placed_qs
                else "Coda fits." if q in AIM_QS else "Notion is an AI-native workspace for teams.")
        return {"output": [{"type": "web_search_call"},
                           {"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    monkeypatch.setenv(live.TRIES_ENV, str(tries))
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model="test-model",
                             transport=transport, evaluator=Judge(), writer=lambda l, d, n: WRITTEN[:n])
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
    assert [(s.front, s.category, s.questions) for s in d.sets] == [
        ("placed", "AI-native workspace", 6), ("aiming", AIMING, 6)]
    placed, aiming = d.sets
    assert (placed.visibility, aiming.visibility, d.visibility_gap) == (50.0, 0.0, 50.0)
    assert (d.placed_category, d.aiming_category) == ("AI-native workspace", AIMING)
    # same total buyer budget as one set: 12 questions, split evenly
    assert len([p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]) == graph.MAX_BASELINE
    # each front has its own control, and only the one that leaves the brand out is flagged
    assert (placed.control_probe_id, aiming.control_probe_id) == ("ctl-2", "ctl-1")
    assert placed.low_confidence is None and "but not Notion" in aiming.low_confidence
    blind = [p for p in run.probes if p.kind == "blind"]
    assert not any(ana.brand_leaks(p.text, run.profile) for p in blind)


def test_the_same_category_on_both_fronts_is_asked_once_and_said_so(monkeypatch):
    run, _ = run_fronts(monkeypatch, aiming="AI-native workspace tools")
    assert [s.front for s in run.drift.sets] == ["both", None]
    assert any("so one set of buyer questions was asked" in l for l in run.log)
    assert len([p for p in run.probes if p.phase == "control"]) == 1
    # the budget never shrinks: the claims' own questions fill the other half, counted in neither front
    both, claims = run.drift.sets
    assert (both.questions, claims.questions, claims.category) == (6, 6, None)
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
    assert placed and all(t.positioning_point_ids == [] and t.fit_evidence_ids == [] for t in placed)
    aiming = [t for t in topics if t.front == "aiming" and t.kind == "buyer"]
    assert all(t.positioning_point_ids for t in aiming)   # the site's own category keeps its homepage


def test_a_front_with_no_questions_says_why_not_that_its_category_is_missing(monkeypatch):
    profile = F.profile.model_copy(update=dict(core_category=AIMING, category_questions=[]))
    _, _, _, missing = ana.blind_probes_for_fronts(profile, PLACED, WRITTEN, F.attributes())
    assert list(missing) == ["aiming"] and "no buyer questions are saved" in missing["aiming"]
    _, _, _, missing = ana.blind_probes_for_fronts(
        F.profile.model_copy(update=dict(core_category=AIMING, category_questions=AIM_QS)), PLACED, [])
    assert list(missing) == ["placed"] and "Where AI places Notion was not measured" in missing["placed"]
    run, _ = run_fronts(monkeypatch)
    assert run.drift.missing_fronts == {}


def test_every_try_is_asked_saved_and_scored_and_the_range_comes_from_them(monkeypatch, tmp_path):
    """Regression: the live run showed one saved answer per buyer question beside "3 tries"."""
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    # the placed questions name the brand on tries 1 and 2 only: per-try 50, 50, 0
    run, asked = run_fronts(monkeypatch, placed_says=lambda n: "Notion fits." if n < 3 else "Coda fits.")
    reports.save_run(run)
    run = reports.load_run(run.id)
    buyer = [p for p in run.probes if p.kind == "blind" and p.phase == "baseline"]
    tries = {p.id: sorted(a.try_no for a in run.answers + run.repeat_answers if a.probe_id == p.id)
             for p in buyer}
    assert all(t == [1, 2, 3] for t in tries.values()) and all(asked[p.text] == 3 for p in buyer)
    evals = Counter(e.probe_id for e in run.evaluations + run.repeat_evaluations)
    assert all(evals[p.id] == 3 for p in buyer)
    placed = run.drift.sets[0]
    assert (placed.tries, placed.visibility, placed.visibility_range) == (3, 33.3, [0.0, 50.0])
    named = Counter(e.probe_id for e in run.evaluations + run.repeat_evaluations if e.mentioned)
    assert {named[p.id] for p in buyer if p.topic_id.startswith("placed")} == {2}   # "named in 2 of 3"


def test_offline_replay_stays_one_unlabelled_set():
    run = graph.execute(graph.new_run(F.profile, F), F)
    [s] = run.drift.sets
    assert (s.front, s.visibility, s.tries, s.questions) == (None, 54.2, 1, 12)
    assert run.drift.visibility_gap is None


# ---------------------------------------------------------------- generic aliases are not the brand
def test_generic_phrases_are_not_aliases():
    for generic in ("AI Marketer", "AI Agents", "Agents", "AI"):
        assert not distinctive_alias(generic, "Profound")
    for kept in ("Profound", "Profound Agents", "Jira", "Conversation Explorer"):
        assert distinctive_alias(kept, "Profound")
    p = CompanyProfile(name="Profound", domain="tryprofound.com",
                       aliases=["Profound", "AI Marketer", "Profound Agents", "Conversation Explorer"])
    assert p.names() == ["Profound", "Profound Agents", "Conversation Explorer"]
    assert ana.brand_leaks("Is Conversation Explorer any good?", p) == ["Conversation Explorer"]
    assert ana.brand_leaks("Which AI marketer tool suits a startup?", p) == []


def test_a_different_product_is_not_a_mention():
    assert not mentions_alias("Try AiMarketer for campaigns.", ["AI Marketer"])
    p = CompanyProfile(name="Profound", domain="tryprofound.com", aliases=["AI Marketer"])
    probe = Probe(id="b1", topic_id="t", text="q", phase="baseline", purpose="p")
    a = Answer(probe_id="b1", text="AiMarketer and AI Marketer tools help.", provenance="synthetic",
               fixture_labels=dict(mentioned=False, recommended=False, negative_mention=False,
                                   competitor_recommendations=[], evidence_quotes=[]))
    e = evaluation.evaluate(probe, a, p)
    assert e.valid and not e.mentioned and e.strength == 0


def test_onboarding_keeps_only_distinctive_aliases():
    from agents.onboarding_model import build_profile
    p = build_profile({"name": "Profound", "aliases": ["AI Marketer", "Profound Agents", "AI Agents"]},
                      [], "tryprofound.com")
    assert p.aliases == ["Profound", "Profound Agents"]
