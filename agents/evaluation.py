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

# The `([host](url))` inline citations, the source-card lines that are nothing but a link, and every
# naked URL. A link inside a sentence ("Try [Asana](https://asana.com)") is the answer's own words.
CITATION = re.compile(r"\(\[[^\]]*\]\([^)\s]*\)\)"
                      r"|(?<![^\n])[^\w\n]*(?:\d+\.)?[^\w\n]*\[[^\]]*\]\([^)\s]*\)[^\w\n]*(?![^\n])"
                      r"|(?<!\]\()https?://\S+")
LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")


def answer_body(text: str) -> str:
    """The answer minus its citation markup, prose links reduced to their text. A name that exists
    only in a citation is a source the model read, not something it said, so body checks run on this
    and never on the raw text."""
    return LINK.sub(r"\1", CITATION.sub(" ", text))


# Markdown emphasis delimiters: a run of * or _ touching a non-word character. The intraword _ of
# "snake_case" is text, not emphasis, and stays.
EMPHASIS = re.compile(r"(?<!\w)[*_]+|[*_]+(?!\w)")


def quoted_in(quote: str, text: str) -> bool:
    """Verbatim, except for markdown emphasis and case. An answer that names the brand is the only
    kind with a quote to check, so every copy slip ("Notion AI: Enhances" for "**Notion AI**:
    Enhances", "applications" for "Applications") deleted a positive observation and never a zero:
    the check biased visibility toward absent. Still a substring test — a quote whose words differ
    fails."""
    plain = lambda s: EMPHASIS.sub("", s).casefold()
    return plain(quote) in plain(text)


def real(q) -> bool:
    """A blank string is a substring of everything, so it would pass a bare `in` test."""
    return isinstance(q, str) and bool(q.strip())


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
    body_mention = mentions_alias(answer.text, profile.names())
    if not body_mention and any(a.lower() in answer.text.lower() for a in profile.names()):
        warnings.append("Ambiguous alias: lowercase/common-word use ignored, not counted as a brand mention.")
    bad_quotes = [q for q in labels["evidence_quotes"] if not real(q) or not quoted_in(q, answer.text)]
    if bad_quotes:
        warnings.append(f"Invalid evidence quote(s) not found verbatim: {bad_quotes}")
    if labels["mentioned"] != body_mention:
        warnings.append(f"Label says mentioned={labels['mentioned']} but answer body says {body_mention}.")
    elif labels["mentioned"] and not mentions_alias(body, profile.names()):
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
        if quote not in CITATION.sub(" ", answer.text):
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


# A characterisation one answer makes is one model's phrasing on one day: noise. The same one raised
# independently by a second answer to a different question is the start of an identity, and is what
# lets the discovery pass see repetition at all. Two is also what clears drift.IMPOSED_MIN at the
# MAX_NAMED=8 brand answers a run can have, so a kept attribute can never be filtered out as noise.
EMERGENT_MIN_ANSWERS = 2

# Words that carry no claim. Two phrasings that share only these are not the same attribute.
FILLER = frozenset("a an the and or of for to in on at by with from as is are be it its your you "
                   "their very too more most less than that this can has have not no".split())
SUFFIXES = ("able", "ing", "es", "ed", "ly", "ey", "er", "s", "y", "e")


def _stem(w: str) -> str:
    """Naive: "pricing", "priced" and "pricey" all become "pric". Over-merging is the safe error."""
    return next((w[:-len(s)] for s in SUFFIXES if w.endswith(s) and len(w) - len(s) >= 3), w)


def content_words(text: str, ignore: frozenset = frozenset()) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 1 and w not in FILLER and w not in ignore}


