"""Agent 2 — AnA (Assimilate and Attack): topics, neutral probes, one adaptive round.

Demo implementation: plans come from fixtures; follow-up *selection* is a deterministic
policy over the current evaluations (simulated AnA policy). A model-backed planner can
replace `choose_followup` behind the same signature later.
"""
import hashlib
import json
import re
from collections import Counter

from config import setting
from schemas import (AdaptiveDecision, Attribute, AttributeScore, CompanyProfile, Probe,
                     QueryEvaluation, Topic, TopicEvaluation)

# Buyer questions per front, asked ONCE each. The old budget spent three tries on six questions a
# side; re-asking one question moved visibility a few points while different questions disagreed by
# tens, so the same money buys a far tighter confidence interval spent on more questions instead.
# A small sample of them is still re-asked for the wobble estimate (providers/live.REPEAT_SAMPLE).
QUESTIONS_ENV = "BUYER_QUESTIONS"
DEFAULT_QUESTIONS = 12
PER_TOPIC = 3
CONTROL_TOPIC = "control"
MAX_FOLLOWUP_TOPICS = 2
PER_FOLLOWUP_TOPIC = 2
MAX_COMPARED = 3
COMPARISON_PROBE_ID = "np-cmp"


def set_questions() -> int:
    """BUYER_QUESTIONS: unbranded questions per front, at least one topic's worth."""
    return setting(QUESTIONS_ENV, DEFAULT_QUESTIONS, floor=PER_TOPIC)


def max_topics() -> int:
    """The whole buyer topic budget: `set_questions()` a front, both fronts, in topics of PER_TOPIC."""
    return 2 * -(-set_questions() // PER_TOPIC)


def leak_terms(profile: CompanyProfile) -> list[str]:
    terms = {*profile.names(), *profile.branded_terms}  # generic aliases are not the brand
    for d in profile.all_domains():
        terms |= {d, d.split(".")[0]}
    return sorted(t for t in terms if t and len(t) > 2)


def brand_leaks(text: str, profile: CompanyProfile) -> list[str]:
    """Case-insensitive on purpose: a measured question must not even hint at the target."""
    return [t for t in leak_terms(profile) if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I)]


# A buyer who has never heard of the brand cannot address it. "How does your platform improve our
# shipping speed?" makes the chatbot play some vendor — it answered as ShipStation — and "these
# agents" points at a product the question never names. Generic "you" ("your own documents",
# "can you suggest…") is how people type to a chatbot and is left alone.
# ponytail: lexical, catches the observed shapes only; a model judging "addressed to a vendor?" is
# the upgrade if new shapes get through.
VENDOR_ADDRESS = re.compile(
    r"\byour (?:[\w-]+ )?(?:platform|solution|service)\b"
    r"|\b(?:do|does|can|could|will) you (?:offer|have|provide|support|sell|integrate)\b"
    r"|\b(?:this|these) (?:product|platform|feature|tool|app|software|solution|service|system|agent)s?\b"
    r"|\bthe (?:platform|system)\b", re.I)


def vendor_address(text: str) -> list[str]:
    """What in an unbranded question addresses the vendor instead of describing the need, or []."""
    return [m.group(0) for m in VENDOR_ADDRESS.finditer(text)]


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


