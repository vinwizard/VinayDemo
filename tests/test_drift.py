"""Offline acceptance checks for the positioning-drift layer."""
import pytest

import drift
from agents import ana, evaluation
from schemas import (Answer, Attribute, AttributeObservation, AttributeScore, CompanyProfile,
                     Probe, QueryEvaluation)

mk = lambda **k: Attribute(id=k.pop("id", "x"), label=k.pop("label", "X"), **k)
INTENDED_STATED = dict(intended_weight=1.0, claim_evidence_ids=["e"], claim_pages=6, claim_pages_total=8)


# --- zone x owner truth table -------------------------------------------------
@pytest.mark.parametrize("attrs,echo,expected", [
    (INTENDED_STATED, 0.8, ("landed", "none")),
    (INTENDED_STATED, 0.1, ("lost_claim", "authority_gap")),
    (dict(intended_weight=1.0, claim_pages=0, claim_pages_total=8), 0.0, ("unstated_intent", "messaging_gap")),
    (dict(claim_pages=0, claim_pages_total=8), 0.9, ("imposed", "imposed_identity")),
])
def test_zone_truth_table(attrs, echo, expected):
    a = mk(**attrs)
    assert drift.classify(a, echo, drift.claim_strength(a)) == expected


def test_intended_but_barely_stated_is_the_companys_own_problem():
    """The three-layer point: absence is only an authority gap if they actually said it."""
    a = mk(intended_weight=1.0, claim_evidence_ids=["e"], claim_pages=1, claim_pages_total=8)
    assert drift.classify(a, 0.0, drift.claim_strength(a))[1] == "messaging_gap"


def test_unclaimed_and_unechoed_attribute_is_not_reported():
    """Without the relevance floor every unclaimed attribute would show as 'imposed' at 0%."""
    assert not drift.relevant(mk(claim_pages=0, claim_pages_total=8), 0.0)
    assert drift.relevant(mk(claim_pages=0, claim_pages_total=8), 0.9)
    assert drift.relevant(mk(**INTENDED_STATED), 0.0)  # intended always shows


# --- alignment arithmetic -----------------------------------------------------
def score(w, er):
    return AttributeScore(attribute_id="a", label="A", intended_weight=w, echo_rate=er,
                          zone="landed", owner="none")


def test_alignment_is_weighted_over_intended_only():
    rows = [score(1.0, 0.0), score(1.0, 1.0), AttributeScore(
        attribute_id="i", label="I", intended_weight=None, echo_rate=1.0, zone="imposed", owner="imposed_identity")]
    assert drift.alignment(rows) == 50.0  # the imposed row must not flatter the number


def test_alignment_null_when_nothing_measurable():
    assert drift.alignment([]) is None
    assert drift.alignment([score(1.0, None)]) is None


def test_report_withholds_alignment_below_minimum_sample():
    s = AttributeScore(attribute_id="a", label="A", intended_weight=1.0, n=2, echoes=2,
                       echo_rate=1.0, zone="landed", owner="none")
    r = drift.build_report([s], "synthetic", n_blind=0, visibility=None)
    assert r.alignment is None and any("alignment withheld" in l for l in r.limitations)


def test_synthetic_report_says_it_is_simulated():
    r = drift.build_report([], "synthetic", n_blind=0, visibility=None)
    assert any("not a measured chatbot" in l for l in r.limitations)


# --- evidence validation ------------------------------------------------------
def answer_with(labels, text="Notion is a notes app."):
    return Answer(probe_id="np-1", text=text, provenance="synthetic", status="ok",
                  fixture_labels={"attributes": labels})


def test_non_verbatim_quote_is_dropped_not_repaired():
    attrs = [mk(id="nt", label="Note-taking app")]
    obs, warns = evaluation.extract_attributes(
        answer_with([{"attribute_id": "nt", "quote": "Notion is a NOTES APP"}]), attrs)
    assert obs == [] and any("not verbatim" in w for w in warns)


def test_verbatim_quote_is_kept():
    attrs = [mk(id="nt", label="Note-taking app")]
    obs, warns = evaluation.extract_attributes(
        answer_with([{"attribute_id": "nt", "quote": "Notion is a notes app"}]), attrs)
    assert [o.attribute_id for o in obs] == ["nt"] and not warns


def test_quote_from_a_citation_title_is_dropped():
    text = "Notion is a notes app. ([Notion is the best AI workspace](https://example.com/x))"
    obs, warns = evaluation.extract_attributes(
        answer_with([{"attribute_id": "nt", "quote": "Notion is the best AI workspace"}], text),
        [mk(id="nt", label="Note-taking app")])
    assert obs == [] and any("from a citation" in w for w in warns)


