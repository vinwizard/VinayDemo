"""Agent 3 — Evaluation and gap analysis.

Replay: authored fixture labels propose the judgment; deterministic code validates every
quote, mention, competitor and citation against the raw answer and computes all numbers.
Live: agents/evaluator_model.py proposes the labels, and they are validated here identically.
"""
import re

from agents.ana import brand_leaks
from labels import probe_names, with_ids
from schemas import (Answer, Attribute, AttributeObservation, CompanyProfile, GapFinding, Probe,
                     QueryEvaluation, Topic, TopicEvaluation)
from scoring import PRIORITY_LABEL, domain_matches, mentions_alias

INSIGHTS = "https://www.tryprofound.com/features/answer-engine-insights"
AGENTS = "https://www.tryprofound.com/features/agents"
TEMPLATES = "https://www.tryprofound.com/agent-templates"

# Reviewed configuration table (agents.md section 4). Explanation of possible fit, not an API call.
CAPABILITIES = {
    "absent_vs_competitors": ("Answer Engine Insights / competitive benchmarking", INSIGHTS,
                              "Track a wider fixed prompt set over time to assess whether the gap persists."),
    "competitor_citations": ("Citation analysis / competitive research", INSIGHTS,
                             "Inspect frequently cited sources and identify coverage the customer lacks."),
    "content": ("Content briefs, FAQ generation and content optimization Agents", AGENTS,
                "Review owned pages and propose an evidence-backed brief for the uncovered questions."),
    "factcheck": ("FactCheck and associated correction workflows", TEMPLATES,
                  "Compare the claim with current authoritative facts and investigate cited sources."),
    "poor_match": ("Sentiment/theme analysis plus topic research", INSIGHTS,
                   "Examine how the brand is described and whether product-fit evidence is clear."),
}

# Every `[title](url)` — the `([host](url))` inline citations and the bare source-card lines a
# search answer is full of — and every naked URL. What is left is what the model actually said.
CITATION = re.compile(r"\(?\[[^\]]*\]\([^)\s]*\)\)?|https?://\S+")


def answer_body(text: str) -> str:
    """The answer minus its citation markup. A name that exists only in a citation is a source the
    model read, not something it said, so body checks run on this and never on the raw text."""
    return CITATION.sub(" ", text)


def named_in(name: str, body: str) -> bool:
    """Word-bounded and case-sensitive, and never as a domain stem: "zapier" inside "zapier.com"
    and "Height" inside "Heights" are not a product being named."""
    return bool(re.search(rf"(?<![\w.]){re.escape(name)}(?!\w|\.\w)", body))