def blind_probes_from_attributes(attributes: list[Attribute], profile: CompanyProfile,
                                 limit: int = 0) -> tuple[list[Topic], list[Probe], list[str]]:
    """The placebo test: buyer topics whose questions never name the brand, one per intended (or,
    unweighted, most-stated) claim, at most `limit` of them. blind_probes_for_fronts gives them
    whatever buyer budget the fronts leave: all of it with neither front, half with only one.

    If a company claims to be X, a buyer asking for X should find them. Asking the question the
    company's own positioning implies — with no brand name, in a fresh context — is a stronger test
    than a generic topic question, because a miss cannot be blamed on an irrelevant question.

    Aspiration is not product fit (.claude/skills/product-workflow): an attribute their own copy states gets
    `strong` fit, one they merely want gets `partial`. A question that leaks the brand is rejected,
    never rewritten. A question addressed to the vendor is skipped, not fatal; the third return value
    names the skipped question ids so the run log can say why a topic is missing.
    """
    limit = limit or max_topics()
    topics, probes, dropped, skipped = [], [], [], []

    def ask(topic: Topic, key: str, questions: list[str], purpose: str, first: int = 1) -> None:
        kept = 0
        for i, text in enumerate(questions, start=first):
            if leaks := brand_leaks(text, profile):
                dropped.append(f"{key}-{i} ({', '.join(leaks)})")
                continue
            # Saved before onboarding vetted for this: refused, not rewritten, and not fatal — it
            # measures our question, not the brand, but raising would strand every older company.
            if vendor := vendor_address(text):
                skipped.append(f"{key}-{i} ({', '.join(vendor)})")
                continue
            probes.append(Probe(id=f"{key}-b{i}", topic_id=topic.id, text=text, kind="blind",
                                phase="baseline", purpose=purpose))
            kept += 1
        if kept:
            topics.append(topic)

    # Heaviest intent first, so truncation to `limit` keeps the claims the customer cares about
    # most rather than whichever the extraction model emitted first. With nothing weighted the run
    # still goes ahead (the claim lens): the claims stated on the most pages go first instead. The
    # sort is stable: ties keep stored order, so the same company always plans the same questions.
    if any(x.intended for x in attributes):
        eligible = sorted((x for x in attributes if x.intended and x.buyer_questions),
                          key=lambda x: -x.intended_weight)
    else:
        eligible = sorted((x for x in attributes if x.buyer_questions and (x.claimed or x.claim_pages)),
                          key=lambda x: -x.claim_pages)
    for a in eligible:
        ask(Topic(id=f"pos-{a.id}", label=a.label, kind="buyer",
                  buyer_need=f"A buyer looking for: {a.label.lower()}",
                  positioning_point_ids=[], fit="strong" if a.claimed else "partial",
                  fit_evidence_ids=list(a.claim_evidence_ids)),
            a.id, a.buyer_questions[:PER_TOPIC],
            f"Placebo: would a buyer wanting '{a.label}' be shown this brand?")
    if dropped:
        raise ValueError("unbranded questions leak the brand and were not rewritten: " + "; ".join(dropped))
    # Truncation drops topics, so it must drop their questions too: a probe whose topic no longer
    # exists fails validation and kills the whole run.
    topics = topics[:limit]
    kept_topics = {t.id for t in topics}
    return topics, [p for p in probes if p.topic_id in kept_topics], skipped


def control_probe(profile: CompanyProfile, category: str | None = None, pid: str = "ctl-1",
                  topic_id: str = CONTROL_TOPIC) -> Probe | None:
    """The control: does the answering model know which companies lead this category at all?

    A low buyer visibility means little when the model cannot name the category's leaders, or does
    not count the brand among them, so one blind question asks exactly that. It is never scored as
    visibility (phase "control"); its answer only decides whether the number is trusted
    (scoring.low_confidence). One per visibility set, each about its own category.
    """
    category = category or profile.core_category
    if not category:
        return None
    return Probe(id=pid, topic_id=topic_id, kind="blind", phase="control",
                 # companies, not "tools": asked for the leading tools for biologic medicines,
                 # the model named none at all
                 text=f"Which companies lead in {category}?",
                 purpose="Control: does the answering model know which companies lead this category? "
                         "Excluded from the visibility score.")


def control_topic(profile: CompanyProfile, category: str | None = None, tid: str = CONTROL_TOPIC,
                  front: str | None = None) -> Topic:
    return Topic(id=tid, label=f"Control — {category or profile.core_category}", kind="control",
                 front=front, buyer_need="Whether the answering model knows the category's leading companies",
                 positioning_point_ids=[], fit="strong")


def perception_topic() -> Topic:
    return Topic(id="perception", label="Brand perception", kind="perception",
                 buyer_need="How AI characterises the brand when asked about it directly",
                 positioning_point_ids=[], fit="strong")


# ---------------------------------------------------------------- two fronts, side by side
def same_category(a: str, b: str) -> bool:
    """Case-insensitive, and near-duplicates too: "AI search visibility" is the category "AI search
    visibility tracking". Same only when every content word of one is in the other, so "Project
    management" and "Product management" stay two categories."""
    from agents.evaluation import content_words  # evaluation imports this module
    x, y = content_words(a), content_words(b)
    return a.strip().lower() == b.strip().lower() or bool(x and y) and (x <= y or y <= x)


def placed_attribute(scores: list[AttributeScore], attributes: list[Attribute],
                     profile: CompanyProfile) -> Attribute | None:
    """Where AI already places the company: the attribute, claimed or emergent, that the most valid
    brand answers associated with it supportively. Ties go to the claim the site states on more
    pages. None when no brand answer endorsed anything. An attribute whose label names the brand is
    skipped: it could not be asked about without naming it."""
    by = {a.id: a for a in attributes}
    ranked = sorted((s for s in scores if s.echo_rate and s.attribute_id in by
                     and not brand_leaks(s.label, profile)),
                    key=lambda s: (-s.echo_rate, -by[s.attribute_id].claim_pages))
    return by[ranked[0].attribute_id] if ranked else None


