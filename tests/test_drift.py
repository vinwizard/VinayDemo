"""Offline acceptance checks for the drift layer."""
import pytest

import drift
from agents import ana, evaluation
from schemas import (Answer, Attribute, AttributeObservation, AttributeScore,
                     Probe, QueryEvaluation)

mk = lambda **k: Attribute(id=k.pop("id", "x"), label=k.pop("label", "X"), **k)
INTENDED_STATED = dict(intended_weight=1.0, claim_evidence_ids=["e"], claim_pages=6, claim_pages_total=8)


# --- zone x owner truth table -------------------------------------------------
CLAIMED = dict(claim_evidence_ids=["pg1", "pg3", "pg5"], claim_quotes=["set up in minutes"], claim_pages=3,
               claim_pages_total=6)    # the company states it but never weighted it: every onboarded claim at first


@pytest.mark.parametrize("attrs,echo,negative,expected", [
    (INTENDED_STATED, 0.8, 0.0, ("landed", "none")),
    (INTENDED_STATED, 0.1, 0.0, ("lost_claim", "authority_gap")),
    (dict(intended_weight=1.0, claim_pages=0, claim_pages_total=8), 0.0, 0.0, ("unstated_intent", "messaging_gap")),
    (dict(claim_pages=0, claim_pages_total=8), 0.9, 0.0, ("imposed", "imposed_identity")),
    # absence is only an authority gap if they actually said it: barely stated is their own problem
    (dict(INTENDED_STATED, claim_pages=1), 0.0, 0.0, ("unstated_intent", "messaging_gap")),
    # criticism is not an endorsement: 4 criticisms + 1 nod used to read as "landed, no problem"
    (INTENDED_STATED, 0.125, 0.5, ("contested", "contested_identity")),
    (INTENDED_STATED, 0.625, 0.0, ("landed", "none")),        # same mention volume, no criticism
    (INTENDED_STATED, 0.75, 0.25, ("landed", "none")),        # majority supportive despite some criticism
    (dict(claim_pages=0, claim_pages_total=8), 0.0, 0.375, ("imposed", "imposed_identity")),  # purely negative
    # their own claim repeated back is unprioritised, never imposed beside their validated quote,
    # also in the band mentioned too little to count as echoed (2 of 7)
    (CLAIMED, 0.75, 0.0, ("unprioritised", "unprioritised_claim")),
    (CLAIMED, 2 / 7, 0.0, ("unprioritised", "unprioritised_claim")),
    (CLAIMED, 0.0, 4 / 7, ("contested", "contested_identity")),   # AI contradicts it: contested, even unweighted
    (dict(claim_pages=0, claim_pages_total=6), 0.0, 4 / 7, ("imposed", "imposed_identity")),
])
def test_zone_truth_table(attrs, echo, negative, expected):
    a = mk(**attrs)
    assert drift.classify(a, echo, drift.claim_strength(a), negative) == expected


def test_only_somebodys_problem_is_filed_under_gaps():
    """Both report surfaces read GAP_ZONES, so neither can start calling the company's own repeated
    claim somebody's problem, or hide a contradicted one from the gap cards."""
    a = mk(**CLAIMED)
    assert a.claimed and not a.intended
    assert "unprioritised" not in drift.GAP_ZONES and "landed" not in drift.GAP_ZONES
    assert "contested" in drift.GAP_ZONES


def test_a_claim_stated_only_in_a_private_document_is_a_messaging_gap():
    """AI cannot read an uploaded document, so not repeating what only it says is not AI failing to
    listen: stated on every source, it is still the company not having said it in public."""
    a = mk(private_only=True, **INTENDED_STATED)
    assert drift.classify(a, 0.1, drift.claim_strength(a)) == ("unstated_intent", "messaging_gap")
    assert drift.classify(a, 0.1, drift.claim_strength(a), claim_lens=True) == ("lost_claim", "messaging_gap")


def test_unclaimed_and_unechoed_attribute_is_not_reported():
    """Without the relevance floor every unclaimed attribute would show as 'imposed' at 0%. Relevance
    is keyed on mentions, not supportive echoes, or 'expensive at scale' disappears."""
    assert not drift.relevant(mk(claim_pages=0, claim_pages_total=8), 0.0)
    assert drift.relevant(mk(claim_pages=0, claim_pages_total=8), 0.9)
    assert drift.relevant(mk(claim_pages=0, claim_pages_total=8), 0.375)   # 3 of 8, all negative
    assert drift.relevant(mk(**INTENDED_STATED), 0.0)  # intended always shows
    assert drift.IMPOSED_MIN <= 2 / 7 < drift.ECHO_THRESHOLD and drift.relevant(mk(**CLAIMED), 2 / 7)


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


