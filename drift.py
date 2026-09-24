"""Drift: intended vs claimed vs perceived. Deterministic — no model judgment here.

Three layers, kept separate on purpose:
  intended  — what the customer says they want to be known for (aspirational, never product fit)
  claimed   — what their own public copy actually states (evidence-backed)
  perceived — what AI associated with them in eligible named-probe answers

The zone is intended x perceived, or claimed x perceived when nothing is weighted (the claim lens). The owner uses the claimed layer to say *whose* problem it is,
which is the whole point: a gap where the company never stated the claim is not an AI problem.
"""
from typing import Optional

from labels import probe_name
from schemas import (Attribute, AttributeObservation, AttributeScore, DriftReport, QueryEvaluation,
                     Answer, Probe)
from scoring import eligible, rate

ECHO_THRESHOLD = 0.5   # share of eligible named answers that must echo an attribute to count as present
IMPOSED_MIN = 0.25     # an attribute you never claimed is worth flagging at a lower bar than one you want
CONTESTED_MIN = 0.25   # AI actively saying the opposite of an intended claim is a problem at the same low bar
CLAIM_THRESHOLD = 0.4  # share of known pages that must state it before absence is an authority problem
MIN_NAMED = 3          # below this, perception is not measurable and alignment is null

# The zones that are somebody's problem. `landed` is working and `unprioritised` is the company's
# own claim being repeated back — neither belongs under a heading that calls it a gap. Mirrored by
# GAP_ZONES in web/src/api.ts.
GAP_ZONES = ("contested", "lost_claim", "unstated_intent", "imposed")

OWNER_TEXT = {
    "authority_gap": "You state this clearly and the models are not repeating it.",
    "messaging_gap": "AI does not say it because your own copy does not clearly say it either.",
    "contested_identity": "AI talks about this and says the opposite of what you claim.",
    "imposed_identity": "AI asserts this about you without you claiming it.",
    "unprioritised_claim": "You say this on your own site and AI repeats it, but you did not mark it "
                           "as something you want to be known for.",
    "none": "Intended positioning is reflected in AI answers.",
}


def claim_strength(a: Attribute) -> Optional[float]:
    return None if not a.claim_pages_total else round(a.claim_pages / a.claim_pages_total, 3)


def is_claimed(a: Attribute) -> bool:
    cs = claim_strength(a)
    return bool(a.claim_evidence_ids) or (cs is not None and cs > 0)


def relevant(a: Attribute, mention_rate: Optional[float], claim_lens: bool = False) -> bool:
    """Intended attributes always appear. An attribute nobody claimed AND AI barely says is noise.

    With no intent at all (the claim lens) every claim is the reference instead, so every claim
    appears: a claim AI never repeats is the lost-claim finding, not noise.

    Deliberately keyed on MENTIONS, not supportive echoes: an unclaimed attribute AI raises only to
    criticise ("expensive at scale") is the most reportable imposed identity there is, and keying
    this on the supportive rate would silently delete it from the report.
    """
    return (a.intended or (claim_lens and is_claimed(a))
            or (mention_rate is not None and mention_rate >= IMPOSED_MIN))


def classify(a: Attribute, echo_rate: Optional[float], cs: Optional[float],
             negative_rate: Optional[float] = None, claim_lens: bool = False) -> tuple[str, str]:
    """Zone x owner. Pure function of the three layers; deliberately has no access to an LLM.

    The model already judged each mention's polarity (agents/evaluation.py extract_attributes); this
    function consumes that judgment, it does not second-guess it.

    An intended attribute needs a majority of its answers to endorse it before it counts as landed:
    `echo_rate` counts only positive observations. A neutral mention ("Notion is sometimes used for
    project tracking") is not the model being convinced of anything, so it does not count as the
    positioning having landed; neither does criticism. One that AI raises mainly to contradict is
    `contested`, checked before the absence zones because "AI says the opposite" is a different
    problem from "AI never says it", and at the low CONTESTED_MIN bar for the same reason
    IMPOSED_MIN is low.

    `claim_lens` is the reading when nothing in the run is weighted: the company's own claims stand
    in for intent, so a claim AI does not endorse is a lost claim — an authority gap when the site
    states it clearly, a messaging gap when it barely does — and nothing reads "unprioritised",
    which only means something relative to weights. Intent is never derived from the copy, so
    `unstated_intent` (you want it, your site never says it) exists only once weights are set.
    """
    echoed = echo_rate is not None and echo_rate >= ECHO_THRESHOLD
    stated = cs is not None and cs >= CLAIM_THRESHOLD
    contested = negative_rate is not None and negative_rate >= CONTESTED_MIN
    claimed = bool(a.claim_evidence_ids) or (cs is not None and cs > 0)
    target = claimed if claim_lens else a.intended
    if target and echoed:
        return "landed", "none"
    # Contradiction of anything the company states on its own site, weighted or not: "AI says the
    # opposite of what you claim" is literally true of an unweighted claim too, and it outranks
    # being unweighted, so this is tested before `unprioritised` below.
    if (a.intended or claimed) and contested:
        return "contested", "contested_identity"
    if target and stated:
        return "lost_claim", "authority_gap"
    if target:
        return ("lost_claim" if claim_lens else "unstated_intent"), "messaging_gap"
    # Claimed but not weighted while other claims are (the claim lens never gets here). This never
    # arose in the fixtures — every unintended fixture attribute has claim_pages=0. `imposed` means AI asserts something the company never claimed
    # ANYWHERE, so a claim their own site makes with a validated quote behind it can never be
    # imposed, whatever the echo rate: keying this on the echo too would leave the ordinary
    # [IMPOSED_MIN, ECHO_THRESHOLD) band reading "AI asserts this about you without you claiming it"
    # beside that row's own "50% of pages (3 of 6)".
    if claimed:
        return "unprioritised", "unprioritised_claim"
    return "imposed", "imposed_identity"


