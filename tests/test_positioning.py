"""The positioning map: PCA on fake vectors is deterministic, the drift arrow runs from where AI
places the brand to where its site aims, axes are named only when a claim lines up with them, and
replays carry the authored sample without moving a score."""
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
    assert aim.x >= seen.x and aim.y >= seen.y  # axes oriented so the drift runs up and right
    assert m.closest == ["Wikia", "Taskly"]      # the brand as AI tells it is a wiki
    assert rivals[0].sentences == ["Wikia is a wiki with wiki pages for docs."]
    assert m.x_axis == ["Knowledge wiki", "AI agents"] and m.toward == "AI agents"
    assert "1 less-named rivals were left off" in m.notes[0]  # Ghost: named, never described


def test_pca_recovers_the_spread_on_a_line():
    coords, _, shown = positioning.pca2([[0, 0, 0], [1, 0, 0], [2, 0, 0]])
    assert [round(abs(x), 6) for x, _ in coords] == [1, 0, 1] and all(abs(y) < 1e-9 for _, y in coords)
    assert shown == 1.0


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
        assert r.drift.alignment == score
        texts = " ".join(a.text for a in [*r.answers, *r.repeat_answers])
        for p in m.points:  # verbatim: every sentence is in an answer or on the site
            assert all(s in texts or s in [q.text for q in r.profile.positioning_points] for s in p.sentences)
        assert "authored, not computed" in " ".join(r.log)
