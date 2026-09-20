"""Positioning drift: intended vs claimed vs perceived. Deterministic — no model judgment here.

Three layers, kept separate on purpose:
  intended  — what the customer says they want to be known for (aspirational, never product fit)
  claimed   — what their own public copy actually states (evidence-backed)
  perceived — what AI associated with them in eligible named-probe answers

The zone is intended x perceived. The owner uses the claimed layer to say *whose* problem it is,
which is the whole point: a gap where the company never stated the claim is not an AI problem.
"""
from typing import Optional

from schemas import (Attribute, AttributeObservation, AttributeScore, DriftReport, QueryEvaluation,
                     Answer, Probe)
from scoring import eligible, rate

ECHO_THRESHOLD = 0.5   # share of eligible named answers that must echo an attribute to count as present
IMPOSED_MIN = 0.25     # an attribute you never claimed is worth flagging at a lower bar than one you want
CONTESTED_MIN = 0.25   # AI actively saying the opposite of an intended claim is a problem at the same low bar
CLAIM_THRESHOLD = 0.4  # share of known pages that must state it before absence is an authority problem
MIN_NAMED = 3          # below this, perception is not measurable and alignment is null

OWNER_TEXT = {
    "authority_gap": "You state this clearly and the models are not repeating it.",
    "messaging_gap": "AI does not say it because your own copy does not clearly say it either.",
    "contested_identity": "AI talks about this and says the opposite of what you claim.",
    "imposed_identity": "AI asserts this about you without you claiming it.",
    "none": "Intended positioning is reflected in AI answers.",
}


def claim_strength(a: Attribute) -> Optional[float]:
    return None if not a.claim_pages_total else round(a.claim_pages / a.claim_pages_total, 3)


def relevant(a: Attribute, mention_rate: Optional[float]) -> bool:
    """Intended attributes always appear. An attribute nobody claimed AND AI barely says is noise.

    Deliberately keyed on MENTIONS, not supportive echoes: an unclaimed attribute AI raises only to
    criticise ("expensive at scale") is the most reportable imposed identity there is, and keying
    this on the supportive rate would silently delete it from the report.
    """
    return a.intended or (mention_rate is not None and mention_rate >= IMPOSED_MIN)


def classify(a: Attribute, echo_rate: Optional[float], cs: Optional[float],
             negative_rate: Optional[float] = None) -> tuple[str, str]:
    """Zone x owner. Pure function of the three layers; deliberately has no access to an LLM.

    The model already judged each mention's polarity (agents/evaluation.py extract_attributes); this
    function consumes that judgment, it does not second-guess it.

    An intended attribute needs a majority SUPPORTIVE echo to count as landed - criticism is not an
    endorsement. One that AI raises mainly to contradict is `contested`, checked before the absence
    zones because "AI says the opposite" is a different problem from "AI never says it", and at the
    low CONTESTED_MIN bar for the same reason IMPOSED_MIN is low.
    """
    echoed = echo_rate is not None and echo_rate >= ECHO_THRESHOLD
    stated = cs is not None and cs >= CLAIM_THRESHOLD
    contested = negative_rate is not None and negative_rate >= CONTESTED_MIN
    if a.intended and echoed:
        return "landed", "none"
    if a.intended and contested:
        return "contested", "contested_identity"
    if a.intended and stated:
        return "lost_claim", "authority_gap"
    if a.intended:
        return "unstated_intent", "messaging_gap"
    return "imposed", "imposed_identity"


def named_eligibility(probes: list[Probe], answers: list[Answer],
                      evals: list[QueryEvaluation]) -> tuple[list[str], list[str], int]:
    """-> (kept probe ids, exclusion reasons, how many were asked).

    Exclusions must be reported, not just applied: a timeout removes an answer that would otherwise
    have counted against you, so a silent exclusion inflates alignment. Callers surface the counts.
    """
    named_ids = [p.id for p in probes if p.kind == "named"]
    ans = {a.probe_id: a for a in answers}
    ev = {e.probe_id: e for e in evals}
    kept, reasons = [], []
    for pid in named_ids:
        if pid not in ans or pid not in ev:
            reasons.append(f"{pid}: no answer collected")
            continue
        ok, why = eligible(ans[pid], ev[pid])
        kept.append(pid) if ok else reasons.append(f"{pid}: {why}")
    return kept, reasons, len(named_ids)