def discover_attributes(proposals, answers: dict[str, Answer], attributes: list[Attribute],
                        observations: dict[str, list[AttributeObservation]], profile: CompanyProfile
                        ) -> tuple[list[Attribute], dict[str, list[AttributeObservation]], list[str]]:
    """The discovery pass proposes attributes nobody declared; this code refuses to trust them.

    answers: the ELIGIBLE brand answers only, by probe id. observations: what extract_attributes
    already kept for the declared attributes. -> (new attributes, their observations, drop reasons).

    A proposal survives only if its quote is verbatim in the answer it cites — the same check as
    `evaluate()`, never looser — in at least EMERGENT_MIN_ANSWERS different eligible answers, and it
    is not an attribute already in the list. Sameness is decided conservatively, because a duplicate
    double-counts in the report while a wrongly dropped proposal is only a finding not made: it is
    the same as an attribute when at least half of its label's content words (filler and the brand's
    own name ignored, suffixes trimmed) appear in that attribute's label or aliases, or when any of
    its quotes contains, or is contained in, a quote already counted for that attribute in the same
    answer. Proposals are taken most-supported first and checked against each other the same way.
    """
    brand = frozenset(w for n in profile.names() for w in re.findall(r"[a-z0-9]+", n.lower()))
    dropped, candidates = [], []
    for raw in proposals if isinstance(proposals, list) else []:
        label = raw.get("label") if isinstance(raw, dict) else None
        if not real(label):
            dropped.append(f"Proposal without a label: {raw!r}")
            continue
        label, found, bad = label.strip(), {}, []
        for e in raw.get("evidence") if isinstance(raw.get("evidence"), list) else []:
            pid, quote = (e.get("answer"), e.get("quote")) if isinstance(e, dict) else (None, None)
            if pid not in answers:
                bad.append(f"cites {pid!r}, not an eligible brand answer")
            elif not real(quote) or not quoted_in(quote, answers[pid].text):
                bad.append(f"{pid}: quote not verbatim in the answer ({quote!r})")
            elif not quoted_in(quote, CITATION.sub(" ", answers[pid].text)):
                bad.append(f"{pid}: quote is from a citation, not the answer ({quote!r})")
            elif pid not in found:  # one observation per answer: support counts answers
                polarity = e.get("polarity") if e.get("polarity") in ("positive", "neutral", "negative") else "neutral"
                found[pid] = AttributeObservation(attribute_id="", quote=quote, polarity=polarity)
        candidates.append((label, raw.get("description"), found, bad))

    # Everything already counted: each attribute's phrasings, and its quotes per answer.
    known = [(content_words(" ".join([a.label, *a.aliases]), brand), a.label,
              {pid: [o.quote for o in obs if o.attribute_id == a.id] for pid, obs in observations.items()})
             for a in attributes]

    def same_as(words: set[str], found: dict[str, AttributeObservation]):
        for phrasing, name, quotes in known:
            if 2 * len(words & phrasing) >= len(words):
                return f"shares '{' '.join(sorted(words & phrasing))}' with '{name}'"
            for pid, o in found.items():
                if any(quoted_in(o.quote, q) or quoted_in(q, o.quote) for q in quotes.get(pid, [])):
                    return f"{pid} quotes the same words for '{name}'"
        return None

    new, new_obs = [], {}
    for label, desc, found, bad in sorted(candidates, key=lambda c: -len(c[2])):
        why = f" Rejected evidence: {'; '.join(bad)}." if bad else ""
        words = content_words(label, brand)
        if len(found) < EMERGENT_MIN_ANSWERS:
            dropped.append(f"'{label}': raised with a verbatim quote in {len(found)} eligible answer(s), "
                           f"needs {EMERGENT_MIN_ANSWERS}.{why}")
        elif not words:
            dropped.append(f"'{label}': no content words to tell it apart from what is measured.")
        elif same := same_as(words, found):
            dropped.append(f"'{label}': same attribute as one already measured ({same}).{why}")
        else:
            # distinct words give a distinct slug: two labels that slug alike were dropped as the same
            aid = "emergent_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            new.append(Attribute(id=aid, label=label, description=desc if real(desc) else None,
                                 discovered=True))
            if bad:
                dropped.append(f"'{label}': kept on its verbatim answers.{why}")
            for pid, o in found.items():
                new_obs.setdefault(pid, []).append(o.model_copy(update={"attribute_id": aid}))
            known.append((words, label, {pid: [o.quote] for pid, o in found.items()}))
    return new, new_obs, dropped


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
