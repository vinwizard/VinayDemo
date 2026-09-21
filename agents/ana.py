"""Agent 2 — AnA (Assimilate and Attack): topics, neutral probes, one adaptive round.

Demo implementation: plans come from fixtures; follow-up *selection* is a deterministic
policy over the current evaluations (simulated AnA policy). A model-backed planner can
replace `choose_followup` behind the same signature later.
"""
import hashlib
import json
import re
from collections import Counter

from schemas import (AdaptiveDecision, Attribute, CompanyProfile, Probe, QueryEvaluation, Topic,
                     TopicEvaluation)

MAX_TOPICS = 4
PER_TOPIC = 3
MAX_FOLLOWUP_TOPICS = 2
PER_FOLLOWUP_TOPIC = 2
MAX_COMPARED = 3
COMPARISON_PROBE_ID = "np-cmp"


def leak_terms(profile: CompanyProfile) -> list[str]:
    terms = {profile.name, *profile.aliases, *profile.branded_terms}
    for d in profile.all_domains():
        terms |= {d, d.split(".")[0]}
    return sorted(t for t in terms if t and len(t) > 2)


def brand_leaks(text: str, profile: CompanyProfile) -> list[str]:
    """Case-insensitive on purpose: a measured question must not even hint at the target."""
    return [t for t in leak_terms(profile) if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I)]


def attribute_leaks(text: str, attributes: list[Attribute]) -> list[str]:
    """A named probe may say the brand; it must NEVER say the attribute being measured.

    Asking "is Notion an AI-native workspace?" invites the model to agree, and the resulting echo
    measures the question, not the model's own view. This is the perception-axis analogue of
    `brand_leaks` and is just as load-bearing.
    """
    hits = []
    for a in attributes:
        for phrase in [a.label, *a.aliases]:
            if len(phrase) > 3 and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.I):
                hits.append(a.id)
                break
    return hits


def blind_probes_from_attributes(attributes: list[Attribute], profile: CompanyProfile
                                 ) -> tuple[list[Topic], list[Probe]]:
    """The placebo test: one buyer topic per intended attribute, questions that never name the brand.

    If a company claims to be X, a buyer asking for X should find them. Asking the question the
    company's own positioning implies — with no brand name, in a fresh context — is a stronger test
    than a generic topic question, because a miss cannot be blamed on an irrelevant question.

    Aspiration is not product fit (agents.md section 3): an attribute their own copy states gets
    `strong` fit, one they merely want gets `partial`. A question that leaks the brand is rejected,
    never rewritten.
    """
    topics, probes, dropped = [], [], []
    # Heaviest intent first, so truncation to MAX_TOPICS keeps the claims the customer cares about
    # most rather than whichever the extraction model emitted first. The sort is stable: equal
    # weights keep stored order, so the same company always plans the same questions.
    eligible = sorted((x for x in attributes if x.intended and x.buyer_questions),
                      key=lambda x: -x.intended_weight)
    for a in eligible:
        topic = Topic(id=f"pos-{a.id}", label=a.label, kind="buyer",
                      buyer_need=f"A buyer looking for: {a.label.lower()}",
                      positioning_point_ids=[], fit="strong" if a.claimed else "partial",
                      fit_evidence_ids=list(a.claim_evidence_ids))
        kept = 0
        for i, text in enumerate(a.buyer_questions[:PER_TOPIC], start=1):
            if leaks := brand_leaks(text, profile):
                dropped.append(f"{a.id}-{i} ({', '.join(leaks)})")
                continue
            probes.append(Probe(
                id=f"{a.id}-b{i}", topic_id=topic.id, text=text, kind="blind", phase="baseline",
                purpose=f"Placebo: would a buyer wanting '{a.label}' be shown this brand?"))
            kept += 1
        if kept:
            topics.append(topic)
    if dropped:
        raise ValueError("buyer questions leak the brand and were not rewritten: " + "; ".join(dropped))
    # Truncation drops topics, so it must drop their questions too: a probe whose topic no longer
    # exists fails validation and kills the whole run.
    topics = topics[:MAX_TOPICS]
    kept_topics = {t.id for t in topics}
    return topics, [p for p in probes if p.topic_id in kept_topics]


def validate_named_probes(probes: list[Probe], attributes: list[Attribute]) -> list[str]:
    errors = []
    for p in probes:
        if p.kind != "named":
            continue
        if leaks := attribute_leaks(p.text, attributes):
            errors.append(f"{p.id} leaks the attribute(s) it measures: {', '.join(leaks)}")
    return errors