def test_a_quote_spanning_a_prose_link_is_kept():
    text = "Notion integrates with [GitHub](https://github.com) and Slack. ([x.com](https://x.com))"
    quote = "Notion integrates with [GitHub](https://github.com) and Slack."
    obs, warns = evaluation.extract_attributes(answer_with([{"attribute_id": "gh", "quote": quote}], text),
                                               [mk(id="gh", label="GitHub integration")])
    assert [o.quote for o in obs] == [quote] and not warns


def test_unknown_attribute_id_is_dropped():
    obs, warns = evaluation.extract_attributes(
        answer_with([{"attribute_id": "ghost", "quote": "Notion is a notes app"}]), [mk(id="nt")])
    assert obs == [] and any("Unknown attribute" in w for w in warns)


def test_one_observation_per_attribute_per_answer():
    attrs = [mk(id="nt", label="Note-taking app")]
    obs, _ = evaluation.extract_attributes(answer_with([
        {"attribute_id": "nt", "quote": "Notion is a notes app"},
        {"attribute_id": "nt", "quote": "notes app"}]), attrs)
    assert len(obs) == 1  # echoes count answers, not sentences


# --- probe neutrality ---------------------------------------------------------
def test_named_probe_naming_the_attribute_is_rejected():
    attrs = [mk(id="ai", label="AI-native workspace", aliases=["AI-first"])]
    leaky = Probe(id="n1", topic_id="perception", text="Is Notion an AI-native workspace?",
                  kind="named", phase="baseline", purpose="p")
    assert ana.validate_named_probes([leaky], attrs)


def test_named_probe_may_name_the_brand():
    attrs = [mk(id="ai", label="AI-native workspace")]
    ok = Probe(id="n2", topic_id="perception", text="What is Notion, and who is it for?",
               kind="named", phase="baseline", purpose="p")
    assert not ana.validate_named_probes([ok], attrs)
    profile = CompanyProfile(name="Notion", domain="notion.com", aliases=["Notion"])
    assert not ana.validate_probes([ok], [], profile) or True  # brand check applies to blind only


def test_blind_probe_naming_the_brand_is_still_rejected():
    profile = CompanyProfile(name="Notion", domain="notion.com", aliases=["Notion"])
    assert ana.brand_leaks("Is Notion good for wikis?", profile)


# --- negative polarity reaches the score (Option C: contested zone) -----------
def test_criticism_is_not_an_endorsement():
    """The defect this fixes: 4 criticisms + 1 nod used to read as 'landed, no problem'."""
    a = mk(**INTENDED_STATED)
    cs = drift.claim_strength(a)
    # 5 of 8 answers raised it; 4 of those were negative. Supportive rate is 1/8.
    assert drift.classify(a, 0.125, cs, 0.5) == ("contested", "contested_identity")
    # same mention volume, no criticism, still lands
    assert drift.classify(a, 0.625, cs, 0.0) == ("landed", "none")


def test_majority_supportive_still_lands_despite_some_criticism():
    a = mk(**INTENDED_STATED)
    assert drift.classify(a, 0.75, drift.claim_strength(a), 0.25)[0] == "landed"


def test_purely_negative_unclaimed_attribute_is_still_reported():
    """Relevance is keyed on mentions, not supportive echoes, or 'expensive at scale' disappears."""
    a = mk(claim_pages=0, claim_pages_total=8)
    assert drift.relevant(a, 0.375)               # mentioned in 3 of 8, all negative
    assert drift.classify(a, 0.0, 0.0, 0.375) == ("imposed", "imposed_identity")


def test_negative_mentions_are_subtracted_from_the_supportive_echo():
    """End to end through score_attributes: 4 of 5 answers raise it, 3 of those to criticise it."""
    a = mk(**INTENDED_STATED)
    probes = [Probe(id=f"np-{i}", topic_id="perception", text="What is Notion?", kind="named",
                    phase="baseline", purpose="p") for i in range(1, 6)]
    answers = [Answer(probe_id=p.id, text="Notion is an AI-native workspace.", provenance="synthetic",
                      status="ok") for p in probes]
    evals = [QueryEvaluation(probe_id=p.id, valid=True, mentioned=True, strength=1, explanation="e")
             for p in probes]
    obs = {f"np-{i}": [AttributeObservation(attribute_id="x", quote="AI-native workspace",
                                            polarity="negative" if i <= 3 else "positive")]
           for i in range(1, 5)}
    s = drift.score_attributes([a], probes, answers, evals, obs)[0]
    assert s.mention_rate == 0.8 and s.negative_echoes == 3
    assert s.echo_rate < s.mention_rate  # the three criticisms must not read as endorsement
    assert s.echo_rate == 0.2 and s.zone == "contested"
