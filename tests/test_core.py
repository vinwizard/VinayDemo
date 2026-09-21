"""Offline acceptance checks (agents.md section 10) for the engine. Run: python -m pytest"""
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

import graph
from agents import ana, evaluation, onboarding
from providers import fixture, imported, live
from reports import from_json, load_run, save_run, to_json, to_markdown
from schemas import Answer, CompanyProfile, PositioningPoint, Probe, Topic
from scoring import domain_matches, score_topic, visibility_score

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = {evaluation.INSIGHTS, evaluation.AGENTS, evaluation.TEMPLATES}


@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    def blocked(*a, **k):
        raise OSError("network disabled in tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def run_scenario(s):
    prov = fixture.FixtureProvider(s)
    return graph.execute(graph.new_run(fixture.bundled_profile(s), prov), prov)


@pytest.fixture(scope="module")
def runs():
    return {s: run_scenario(s) for s in "AB"}


PROFILE = fixture.bundled_profile("A")
PROBE = Probe(id="x-1", topic_id="kb", text="q", phase="baseline", purpose="t")


def synth(text, cites=(), **labels):
    base = dict(mentioned=False, recommended=False, negative_mention=False, competitor_recommendations=[],
                evidence_quotes=[], on_topic=True, outdated_claim_quote=None)
    return Answer(probe_id="x-1", text=text, citations=list(cites), provenance="synthetic", provider="fixture",
                  fixture_labels={**base, **labels})


# --- workflow ---------------------------------------------------------------
def test_both_scenarios_complete_offline(runs):
    for r in runs.values():
        assert r.status == "complete"
        assert len([p for p in r.probes if p.phase == "baseline" and p.kind == "blind"]) == 12
        assert len([p for p in r.probes if p.kind == "named"]) == 8
        assert len([p for p in r.probes if p.phase == "followup"]) == 4
        assert len(r.decisions) == 1


def test_three_agent_roles_in_workflow():
    agents = {a for _, a in graph.STAGES.values()}
    assert {"Agent 2 · Question planner", "Agent 3 · Answer evaluation", "Orchestrator"} <= agents
    assert hasattr(onboarding, "named_probes_for")  # Agent 1 (shown as the Onboarding stage in the UI)


def test_adaptive_selection_depends_on_results(runs):
    assert runs["A"].decisions[0].selected_topics == ["pt", "mtg"]
    assert runs["B"].decisions[0].selected_topics == ["po", "kb"]
    for r in runs.values():
        d = r.decisions[0]
        assert d.evidence_probe_ids and all(p.parent_probe_ids for p in d.new_probes)


def test_adaptive_policy_reads_current_evaluations(runs):
    """Same run, swapped evaluations -> different choice (not a fixed animation)."""
    r = runs["A"]
    swapped = [te.model_copy(update={"status": "observed presence", "gap_priority": 0.0})
               if te.topic_id == "pt" else te for te in r.topic_evaluations]
    d = ana.choose_followup(r.topics, swapped, r.evaluations, [p for p in r.probes if p.phase == "baseline"],
                            fixture.FixtureProvider("A").followup_bank(), r.profile)
    assert d.selected_topics == ["mtg", "po"]


def test_baseline_unchanged_after_followup(runs):
    for s, r in runs.items():
        base = [p for p in r.probes if p.phase == "baseline"]
        assert ana.baseline_hash(r.probes) == r.baseline_hash == ana.baseline_hash(base)
        ev, ans = {e.probe_id: e for e in r.evaluations}, {a.probe_id: a for a in r.answers}
        for t in [x for x in r.topics if x.kind == "buyer"]:
            ps = [p for p in base if p.topic_id == t.id and p.kind == "blind"]
            fresh = score_topic(t, "baseline", [ans[p.id] for p in ps], [ev[p.id] for p in ps])
            stored = next(x for x in r.topic_evaluations if x.topic_id == t.id and x.phase == "baseline")
            assert stored == fresh and stored.n == 3  # follow-ups never pooled into baseline


def test_round_limit_enforced(runs):
    assert all(len(r.decisions) <= graph.MAX_ADAPTIVE_ROUNDS for r in runs.values())


# --- explanations, provenance, findings --------------------------------------
def test_every_query_and_topic_explained(runs):
    for r in runs.values():
        ev = {e.probe_id: e for e in r.evaluations}
        for p in r.probes:
            assert ev[p.id].explanation
        for a in r.answers:
            assert a.provenance == "synthetic" and a.provider == "fixture" and a.collected_at is None and not a.search_executed
        for te in r.topic_evaluations:
            assert te.status and te.limitations and te.provenance == "synthetic"
        md = to_markdown(r)
        assert "SYNTHETIC DEMO" in md
        points = [l for l in md.split("## Positioning points")[1].splitlines() if l.startswith("- Point ")]
        assert [l.endswith("not tested") for l in points] == [False, False, False, False, True]  # pp5 has no topic


def test_every_gap_maps_to_capability_or_insufficient(runs):
    for r in runs.values():
        assert r.findings
        for f in r.findings:
            if f.profound_capability:
                assert f.capability_url in OFFICIAL and f.suggested_action and f.evidence_ids
            else:
                assert "insufficient" in f.interpretation.lower()
            assert f.limitations and f.provenance == "synthetic"
    caps = {f.profound_capability for f in runs["B"].findings}
    assert "FactCheck and associated correction workflows" in caps
    content = [f for r in runs.values() for f in r.findings if f.profound_capability.startswith("Content")]
    assert content and all(any("NOT confirmed" in l for l in f.limitations) for f in content)


def test_insufficient_evidence_finding_has_no_capability():
    t = Topic(id="kb", label="KB", buyer_need="n", positioning_point_ids=["pp1"], fit="strong")
    probes = [PROBE]
    a = Answer(probe_id="x-1", provenance="synthetic", provider="fixture", status="timeout")
    e = evaluation.evaluate(PROBE, a, PROFILE)
    te = score_topic(t, "baseline", [a], [e])
    [f] = evaluation.build_findings([t], [te], [e], probes)
    assert f.profound_capability is None and f.capability_url is None


# --- honesty rules ---------------------------------------------------------------
@pytest.mark.parametrize("bad", [dict(provider="gemini"), dict(model="gpt-x"), dict(collected_at="2026-09-18T00:00:00"),
                                 dict(search_executed=True)])
def test_synthetic_cannot_look_live(bad):
    with pytest.raises(ValidationError):
        Answer(probe_id="p", provenance="synthetic", **bad)


def test_fixture_labels_only_on_synthetic():
    with pytest.raises(ValidationError):
        Answer(probe_id="p", provenance="live_api", fixture_labels={})


def test_search_snapshot_never_scored():
    a = Answer(probe_id="x-1", text="Notion is great", provenance="web_research_snapshot")
    e = evaluation.evaluate(PROBE, a, PROFILE)
    te = score_topic(Topic(id="kb", label="KB", buyer_need="n", positioning_point_ids=[], fit="strong"), "baseline", [a], [e])
    assert not e.valid and te.n == 0 and te.visibility_score is None and "search snapshot" in te.excluded_reasons[0]


def test_snapshot_only_touches_profile_evidence():
    snap = imported.load_snapshot(imported.list_snapshots()[-1])
    p = imported.apply_snapshot(PROFILE, snap)
    assert {e.source_type for e in p.evidence} == {"web_research_snapshot"}
    for e in p.evidence:
        assert e.url.startswith("https://www.notion.com") and e.retrieved_at
    fixture.FixtureProvider("A").check_profile(p)  # factual edit: replay still allowed


# --- scoring --------------------------------------------------------------------
def test_visibility_math():
    assert visibility_score([2, 1, 0]) == 50
    assert visibility_score([]) is None


def test_no_eligible_answers_gives_null():
    t = Topic(id="kb", label="KB", buyer_need="n", positioning_point_ids=[], fit="strong")
    a = Answer(probe_id="x-1", provenance="synthetic", provider="fixture", status="timeout")
    te = score_topic(t, "baseline", [a], [evaluation.evaluate(PROBE, a, PROFILE)])
    assert te.n == 0 and te.excluded == 1
    assert te.visibility_score is None and te.mention_rate is None and te.gap_priority is None
    assert te.status == "insufficient evidence"


# --- edge cases -----------------------------------------------------------------
def test_negative_mention():
    e = evaluation.evaluate(PROBE, synth("Notion is clunky for this.", mentioned=True, negative_mention=True,
                                         evidence_quotes=["Notion is clunky for this."]), PROFILE)
    assert e.valid and e.negative_mention and e.strength == 0 and "criticism" in e.explanation


def test_citation_only_reference():
    e = evaluation.evaluate(PROBE, synth("Use Confluence.", ["https://www.notion.com/help"],
                                         competitor_recommendations=["Confluence"]), PROFILE)
    assert e.valid and e.owned_citation and not e.mentioned and e.strength == 0 and "citation-only" in e.explanation


def test_ambiguous_alias():
    e = evaluation.evaluate(PROBE, synth("I like the notion of a second brain."), PROFILE)
    assert e.valid and not e.mentioned and any("Ambiguous alias" in w for w in e.warnings)
    wrong = evaluation.evaluate(PROBE, synth("I like the notion of a second brain.", mentioned=True,
                                             evidence_quotes=["notion of a second brain"]), PROFILE)
    assert not wrong.valid  # a label claiming the common word is the brand is rejected


@pytest.mark.parametrize("url,owned", [("https://notion.com/x", True), ("https://www.notion.so/x", True),
                                       ("https://notion.com.example.net/x", False), ("https://notion.so.example.com", False),
                                       ("https://mynotion.com", False), ("https://notion.company.io", False)])
def test_deceptive_domains(url, owned):
    assert domain_matches(url, PROFILE.all_domains()) is owned


def test_timeout_and_ungrounded_excluded():
    t = Topic(id="kb", label="KB", buyer_need="n", positioning_point_ids=[], fit="strong")
    good = [Answer(probe_id=f"g{i}", text="Notion is recommended.", provenance="live_api", provider="gemini",
                   model="m", collected_at="2026-09-18T00:00:00", search_executed=True) for i in range(3)]
    timeout = Answer(probe_id="t", provenance="live_api", provider="gemini", status="timeout", error="25s timeout")
    ungrounded = Answer(probe_id="u", text="Notion", provenance="live_api", provider="gemini", search_executed=False)
    evs = [evaluation.evaluate(PROBE, a, PROFILE) for a in good + [timeout, ungrounded]]
    evs[:3] = [e.model_copy(update=dict(valid=True, mentioned=True, recommended=True, strength=2)) for e in evs[:3]]
    te = score_topic(t, "baseline", good + [timeout, ungrounded], evs)
    assert te.n == 3 and te.excluded == 2 and te.visibility_score == 100
    assert any("timeout" in r for r in te.excluded_reasons) and any("ungrounded" in r for r in te.excluded_reasons)


def test_invalid_quote_flagged():
    e = evaluation.evaluate(PROBE, synth("Notion works.", mentioned=True, recommended=True,
                                         evidence_quotes=["Notion is the best tool ever"]), PROFILE)
    assert not e.valid and e.strength is None and any("Invalid evidence quote" in w for w in e.warnings)


def test_competitor_must_appear_in_text():
    e = evaluation.evaluate(PROBE, synth("Use Confluence.", competitor_recommendations=["Asana"]), PROFILE)
    assert not e.valid


# A live search answer, shaped as the Responses API writes one: inline `([host](url))` citations and
# bare source-card lines whose titles name products the answer itself never recommends.
CITED = ("Asana is the pick for this. ([zapier.com](https://zapier.com/blog/asana?utm_source=openai))\n\n"
         "[Trello vs Asana: which is better](https://example.com/trello?utm_source=openai)\n"
         "Teams also like monday.com and Otter.ai, and Heights of focus.")


@pytest.mark.parametrize("name,kept", [
    ("Asana", True),         # named in the body
    ("Otter.ai", True),      # a product whose name is a domain, written as a name
    ("Trello", False),       # only in a source card's title
    ("zapier.com", False),   # a citation's host
    ("zapier", False),       # a domain stem
    ("Height", False),       # inside another word
    ("monday.com", False),   # lowercase host shape: dropped even in prose (see BARE_HOST)
])
def test_competitor_must_be_named_in_the_body_not_in_a_citation(name, kept):
    e = evaluation.evaluate(PROBE, synth(CITED, competitor_recommendations=[name]), PROFILE)
    assert e.valid   # the name is dropped; the answer's other labels still stand
    assert (name in e.competitor_recommendations) is kept
    assert kept or any("Citation-only" in w for w in e.warnings)


@pytest.mark.parametrize("labels", [dict(mentioned=True, evidence_quotes=[""]),
                                    dict(competitor_recommendations=[" "])])
def test_a_blank_string_is_not_evidence(labels):
    """`"" in text` is always true, so a blank quote or name would otherwise pass as verbatim."""
    assert not evaluation.evaluate(PROBE, synth("Notion works. Asana too.", **labels), PROFILE).valid


def test_brand_named_only_inside_a_citation_is_not_a_mention():
    text = "Use Confluence. ([Notion vs Confluence](https://example.com/x))"
    e = evaluation.evaluate(PROBE, synth(text, mentioned=True, evidence_quotes=["Notion vs Confluence"]),
                            PROFILE)
    assert not e.valid and any("only inside a citation" in w for w in e.warnings)


@pytest.mark.parametrize("text", ["Is Notion good for wikis?", "What does notion.so offer?", "Compare notion AI tools",
                                  "Which tool like Notion Calendar is best?"])
def test_brand_leaking_questions_rejected(text):
    p = Probe(id="kb-9", topic_id="kb", text=text, phase="baseline", purpose="t")
    topics = [Topic(id="kb", label="KB", buyer_need="n", positioning_point_ids=[], fit="strong")]
    assert any("leaks" in err for err in ana.validate_probes([p], topics, PROFILE))


def test_leaking_plan_stops_graph():
    prov = fixture.FixtureProvider("A")
    prov.data = json.loads(json.dumps(prov.data))
    prov.data["baseline_probes"][0]["text"] = "Is Notion a good knowledge base?"
    with pytest.raises(graph.ValidationError):
        graph.execute(graph.new_run(fixture.bundled_profile("A"), prov), prov)


def test_bundled_questions_are_neutral():
    prov = fixture.FixtureProvider("A")
    topics, probes = prov.plan(PROFILE)
    bank = [Probe(**p, parent_probe_ids=[]) for ps in prov.followup_bank().values() for p in ps]
    assert ana.validate_probes(probes, topics, PROFILE) == []
    assert all(not ana.brand_leaks(p.text, PROFILE) for p in bank)


def test_measured_prompt_carries_no_company_context():
    msgs = live.measured_prompt(Probe(id="a", topic_id="kb", text="Best wiki tools?", phase="baseline", purpose="p"))
    blob = json.dumps(msgs)
    assert "Best wiki tools?" in blob and not ana.brand_leaks(blob, PROFILE) and len(msgs) == 2


# --- export / import / persistence -------------------------------------------------
def test_export_import_roundtrip(runs, tmp_path, monkeypatch):
    import reports
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    r = runs["B"]
    back = from_json(to_json(r))
    assert back == r and back.baseline_hash == r.baseline_hash and back.schema_version == r.schema_version
    assert [a.provenance for a in back.answers] == [a.provenance for a in r.answers]
    assert [(t.n, t.recommendations) for t in back.topic_evaluations] == [(t.n, t.recommendations) for t in r.topic_evaluations]
    save_run(r)
    assert load_run(r.id) == r
    tampered = json.loads(to_json(r))
    tampered["probes"][0]["text"] = "changed"
    with pytest.raises(ValueError):
        from_json(json.dumps(tampered))


# --- arbitrary companies ------------------------------------------------------------
def test_arbitrary_company_never_gets_bundled_report():
    p = CompanyProfile(name="Acme Wiki", domain="acme.example", aliases=["Acme Wiki"],
                       positioning_points=[PositioningPoint(id="pp1", text="Team wikis")])
    with pytest.raises(fixture.ReplayUnavailable):
        fixture.FixtureProvider("A").plan(p)
    with pytest.raises(fixture.ReplayUnavailable):
        graph.execute(graph.new_run(p, fixture.FixtureProvider("A")), fixture.FixtureProvider("A"))


def test_renamed_or_structurally_edited_notion_rejected():
    renamed = PROFILE.model_copy(update={"name": "Acme"})
    edited = PROFILE.model_copy(deep=True)
    edited.positioning_points[0].text = "Something different"
    for p in (renamed, edited):
        with pytest.raises(fixture.ReplayUnavailable):
            fixture.FixtureProvider("B").check_profile(p)


# --- secrets -------------------------------------------------------------------------
def test_secrets_not_exported_or_committed(monkeypatch):
    secret = "sk-test-DO-NOT-LEAK-123"
    monkeypatch.setenv(live.KEY_ENV, secret)
    r = run_scenario("A")
    assert secret not in to_json(r) and secret not in to_markdown(r) and secret not in live.status()
    assert ".env" in (ROOT / ".gitignore").read_text().split()