def validate_probes(probes: list[Probe], topics: list[Topic], profile: CompanyProfile) -> list[str]:
    errors = []
    topic_ids = {t.id for t in topics}
    buyer = [t for t in topics if t.kind == "buyer"]
    if len(buyer) > MAX_TOPICS:
        errors.append(f"{len(buyer)} buyer topics exceeds {MAX_TOPICS}")
    for t in buyer:
        if t.fit == "unsupported":
            errors.append(f"topic {t.id} has no supported fit")
    seen = set()
    for p in probes:
        if p.kind == "blind" and (leaks := brand_leaks(p.text, profile)):
            errors.append(f"{p.id} leaks target identity: {', '.join(leaks)}")
        if p.topic_id not in topic_ids:
            errors.append(f"{p.id} references unknown topic {p.topic_id}")
        if p.text.strip().lower() in seen:
            errors.append(f"{p.id} duplicates an earlier question")
        seen.add(p.text.strip().lower())
    for t in buyer:  # the perception container is sized by the named-probe budget, not PER_TOPIC
        if sum(p.topic_id == t.id and p.kind == "blind" for p in probes) > PER_TOPIC:
            errors.append(f"topic {t.id} has more than {PER_TOPIC} baseline questions")
    return errors


def discovered_competitors(topic_evals: list[TopicEvaluation], limit: int = MAX_COMPARED) -> list[str]:
    """The names AI volunteered in the blind answers, most widely seen first.

    Nobody supplied these and nobody was asked for them: a blind question describes what the
    company does without naming it, so any brand the model offers back is, by definition, who it
    thinks the buyer should use instead. Each name has already been checked verbatim against the
    answer it came from (agents/evaluation.py), so nothing here is invented.
    """
    counts = Counter(c for te in topic_evals if te.phase == "baseline" for c in te.top_competitors)
    return [name for name, _ in counts.most_common(limit)]


def comparison_probe(profile: CompanyProfile, names: list[str], parents: list[str]) -> Probe:
    """Round two of the named axis: compare the brand to the competitors AI itself named.

    Kept at `phase="followup"` on purpose. It is exploratory evidence about how the model frames
    the brand against that set, and it must not move the baseline alignment score — the baseline is
    frozen before any of these names exist.
    """
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return Probe(id=COMPARISON_PROBE_ID, topic_id="perception", kind="named", phase="followup",
                 text=f"How does {profile.name} compare to {listed}?",
                 purpose="Exploratory: how AI frames the brand against the competitors it named itself.",
                 parent_probe_ids=parents)


def baseline_hash(probes: list[Probe]) -> str:
    base = [p.model_dump() for p in probes if p.phase == "baseline"]
    return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


def choose_followup(topics: list[Topic], topic_evals: list[TopicEvaluation], evals: list[QueryEvaluation],
                    probes: list[Probe], bank: dict[str, list[dict]], profile: CompanyProfile) -> AdaptiveDecision:
    """Pick supported topics with the highest candidate-gap priority; mixed results as fallback."""
    fit = {t.id: t.fit for t in topics}
    base = [te for te in topic_evals if te.phase == "baseline" and fit.get(te.topic_id) != "unsupported"
            and te.gap_priority is not None]
    gaps = sorted((te for te in base if te.status == "candidate gap"), key=lambda te: -te.gap_priority)
    mixed = sorted((te for te in base if te.status == "mixed"), key=lambda te: -te.gap_priority)
    chosen = [te for te in gaps + mixed if te.gap_priority > 0][:MAX_FOLLOWUP_TOPICS]
    if not chosen:
        return AdaptiveDecision(
            selected_topics=[], new_probes=[], evidence_probe_ids=[],
            rationale="Stop: no topic with supported fit was left unrecommended or split, "
                      "so another round of questions would add nothing.")
    label = {t.id: t.label for t in topics}
    strength = {e.probe_id: e.strength for e in evals}
    asked = {p.text.strip().lower() for p in probes}
    new, evidence, why = [], [], []
    for te in chosen:
        motivating = [p.id for p in probes if p.topic_id == te.topic_id and p.phase == "baseline"
                      and (strength.get(p.id) or 0) < 2]
        answered = [i for i in motivating if strength.get(i) is not None]
        evidence += motivating
        for raw in bank.get(te.topic_id, [])[:PER_FOLLOWUP_TOPIC]:
            p = Probe(**raw, parent_probe_ids=motivating)
            if p.text.strip().lower() in asked or brand_leaks(p.text, profile):
                continue  # not novel or not neutral: skip rather than ask
            new.append(p)
        uncertainty = ("whether the absence persists under differently framed buyer questions"
                       if te.status == "candidate gap" else "why results were split across similar questions")
        found = (f"not recommended in any of {te.n} answers" if not te.recommendations
                 else f"recommended in only {te.recommendations} of {te.n} answers")
        n_m = len(answered)
        motive = (f"{n_m} answer{'' if n_m == 1 else 's'} that did not recommend the brand" if answered
                  else "the topic-level result")
        why.append(f"{label.get(te.topic_id, te.topic_id)} — {found}; asking more questions to test "
                   f"{uncertainty}, prompted by {motive}")
    return AdaptiveDecision(selected_topics=[te.topic_id for te in chosen], new_probes=new,
                            evidence_probe_ids=evidence, rationale=" | ".join(why))