LINKED = "Notion integrates with [GitHub](https://github.com) and Slack."


@pytest.mark.parametrize("text,quote,kept,warning", [
    (None, "Notion is a NOTES APP", False, "not verbatim"),           # dropped, not repaired
    (None, "Notion is a notes app", True, None),
    ("Notion is a notes app. ([Notion is the best AI workspace](https://example.com/x))",
     "Notion is the best AI workspace", False, "from a citation"),
    (f"{LINKED} ([x.com](https://x.com))", LINKED, True, None),        # a quote spanning a prose link
])
def test_a_quote_is_kept_only_when_verbatim_in_the_answer_prose(text, quote, kept, warning):
    a = answer_with([{"attribute_id": "nt", "quote": quote}], *([text] if text else []))
    obs, warns = evaluation.extract_attributes(a, [mk(id="nt", label="Note-taking app")])
    assert [o.quote for o in obs] == ([quote] if kept else [])
    assert any(warning in w for w in warns) if warning else not warns


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


# --- negative polarity reaches the score (Option C: contested zone) -----------
def five_named(text):
    """Five baseline brand questions, each answered with `text` and judged a valid mention."""
    probes = [Probe(id=f"np-{i}", topic_id="perception", text="What is Notion?", kind="named",
                    phase="baseline", purpose="p") for i in range(1, 6)]
    answers = [Answer(probe_id=p.id, text=text, provenance="synthetic", status="ok") for p in probes]
    evals = [QueryEvaluation(probe_id=p.id, valid=True, mentioned=True, strength=1, explanation="e")
             for p in probes]
    return probes, answers, evals


def test_negative_mentions_are_subtracted_from_the_supportive_echo():
    """End to end through score_attributes: 4 of 5 answers raise it, 3 of those to criticise it."""
    a = mk(**INTENDED_STATED)
    probes, answers, evals = five_named("Notion is an AI-native workspace.")
    obs = {f"np-{i}": [AttributeObservation(attribute_id="x", quote="AI-native workspace",
                                            polarity="negative" if i <= 3 else "positive")]
           for i in range(1, 5)}
    s = drift.score_attributes([a], probes, answers, evals, obs)[0]
    assert s.mention_rate == 0.8 and s.negative_echoes == 3
    assert s.echo_rate < s.mention_rate  # the three criticisms must not read as endorsement
    assert s.echo_rate == 0.2 and s.zone == "contested"


def test_neutral_mentions_do_not_land_an_intended_attribute():
    """Five of five answers mention it neutrally, none endorse it: a mention is not conviction."""
    a = mk(**INTENDED_STATED)
    probes, answers, evals = five_named("Notion is sometimes used as an AI-native workspace.")
    obs = {p.id: [AttributeObservation(attribute_id="x", quote="AI-native workspace", polarity="neutral")]
           for p in probes}
    s = drift.score_attributes([a], probes, answers, evals, obs)[0]
    assert s.mention_rate == 1.0 and s.negative_echoes == 0
    assert s.echo_rate == 0.0 and s.zone != "landed"
    assert drift.alignment([s]) == 0.0


def test_neutral_heavy_row_says_ai_mentions_but_does_not_endorse():
    """A lost claim AI mentions in every answer must not read as 'the models are not repeating it'."""
    probes, answers, evals = five_named("Notion is sometimes used as an AI-native workspace.")
    obs = {p.id: [AttributeObservation(attribute_id="x", quote="AI-native workspace",
                                       polarity="positive" if p.id == "np-1" else "neutral")]
           for p in probes}
    neutral, absent = drift.score_attributes(
        [mk(**INTENDED_STATED), mk(id="y", label="Y", **INTENDED_STATED)], probes, answers, evals, obs)
    assert neutral.zone == absent.zone == "lost_claim"
    assert any("mentions this in 5 of 5 answers but does not endorse it" in l for l in neutral.limitations)
    assert not any("does not endorse" in l for l in absent.limitations)
