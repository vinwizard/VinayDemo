"""The positioning map: deterministic on fake vectors, the drift arrow runs from where AI places the
brand to where its site aims, both axes are always named after one of the company's claims, and
replays carry the authored sample without moving a score."""
import pytest

import positioning
from schemas import Answer, Attribute, CompanyProfile, PositioningPoint, Probe, QueryEvaluation, Run
from test_retrieval import replay

VOCAB = ["wiki", "task", "meeting", "ai"]


def by_words(texts):
    return [[t.lower().count(w) + 0.01 for w in VOCAB] for t in texts]


def run():
    ok = dict(provenance="live_api", provider="openai", model="m", collected_at="2026-09-22T00:00:00")
    return Run(
        id="r", mode="live_api", profile=CompanyProfile(name="Acme", domain="acme.test", positioning_points=[
            PositioningPoint(id="p1", text="Acme is the AI workspace. Acme AI runs your ai agents.")]),
        probes=[Probe(id="n1", topic_id="t", text="What is Acme?", kind="named", phase="baseline", purpose="x"),
                Probe(id="b1", topic_id="t", text="Best wiki tools?", phase="baseline", purpose="x")],
        answers=[Answer(probe_id="n1", text="Acme is a wiki for your team wiki pages. It keeps a wiki.", **ok),
                 Answer(probe_id="b1", text="Wikia is a wiki with wiki pages for docs. "
                                            "Taskly tracks every task and task list well. Nothing else here.", **ok)],
        evaluations=[QueryEvaluation(probe_id="b1", valid=True, competitor_recommendations=["Wikia", "Taskly", "Ghost"],
                                     explanation="x")],
        attributes=[Attribute(id="a1", label="Knowledge wiki"), Attribute(id="a2", label="AI agents"),
                    Attribute(id="a3", label="Meeting notes")])


def test_projection_is_deterministic_and_the_arrow_points_at_the_site():
    m = positioning.build(run(), embed=by_words)
    assert m == positioning.build(run(), embed=by_words)
    seen, aim, *rivals = m.points
    assert (seen.kind, aim.kind, [r.name for r in rivals]) == ("seen", "intended", ["Wikia", "Taskly"])
    assert m.aim == "site"
    assert m.closest == ["Wikia", "Taskly"]      # the brand as AI tells it is a wiki
    assert rivals[0].sentences == ["Wikia is a wiki with wiki pages for docs."]
    assert m.x_axis == ["AI agents"] and m.y_axis == ["Knowledge wiki"]  # what the dots differ on most
    assert aim.x > seen.x and m.toward == "AI agents"  # the site talks about agents more than AI does
    assert "1 less-named rivals were left off" in m.notes[0]  # Ghost: named, never described


def test_both_axes_are_named_even_when_every_claim_sits_at_one_end():
    # Amgen, Notion and Profound, live: every claim describes the company, so all of them sat at one
    # end of each PCA axis, and an axis was named only with a claim at BOTH ends. No live map ever
    # named an axis ("No claim lines up with either axis, so they have no name").
    r = run()
    r.attributes = [Attribute(id="a1", label="Knowledge wiki"), Attribute(id="a2", label="Wiki pages"),
                    Attribute(id="a3", label="Team wiki", intended_weight=1.0)]
    m = positioning.build(r, embed=by_words)
    assert m.x_axis == ["Team wiki"]            # across: the claim weighted highest
    assert len(m.y_axis) == 1 and m.y_axis != m.x_axis and m.explained is not None


def test_an_axis_is_one_claim_and_the_other_axis_is_what_is_left():
    means = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]]
    claims = [Attribute(id="x", label="X"), Attribute(id="y", label="Y", intended_weight=0.5)]
    coords, ix, iy, shown = positioning.claim_axes(means, claims, [[1, 1, 0], [0, 1, 0]])
    assert (ix, iy) == (1, 0) and 0 < shown <= 1  # across is the weighted claim, however little it spreads


def test_no_rival_means_no_map_and_a_reason():
    r = run()
    r.evaluations = []
    m = positioning.build(r, embed=by_words)
    assert not m.points and "named a rival" in m.reason


