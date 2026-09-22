"""Cited sources and share of voice, read off saved runs with no model calls."""
import re

import graph
from insights import cited_sources, share_of_voice, source_kind
from providers import fixture


def run_scenario(s):
    prov = fixture.FixtureProvider(s)
    return graph.execute(graph.new_run(fixture.bundled_profile(s), prov), prov)


def test_sources_rank_owned_and_third_party_separately():
    src = cited_sources(run_scenario("B"))
    by = {r["domain"]: r for r in src["sources"]}
    assert src["sources"][0]["domain"] == "example.com/demo-source-1"  # most-cited first
    assert by["notion.com"]["owned"]
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


def test_rival_only_sources_cite_rivals_in_buyer_answers_that_never_mention_the_brand():
    run = run_scenario("A")
    src = cited_sources(run)
    by = {r["domain"]: r for r in src["sources"]}
    assert src["rival_only"][:2] == ["example.com/demo-source-5", "example.com/demo-source-6"]  # 3 rivals each
    for d in src["rival_only"]:
        assert by[d]["rivals"] and by[d]["with_brand"] == 0 and not by[d]["owned"]
    # cited beside Confluence, but in an answer that also mentions Notion: not a gap
    assert by["example.com/demo-source-1"]["with_brand"] == 1
    assert "example.com/demo-source-1" not in src["rival_only"]
    assert by["notion.com"]["kind"] == "owned"


def test_a_rivals_own_site_is_never_a_site_to_get_onto():
    run = run_scenario("A")
    gap = {r["domain"]: r for r in cited_sources(run)["sources"]}[cited_sources(run)["rival_only"][0]]
    rival = gap["rivals"][0]["name"]
    host = re.sub(r"[^a-z0-9]", "", rival.lower()) + ".com"
    next(a for a in run.answers if a.probe_id == gap["probes"][0]).citations.append(f"https://{host}/")
    src = cited_sources(run)
    by = {r["domain"]: r for r in src["sources"]}
    assert by[host]["kind"] == "rival" and by[host]["with_brand"] == 0
    assert host not in src["rival_only"] and gap["domain"] in src["rival_only"]


def test_source_kinds():
    rivals = {"asana", "otter"}
    assert source_kind("asana.com", False, rivals) == "rival"
    assert source_kind("blog.otter.ai", False, rivals) == "rival"
    assert source_kind("g2.com", False, rivals) == "review"
    assert source_kind("old.reddit.com", False, rivals) == "community"
    assert source_kind("community.example.org", False, rivals) == "community"
    assert source_kind("techcrunch.com", False, rivals) == "media"
    assert source_kind("example.com/demo-source-1", False, rivals) == "other"
    assert source_kind("asana.com", True, rivals) == "owned"