def evaluate(probe: Probe, answer: Answer, profile: CompanyProfile) -> QueryEvaluation:
    fail = lambda why, warn: QueryEvaluation(probe_id=probe.id, valid=False, explanation=why, warnings=[warn])
    if answer.status != "ok":
        return fail(f"Collection failed ({answer.status}); excluded from scores.", answer.error or answer.status)
    if answer.provenance == "web_research_snapshot":
        return fail("Search snapshot, not a chatbot answer; never scored as visibility.", "search snapshot")
    if answer.provenance == "live_api" and not answer.search_executed:
        return fail("Answer was not search-grounded; excluded from live scores.", "ungrounded")
    labels = answer.labels  # fixture-authored or model-produced: validated identically
    if labels is None:
        return fail("No evaluator output available (model-backed evaluator not configured).", "needs review")

    warnings = []
    body = answer_body(answer.text)
    body_mention = mentions_alias(answer.text, profile.aliases or [profile.name])
    if not body_mention and any(a.lower() in answer.text.lower() for a in profile.aliases):
        warnings.append("Ambiguous alias: lowercase/common-word use ignored, not counted as a brand mention.")
    # a blank string is a substring of everything, so it would pass a bare `in` test
    real = lambda q: isinstance(q, str) and bool(q.strip())
    bad_quotes = [q for q in labels["evidence_quotes"] if not real(q) or q not in answer.text]
    if bad_quotes:
        warnings.append(f"Invalid evidence quote(s) not found verbatim: {bad_quotes}")
    if labels["mentioned"] != body_mention:
        warnings.append(f"Label says mentioned={labels['mentioned']} but answer body says {body_mention}.")
    elif labels["mentioned"] and not mentions_alias(body, profile.aliases or [profile.name]):
        warnings.append("Label says mentioned, but the name appears only inside a citation.")
    if (labels["recommended"] or labels["negative_mention"]) and not labels["mentioned"]:
        warnings.append("Recommendation/negative flag without a mention.")
    if labels["mentioned"] and not labels["evidence_quotes"]:
        warnings.append("Mention claimed without a supporting quote.")
    # An evaluator listing the target among "other brands recommended" is a routine slip, and this
    # list is not display-only: it feeds competitor_rate, gap_priority and the round-two comparison
    # question sent to the measured model. "How does Notion compare to Notion and Confluence?" must
    # be impossible, so the target's own vocabulary is stripped here, at the one shared boundary.
    competitors = [c for c in labels["competitor_recommendations"] if not brand_leaks(c, profile)]
    if own := [c for c in labels["competitor_recommendations"] if brand_leaks(c, profile)]:
        warnings.append(f"Self-named competitor(s) dropped: {own} is the target, not a rival.")
    missing_comps = [c for c in competitors if not real(c) or c not in answer.text]
    if missing_comps:
        warnings.append(f"Competitor(s) not in answer text: {missing_comps}")
    # In the text, but only as a citation's title or host, or as a domain stem: a source the model
    # read, not a product it recommended. The name is dropped; the answer's other labels still stand.
    # A name that IS a domain ("cctk.ai", "monday.com") written in the answer's own prose stays.
    cited = [c for c in competitors if c not in missing_comps and not named_in(c, body)]
    if cited:
        warnings.append(f"Citation-only name(s) dropped, not named in the answer body: {cited}")
        competitors = [c for c in competitors if c not in cited]
    if not labels.get("on_topic", True):
        warnings.append("Off-topic answer.")
    owned = any(domain_matches(c, profile.all_domains()) for c in answer.citations)
    deceptive = [c for c in answer.citations if not domain_matches(c, profile.all_domains())
                 and any(d in c.lower() for d in profile.all_domains())]
    if deceptive:
        warnings.append(f"Lookalike domain not counted as owned citation: {deceptive}")
    if labels.get("outdated_claim_quote"):
        warnings.append(f"Possible outdated/inaccurate claim: \"{labels['outdated_claim_quote']}\"")

    blocking = [w for w in warnings
                if not w.startswith(("Ambiguous alias", "Lookalike", "Possible outdated", "Self-named",
                                         "Citation-only"))]
    valid = not blocking
    strength = None
    if valid:
        strength = 2 if labels["recommended"] else 1 if labels["mentioned"] and not labels["negative_mention"] else 0
    if not valid:
        expl = "Needs review: evidence failed validation; excluded from scores."
    elif labels["recommended"]:
        expl = "Target positively recommended (scored: recommended)."
    elif labels["negative_mention"]:
        expl = ("Target mentioned only critically; scored the same as absent, because "
                "criticism is not a recommendation.")
    elif labels["mentioned"]:
        expl = "Target mentioned descriptively but not recommended (scored: mentioned)."
    else:
        expl = "Target absent from answer body (scored: absent)."
    if owned and not labels["mentioned"]:
        expl += " Owned domain cited without a body mention (citation-only; not counted as a mention)."
    elif owned:
        expl += " Owned domain cited."
    if competitors:
        expl += f" Competitors recommended: {', '.join(competitors)}."
    return QueryEvaluation(
        probe_id=probe.id, valid=valid, mentioned=labels["mentioned"], recommended=labels["recommended"],
        negative_mention=labels["negative_mention"], competitor_recommendations=competitors,
        evidence_quotes=labels["evidence_quotes"], owned_citation=owned, strength=strength,
        explanation=expl, warnings=warnings)


def extract_attributes(answer: Answer, attributes: list[Attribute]) -> tuple[list[AttributeObservation], list[str]]:
    """Fixture (later: model) proposes attribute observations; this code refuses to trust them.

    A quote that is not a verbatim substring of the answer is dropped, not repaired. An unverifiable
    observation must never reach the drift map, or every number downstream is noise.
    """
    labels = (answer.labels or {}).get("attributes") or []
    known = {a.id for a in attributes}
    kept, warnings = [], []
    for raw in labels:
        aid, quote = raw.get("attribute_id"), raw.get("quote", "")
        if aid not in known:
            warnings.append(f"Unknown attribute id {aid!r}: dropped.")
            continue
        if not isinstance(quote, str) or not quote.strip() or quote not in answer.text:
            warnings.append(f"Attribute {aid}: quote not verbatim in the answer; dropped.")
            continue
        if quote not in answer_body(answer.text):
            warnings.append(f"Attribute {aid}: quote is from a citation, not the answer; dropped.")
            continue
        kept.append(AttributeObservation(attribute_id=aid, quote=quote,
                                         polarity=raw.get("polarity", "neutral")))
    seen, deduped = set(), []
    for o in kept:  # one observation per attribute per answer: echoes count answers, not sentences
        if o.attribute_id not in seen:
            seen.add(o.attribute_id)
            deduped.append(o)
    return deduped, warnings