def test_replay_carries_the_authored_sample_and_moves_no_score():
    for scenario, score in (("A", 21.4), ("B", 27.9)):
        r = replay(scenario)
        m = r.positioning
        assert m.provenance == "synthetic" and m.model is None
        assert len(m.x_axis) == 2 and len(m.y_axis) == 2  # the authored sample is labelled too
        assert r.drift.alignment == score
        texts = " ".join(a.text for a in [*r.answers, *r.repeat_answers])
        for p in m.points:  # verbatim: every sentence is in an answer or on the site
            assert all(s in texts or s in [q.text for q in r.profile.positioning_points] for s in p.sentences)
        assert "authored, not computed" in " ".join(r.log)


def test_site_basis_until_a_claim_is_weighted_then_the_weighted_claims():
    assert positioning.build(run(), embed=by_words).aim == "site"
    r = run()
    r.attributes[1].intended_weight = 1.0
    r.attributes[2].intended_weight = 0.2
    m = positioning.build(r, embed=by_words)
    aim = m.points[1]
    assert m.aim == "intended" and aim.sentences == ["AI agents", "Meeting notes"]
    r.attributes[2].intended_weight = 1.0
    assert (positioning.build(r, embed=by_words).points[1].x, positioning.build(r, embed=by_words).points[1].y) \
        != (aim.x, aim.y)  # the weights pull the aim


def test_repeated_tries_count_each_sentence_once():
    r = run()
    r.repeat_answers = [a.model_copy() for a in r.answers]
    m = positioning.build(r, embed=by_words)
    assert m == positioning.build(run(), embed=by_words)
    assert m.points[0].sentences == ["Acme is a wiki for your team wiki pages.", "It keeps a wiki."]


def test_rivals_named_but_never_described_get_their_own_reason():
    r = run()
    r.evaluations[0].competitor_recommendations = ["Ghost"]
    m = positioning.build(r, embed=by_words)
    assert not m.points and "never described one in a sentence" in m.reason


def test_rescore_moves_the_aim_to_the_weighted_claims_without_asking_a_model(monkeypatch, tmp_path):
    import access
    import embeddings
    import graph
    sample = replay("A")
    live = replay("A")
    live.positioning = positioning.build(live)  # embeds once, through the (faked) metered call
    monkeypatch.setattr(access, "_create", lambda *a, **k: pytest.fail("no model call expected"))
    monkeypatch.setattr(access, "_embed", lambda *a, **k: pytest.fail("no embedding call expected"))
    graph.rescore(sample, {sample.attributes[0].id: 0.5})
    assert sample.positioning.provenance == "synthetic" and sample.positioning.aim == "site"

    graph.rescore(live, {a.id: 0.5 for a in live.attributes[:2]})
    assert live.positioning.aim == "intended" and live.positioning.points
    assert live.positioning.points[1].sentences == [positioning._text(a) for a in live.attributes if a.intended]

    before = live.positioning.model_copy(deep=True)
    monkeypatch.setattr(embeddings, "_path", lambda: tmp_path / "empty.db")
    graph.rescore(live, {live.attributes[2].id: 0.9})
    assert live.positioning.points == before.points
    assert "a text it needs was never embedded" in live.positioning.notes[-1]

    monkeypatch.setattr(positioning, "claim_axes", lambda *a: 1 / 0)
    monkeypatch.setattr(embeddings, "_path", lambda: tmp_path / "embeddings.db")
    graph.rescore(live, {live.attributes[2].id: 0.4})
    assert live.positioning.points == before.points and "ZeroDivisionError" in live.log[-2]


def test_a_division_is_counted_as_its_parent_company_and_never_shown_twice():
    # Amgen on gpt-6-luna, 22 Sep 2026: the map drew "Johnson & Johnson" and "Johnson & Johnson
    # Innovative Medicine" as two rivals, from two answers naming the one company two ways.
    from agents.evaluation import merge_divisions
    evals = [QueryEvaluation(probe_id="b1", valid=True, explanation="x",
                             competitor_recommendations=["Johnson & Johnson", "Pfizer"]),
             QueryEvaluation(probe_id="b2", valid=True, explanation="x",
                             competitor_recommendations=["Johnson & Johnson Innovative Medicine", "Johnson & Johnson"]),
             QueryEvaluation(probe_id="b3", valid=True, explanation="x",
                             competitor_recommendations=["Pfizer Oncology", "Novartis"])]
    merge_divisions(evals)
    assert [e.competitor_recommendations for e in evals] == [
        ["Johnson & Johnson", "Pfizer"], ["Johnson & Johnson"], ["Pfizer", "Novartis"]]
    merge_divisions(evals)  # idempotent
    assert evals[1].competitor_recommendations == ["Johnson & Johnson"]