def blind_probes_for_fronts(profile: CompanyProfile, placed: Attribute | None,
                            placed_questions: list[str], attributes: list[Attribute] = (),
                            placed_category: str | None = None
                            ) -> tuple[list[Topic], list[Probe], list[str], dict[str, str]]:
    """Buyer questions on both fronts: where AI places the company (`placed`, its questions already
    written) and where its homepage says it aims to be (the core category). -> (topics, probes with
    one control per set, skipped question notes, front -> why it was not measured).

    Each front gets half the buyer budget; when both are the same category the set is asked once.
    Whatever budget the fronts leave goes to the claims' own buyer questions
    (blind_probes_from_attributes), an unlabelled group counted as neither front, so the sample
    never shrinks. Blind questions are vetted like any other: one that names the brand or addresses
    the vendor is skipped, never rewritten. `placed_category` is where AI places the company as a
    buyer would name it; without one the attribute's own label stands in.
    """
    aiming = profile.core_category
    placed_as = placed_category or (placed.label if placed else None)
    fronts, missing = [], {}
    if placed and aiming and same_category(placed_as, aiming):
        fronts.append(("both", aiming, [*profile.category_questions, *placed_questions]))
    else:
        if placed:
            fronts.append(("placed", placed_as, placed_questions))
        else:
            missing["placed"] = (f"No brand answer endorsed any attribute, so there is no category where "
                                 f"AI already places {profile.name}.")
        if aiming:
            fronts.append(("aiming", aiming, profile.category_questions))
        else:
            missing["aiming"] = (f"No core category is saved for {profile.name}, so where it aims to be "
                                 f"was not asked about. Set the category on the claims screen to measure it.")
    topics, probes, skipped = [], [], []
    seen = set()
    for front, category, questions in fronts:
        prefix = "placed" if front == "placed" else "cat"
        control = control_probe(profile, category, pid="ctl-2" if front == "placed" else "ctl-1",
                                topic_id="control-placed" if front == "placed" else CONTROL_TOPIC)
        seen.add(control.text.strip().lower())
        kept = []
        for i, q in enumerate(questions, start=1):
            if q.strip().lower() in seen:
                continue
            if why := brand_leaks(q, profile) or vendor_address(q):
                skipped.append(f"{prefix}-{i} ({', '.join(why)})")
                continue
            seen.add(q.strip().lower())
            kept.append(q)
        kept = kept[:set_questions()]
        fit = "strong" if front != "placed" or placed.claimed else "partial"
        # the placed front is what AI says, not what the site claims: only its own claim evidence
        points = [] if front == "placed" else [pp.id for pp in profile.positioning_points[:1]]
        for n in range(0, len(kept), PER_TOPIC):
            t = Topic(id=f"{prefix}-{n // PER_TOPIC + 1}", label=category, kind="buyer", front=front,
                      buyer_need=f"A buyer looking for: {category}", fit=fit, positioning_point_ids=points,
                      fit_evidence_ids=list(placed.claim_evidence_ids) if front == "placed" else [])
            topics.append(t)
            probes += [Probe(id=f"{prefix}-b{n + j + 1}", topic_id=t.id, text=q, kind="blind",
                             phase="baseline", purpose=f"{FRONT_PURPOSE[front]} would a buyer shopping "
                                                       f"for {category} be shown this brand?")
                       for j, q in enumerate(kept[n:n + PER_TOPIC])]
        if kept:
            topics.append(control_topic(profile, category, control.topic_id, front))
            probes.append(control)
            continue
        why = (f"every unbranded question for {category} named {profile.name} or addressed the vendor"
               if questions else f"no unbranded questions are saved or could be written for {category}")
        for f in (("placed", "aiming") if front == "both" else (front,)):
            where = f"Where AI places {profile.name}" if f == "placed" else f"Where {profile.name} aims to be"
            missing[f] = (f"{where} was not measured: {why}."
                          + (" Set the category again on the claims screen to write them."
                             if f == "aiming" and not questions else ""))
    if left := max_topics() - sum(t.kind == "buyer" for t in topics):
        claims, claim_probes, claim_skipped = blind_probes_from_attributes(
            [a for a in attributes if not placed or a.id != placed.id], profile, left)
        skipped += claim_skipped
        claim_probes = [p for p in claim_probes if p.text.strip().lower() not in seen]
        asked = {p.topic_id for p in claim_probes}
        topics += [t for t in claims if t.id in asked]
        probes += claim_probes
    return topics, probes, skipped, missing


FRONT_PURPOSE = {"placed": "Where AI places you:", "aiming": "Where you aim to be:",
                 "both": "Where AI places you and where you aim to be:"}


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
    if len(buyer) > (cap := max_topics()):
        errors.append(f"{len(buyer)} buyer topics exceeds {cap}")
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
    # exclude_none: a probe with no real-demand grounding hashes exactly as it did before `demand` existed
    base = [p.model_dump(exclude_none=True) for p in probes if p.phase in ("baseline", "control")]
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
        uncertainty = ("whether the absence persists under differently framed unbranded questions"
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
