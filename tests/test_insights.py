"""Cited sources and share of voice, read off saved runs with no model calls."""
import graph
from insights import cited_sources, share_of_voice
from providers import fixture


def run_scenario(s):
    prov = fixture.FixtureProvider(s)
    return graph.execute(graph.new_run(fixture.bundled_profile(s), prov), prov)


def test_sources_rank_owned_and_third_party_separately():
    src = cited_sources(run_scenario("B"))
    by = {r["domain"]: r for r in src["sources"]}
    assert src["sources"][0]["domain"] == "example.com/demo-source-1"  # most-cited first
    assert by["example.com/demo-source-1"]["target"]                    # third party, repeated
    assert by["notion.com"]["owned"] and not by["notion.com"]["target"]
    # a lookalike host is a third party, never the brand's own site
    assert not by["notion.com.example.net"]["owned"]
    assert all(r["answers"] == r["buyer"] + r["brand"] for r in src["sources"])


def test_share_of_voice_counts_answers_not_mentions():
    v = share_of_voice(run_scenario("A"))
    assert (v["questions"], v["brand"], v["brand_recommended"]) == (12, "Notion", 6)
    assert v["rivals"] and all(0 < r["count"] <= 12 for r in v["rivals"])
    assert v["reason"] is None


def test_share_of_voice_counts_brand_recommendations_like_competitors():
    run = run_scenario("A")
    for e in run.evaluations:
        e.mentioned, e.recommended = True, False  # named everywhere, recommended nowhere
    assert share_of_voice(run)["brand_recommended"] == 0


def test_share_of_voice_counts_a_tie_for_first_beyond_the_rivals_shown():
    run = run_scenario("A")
    for e in run.evaluations:
        e.competitor_recommendations = ["A", "B", "C", "D"]
    v = share_of_voice(run)
    assert len(v["rivals"]) == 3 and v["tied_top"] == 4


def test_empty_panels_say_why():
    run = run_scenario("A")
    for e in run.evaluations:
        e.competitor_recommendations = []
    for a in run.answers:
        a.citations = []
    assert "No competitor" in share_of_voice(run)["reason"]
    assert "cited a source" in cited_sources(run)["reason"]
    run.answers = []
    assert "no citations" in cited_sources(run)["reason"]
    assert "no voice" in share_of_voice(run)["reason"]