def named_eligibility(probes: list[Probe], answers: list[Answer],
                      evals: list[QueryEvaluation]) -> tuple[list[str], list[str], int]:
    """-> (kept probe ids, exclusion reasons, how many were asked).

    Exclusions must be reported, not just applied: a timeout removes an answer that would otherwise
    have counted against you, so a silent exclusion inflates alignment. Callers surface the counts.
    """
    # Baseline only. The adaptive comparison question is a named probe too, but it is chosen from
    # results the baseline produced, so counting it here would let the follow-up round move the
    # score it was selected by. It is reported as exploratory evidence instead.
    named = [p for p in probes if p.kind == "named" and p.phase == "baseline"]
    ans = {a.probe_id: a for a in answers}
    ev = {e.probe_id: e for e in evals}
    kept, reasons = [], []
    for p in named:  # reasons are read by a human, so they name the question, not its id
        if p.id not in ans or p.id not in ev:
            reasons.append(f"{probe_name(p)}: no answer collected")
            continue
        ok, why = eligible(ans[p.id], ev[p.id])
        kept.append(p.id) if ok else reasons.append(f"{probe_name(p)}: {why}")
    return kept, reasons, len(named)


def score_attributes(attributes: list[Attribute], probes: list[Probe], answers: list[Answer],
                     evals: list[QueryEvaluation],
                     observations: dict[str, list[AttributeObservation]]) -> list[AttributeScore]:
    """observations: probe_id -> validated observations (quotes already checked verbatim upstream)."""
    kept, _, _ = named_eligibility(probes, answers, evals)
    n = len(kept)
    claim_lens = not any(a.intended for a in attributes)

    out = []
    for a in attributes:
        hits = [(pid, o) for pid in kept for o in observations.get(pid, []) if o.attribute_id == a.id]
        echoes = len({pid for pid, _ in hits})
        neg = len({pid for pid, o in hits if o.polarity == "negative"})
        pos = len({pid for pid, o in hits if o.polarity == "positive"})
        # echo_rate drives `landed` and the alignment score. It counts only positive observations:
        # a neutral mention is not conviction, and criticism is the opposite of it. mention_rate keeps
        # the full count so a reader can see the volume, and negative_rate the criticism inside it.
        # extract_attributes keeps at most one observation per attribute per answer, so these are
        # disjoint counts of answers, not of sentences.
        mr = rate(echoes, n)
        nr = rate(neg, n)
        er = rate(pos, n)
        cs = claim_strength(a)
        if not relevant(a, mr, claim_lens):
            continue  # unclaimed and barely mentioned: not a finding, and never padding for the report
        zone, owner = classify(a, er, cs, nr, claim_lens)
        limits = []
        if a.discovered:
            limits.append("Discovered from the answers: neither you nor your site supplied this. A model "
                          f"proposed it after reading all {n} answers together; it is kept because "
                          f"{echoes} of them say it in words quoted verbatim.")
        if zone == "contested":
            limits.append(f"AI raised this in {echoes} of {n} answers and was negative in {neg} of them; "
                          "the score counts only the answers that endorsed it.")
        if zone in ("lost_claim", "unstated_intent") and mr is not None and mr >= ECHO_THRESHOLD:
            limits.append(f"AI mentions this in {echoes} of {n} answers but does not endorse it: "
                          f"only {pos} endorsed it.")
        if n < MIN_NAMED:
            limits.append(f"Only {n} eligible brand-question answer(s); perception is not measurable.")
        if a.intended and cs is None:
            limits.append("No page-level claim data: cannot separate an authority gap from a messaging gap.")
        na = {}
        if er is None:
            na["echo_rate"] = "No eligible brand-question answer, so there is nothing AI could have repeated."
        if cs is None:
            na["claim_strength"] = ("Found in the answers, not on the site: no page was checked for it."
                                    if a.discovered else "No pages were fetched for this claim.")
        out.append(AttributeScore(
            attribute_id=a.id, label=a.label, discovered=a.discovered,
            intended_weight=a.intended_weight, claim_strength=cs,
            claim_pages=a.claim_pages, claim_pages_total=a.claim_pages_total,
            n=n, echoes=echoes, echo_rate=er, negative_echoes=neg, mention_rate=mr,
            negative_rate=nr, zone=zone, owner=owner,
            quotes=[o.quote for _, o in hits][:3], probe_ids=sorted({pid for pid, _ in hits}),
            limitations=limits, na_reasons=na))
    return out