def build_findings(topics: list[Topic], topic_evals: list[TopicEvaluation], evals: list[QueryEvaluation],
                   probes: list[Probe]) -> list[GapFinding]:
    ev = {e.probe_id: e for e in evals}
    pn = probe_names(probes, topics)
    findings = []
    for t in topics:
        te = next((x for x in topic_evals if x.topic_id == t.id and x.phase == "baseline"), None)
        if te is None:
            continue
        base_ids = [p.id for p in probes if p.topic_id == t.id and p.phase == "baseline"]
        fu_ids = [p.id for p in probes if p.topic_id == t.id and p.phase == "followup"]
        fu_te = next((x for x in topic_evals if x.topic_id == t.id and x.phase == "followup"), None)
        note = None
        if fu_ids and fu_te:
            note = (f"Exploratory follow-ups {with_ids(fu_ids, pn)} (not merged into baseline): "
                    f"{fu_te.recommendations}/{fu_te.n} recommended.")
        limits = list(te.limitations) + [
            "Citations alone do not prove why a model chose a brand.",
            "Absence alone is not proof of opportunity or market demand."]

        def add(key, observation, interpretation, evidence_ids, extra_limits=()):
            cap, url, action = CAPABILITIES[key]
            findings.append(GapFinding(
                topic_id=t.id, observation=observation, evidence_ids=evidence_ids, fit_evidence_ids=t.fit_evidence_ids,
                interpretation=interpretation, suggested_action=action, profound_capability=cap, capability_url=url,
                limitations=limits + list(extra_limits), provenance=te.provenance, gap_priority=te.gap_priority,
                exploratory_note=note))

        if te.status in ("insufficient evidence", "unclear"):
            findings.append(GapFinding(
                topic_id=t.id, observation=f"Status: {te.status} ({te.n} eligible, {te.excluded} excluded).",
                evidence_ids=base_ids, fit_evidence_ids=t.fit_evidence_ids,
                interpretation="Insufficient evidence to connect this topic to a gap or a capability.",
                suggested_action="Collect more eligible observations before drawing conclusions.",
                profound_capability=None, capability_url=None, limitations=limits, provenance=te.provenance,
                exploratory_note=note))
            continue
        if te.status == "observed presence":
            continue
        comps = ", ".join(te.top_competitors) or "none"
        if te.status == "candidate gap":
            add("absent_vs_competitors",
                f"Not recommended in any of {te.n} baseline answers while competitors were ({comps}).",
                f"Candidate gap in a strong-fit topic ({PRIORITY_LABEL} {te.gap_priority:g}).", base_ids)
        neg = [i for i in base_ids if ev.get(i) and ev[i].negative_mention]
        described = [i for i in base_ids if ev.get(i) and ev[i].mentioned and not ev[i].recommended]
        if te.status == "mixed":
            if described:
                add("poor_match", f"Recommended in {te.recommendations}/{te.n}; mentioned without recommendation in {with_ids(described, pn)}.",
                    "Brand appears but is not clearly matched to this use case in some answers.", base_ids)
            else:
                add("absent_vs_competitors", f"Recommended in {te.recommendations}/{te.n}; absent elsewhere while competitors appeared ({comps}).",
                    "Mixed visibility; the small sample cannot show whether this persists.", base_ids)
        if neg and te.status == "candidate gap":
            add("poor_match", f"Negative mention(s) in {with_ids(neg, pn)}.",
                "The brand is described critically for this use case.", neg)
        outdated = [i for i in base_ids if ev.get(i) and any(w.startswith("Possible outdated") for w in ev[i].warnings)]
        if outdated:
            add("factcheck", f"Answer(s) to {with_ids(outdated, pn)} contain a product claim flagged as possibly outdated.",
                "Needs comparison against current authoritative product facts.", outdated,
                ["Accuracy not yet verified against current company pages."])
        if t.fit == "strong" and te.owned_citations == 0 and te.recommendations < te.n:
            add("content", f"No owned-domain citations across {te.n} baseline answers.",
                "Possible owned-content gap for these questions.", base_ids,
                ["Content gap NOT confirmed: the company's relevant pages were not examined."])
    return sorted(findings, key=lambda f: -(f.gap_priority or -1))