def score_attributes(attributes: list[Attribute], probes: list[Probe], answers: list[Answer],
                     evals: list[QueryEvaluation],
                     observations: dict[str, list[AttributeObservation]]) -> list[AttributeScore]:
    """observations: probe_id -> validated observations (quotes already checked verbatim upstream)."""
    kept, _, _ = named_eligibility(probes, answers, evals)
    n = len(kept)

    out = []
    for a in attributes:
        hits = [(pid, o) for pid in kept for o in observations.get(pid, []) if o.attribute_id == a.id]
        echoes = len({pid for pid, _ in hits})
        neg = len({pid for pid, o in hits if o.polarity == "negative"})
        # echo_rate drives `landed` and the alignment score, so it counts only supportive mentions.
        # extract_attributes keeps at most one observation per attribute per answer, so these are
        # disjoint counts of answers, not of sentences.
        mr = rate(echoes, n)
        nr = rate(neg, n)
        er = rate(echoes - neg, n)
        cs = claim_strength(a)
        if not relevant(a, mr):
            continue  # unclaimed and barely mentioned: not a finding, and never padding for the report
        zone, owner = classify(a, er, cs, nr)
        limits = []
        if zone == "contested":
            limits.append(f"AI raised this in {echoes} of {n} answers and was negative in {neg} of them; "
                          "the score counts only the supportive mentions.")
        if n < MIN_NAMED:
            limits.append(f"Only {n} eligible named-probe answer(s); perception is not measurable.")
        if a.intended and cs is None:
            limits.append("No page-level claim data: cannot separate an authority gap from a messaging gap.")
        out.append(AttributeScore(
            attribute_id=a.id, label=a.label, intended_weight=a.intended_weight, claim_strength=cs,
            n=n, echoes=echoes, echo_rate=er, negative_echoes=neg, mention_rate=mr,
            negative_rate=nr, zone=zone, owner=owner,
            quotes=[o.quote for _, o in hits][:3], probe_ids=sorted({pid for pid, _ in hits}),
            limitations=limits))
    return out


def alignment(scores: list[AttributeScore]) -> Optional[float]:
    """Weighted echo of INTENDED attributes only. Imposed attributes never flatter this number."""
    rows = [s for s in scores if s.intended_weight and s.echo_rate is not None]
    total = sum(s.intended_weight for s in rows)
    if not rows or total == 0:
        return None
    return round(100 * sum(s.intended_weight * s.echo_rate for s in rows) / total, 1)


def build_report(scores: list[AttributeScore], provenance: str, n_blind: int,
                 visibility: Optional[float], asked: int = 0,
                 excluded_reasons: Optional[list[str]] = None) -> DriftReport:
    n = scores[0].n if scores else 0
    reasons = list(excluded_reasons or [])
    asked = asked or n
    by = lambda z: [s.label for s in scores if s.zone == z]
    limits = []
    if reasons:
        # first, because it changes how every number below should be read
        limits.append(f"{len(reasons)} of {asked} named answers were excluded, so alignment rests on "
                      f"{n}. Excluded answers cannot count against the brand, which biases the score "
                      f"upward: {'; '.join(reasons)}")
    limits += ["Small sample: alignment rests on a handful of named-probe answers.",
               "An echo is an association in the answer text, not proof of why the model said it."]
    if provenance == "synthetic":
        limits.append("Simulated: attribute observations come from authored fixtures, not a measured chatbot.")
    if n < MIN_NAMED:
        limits.append(f"Only {n} eligible named answer(s) (minimum {MIN_NAMED}); alignment withheld.")
    return DriftReport(
        provenance=provenance, n_named=n, n_blind=n_blind, named_asked=asked,
        excluded_named=len(reasons), excluded_reasons=reasons,
        alignment=alignment(scores) if n >= MIN_NAMED else None,
        visibility=visibility, scores=scores, limitations=limits,
        landed=by("landed"), lost_claims=by("lost_claim"), contested=by("contested"),
        imposed=by("imposed"), unstated_intent=by("unstated_intent"))
