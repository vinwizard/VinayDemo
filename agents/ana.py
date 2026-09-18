"""Agent 2 — AnA (Assimilate and Attack): topics, neutral probes, one adaptive round.

Demo implementation: plans come from fixtures; follow-up *selection* is a deterministic
policy over the current evaluations (simulated AnA policy). A model-backed planner can
replace `choose_followup` behind the same signature later.
"""
import hashlib
import json
import re

from schemas import AdaptiveDecision, CompanyProfile, Probe, QueryEvaluation, Topic, TopicEvaluation

MAX_TOPICS = 4
PER_TOPIC = 3
MAX_FOLLOWUP_TOPICS = 2
PER_FOLLOWUP_TOPIC = 2


def leak_terms(profile: CompanyProfile) -> list[str]:
    terms = {profile.name, *profile.aliases, *profile.branded_terms}
    for d in profile.all_domains():
        terms |= {d, d.split(".")[0]}
    return sorted(t for t in terms if t and len(t) > 2)


def brand_leaks(text: str, profile: CompanyProfile) -> list[str]:
    """Case-insensitive on purpose: a measured question must not even hint at the target."""
    return [t for t in leak_terms(profile) if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I)]


def validate_probes(probes: list[Probe], topics: list[Topic], profile: CompanyProfile) -> list[str]:
    errors = []
    topic_ids = {t.id for t in topics}
    if len(topics) > MAX_TOPICS:
        errors.append(f"{len(topics)} topics exceeds {MAX_TOPICS}")
    for t in topics:
        if t.fit == "unsupported":
            errors.append(f"topic {t.id} has no supported fit")
    seen = set()
    for p in probes:
        if leaks := brand_leaks(p.text, profile):
            errors.append(f"{p.id} leaks target identity: {', '.join(leaks)}")
        if p.topic_id not in topic_ids:
            errors.append(f"{p.id} references unknown topic {p.topic_id}")
        if p.text.strip().lower() in seen:
            errors.append(f"{p.id} duplicates an earlier question")
        seen.add(p.text.strip().lower())
    for t in topics:
        if sum(p.topic_id == t.id for p in probes) > PER_TOPIC:
            errors.append(f"topic {t.id} has more than {PER_TOPIC} baseline questions")
    return errors


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
        return AdaptiveDecision(selected_topics=[], new_probes=[], evidence_probe_ids=[],
                                rationale="Stop: no supported topic shows a candidate gap or mixed result worth another round.")
    strength = {e.probe_id: e.strength for e in evals}
    asked = {p.text.strip().lower() for p in probes}
    new, evidence, why = [], [], []
    for te in chosen:
        motivating = [p.id for p in probes if p.topic_id == te.topic_id and p.phase == "baseline"
                      and (strength.get(p.id) or 0) < 2]
        evidence += motivating
        for raw in bank.get(te.topic_id, [])[:PER_FOLLOWUP_TOPIC]:
            p = Probe(**raw, parent_probe_ids=motivating)
            if p.text.strip().lower() in asked or brand_leaks(p.text, profile):
                continue  # not novel or not neutral: skip rather than ask
            new.append(p)
        uncertainty = ("whether the absence persists under differently framed buyer questions"
                       if te.status == "candidate gap" else "why results were split across similar questions")
        why.append(f"{te.topic_id} ({te.status}, {te.recommendations}/{te.n} recommended, priority {te.gap_priority:g}): "
                   f"tests {uncertainty}; motivated by {', '.join(motivating) or 'topic-level results'}")
    return AdaptiveDecision(selected_topics=[te.topic_id for te in chosen], new_probes=new,
                            evidence_probe_ids=evidence, rationale=" | ".join(why))