def alignment(scores: list[AttributeScore]) -> Optional[float]:
    """Weighted echo of INTENDED attributes only. Imposed attributes never flatter this number."""
    rows = [s for s in scores if s.intended_weight and s.echo_rate is not None]
    total = sum(s.intended_weight for s in rows)
    if not rows or total == 0:
        return None
    return round(100 * sum(s.intended_weight * s.echo_rate for s in rows) / total, 1)


def claim_echo(attributes: list[Attribute], kept: list[str],
               observations: dict[str, list[AttributeObservation]]) -> tuple[Optional[float], Optional[str]]:
    """-> (score, why it is null). The headline that needs no human input: of what the site claims,
    weighted by prominence (pages stating it), how much AI repeats supportively.

    Positive observations only, the same rule as `echo_rate`: a neutral mention is not conviction.
    Taken over every claim, not only the rows the report shows, so hiding a quiet unweighted claim
    from the drift map can never flatter this number. Discovered attributes are not claims.
    """
    n = len(kept)
    if n < MIN_NAMED:
        return None, f"Only {n} eligible brand answer(s) (minimum {MIN_NAMED}), so AI's view is not measurable."
    rows = [(a.claim_pages, sum(any(o.attribute_id == a.id and o.polarity == "positive"
                                    for o in observations.get(pid, [])) for pid in kept))
            for a in attributes if not a.discovered and a.claim_pages > 0]
    total = sum(pages for pages, _ in rows)
    if not total:
        return None, "No claim was found stated on any fetched page, so there is nothing to echo."
    return round(100 * sum(pages * pos / n for pages, pos in rows) / total, 1), None


def build_report(scores: list[AttributeScore], provenance: str, n_blind: int,
                 visibility: Optional[float], asked: int = 0,
                 excluded_reasons: Optional[list[str]] = None,
                 echo: tuple[Optional[float], Optional[str]] = (None, "Not computed for this report."),
                 lens: str = "intent") -> DriftReport:
    n = scores[0].n if scores else 0
    reasons = list(excluded_reasons or [])
    asked = asked or n
    by = lambda z: [s.label for s in scores if s.zone == z]
    limits = []
    if reasons:
        # first, because it changes how every number below should be read
        limits.append(f"{len(reasons)} of {asked} brand answers were excluded, so alignment rests on "
                      f"{n}. Excluded answers cannot count against the brand, which biases the score "
                      f"upward: {'; '.join(reasons)}")
    limits += ["Small sample: alignment rests on a handful of brand-question answers.",
               "An echo is an association in the answer text, not proof of why the model said it."]
    if provenance == "synthetic":
        limits.append("Simulated: attribute observations come from authored fixtures, not a measured chatbot.")
    if n < MIN_NAMED:
        limits.append(f"Only {n} eligible brand answer(s) (minimum {MIN_NAMED}); alignment withheld.")
    na = {}
    if lens == "claim":
        # Every n/a says why. This one is a choice, not a failure: intent is the customer's input.
        align = None
        na["alignment"] = ("No claim is weighted as intended, so there is no intended positioning to "
                           "align against. Claim echo is the headline; setting intent weights on the "
                           "finished run adds alignment by re-scoring its saved answers.")
    else:
        align = alignment(scores) if n >= MIN_NAMED else None
        if align is None:
            na["alignment"] = (f"Only {n} eligible brand answer(s) (minimum {MIN_NAMED}), so alignment "
                               "is withheld." if n < MIN_NAMED else
                               "No weighted claim has a measurable echo rate.")
    if echo[0] is None:
        na["claim_echo"] = echo[1] or "Not computed."
    if visibility is None:
        na["visibility"] = "No unbranded question produced an eligible answer, so visibility is not measured."
    return DriftReport(
        provenance=provenance, n_named=n, n_blind=n_blind, named_asked=asked,
        excluded_named=len(reasons), excluded_reasons=reasons, lens=lens,
        claim_echo=echo[0], alignment=align,
        visibility=visibility, scores=scores, limitations=limits, na_reasons=na,
        landed=by("landed"), lost_claims=by("lost_claim"), contested=by("contested"),
        imposed=by("imposed"), unstated_intent=by("unstated_intent"),
        unprioritised=by("unprioritised"))
