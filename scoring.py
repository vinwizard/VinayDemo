"""Deterministic arithmetic (.claude/skills/evaluation-and-scoring). No model judgment lives here."""
import random
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlparse

from schemas import Answer, QueryEvaluation, Topic, TopicEvaluation

FIT_WEIGHT = {"strong": 1.0, "partial": 0.5, "unsupported": 0.0}
PRIORITY_LABEL = "heuristic investigation priority"


def domain_matches(url: str, domains: list[str]) -> bool:
    """Exact host or dot-delimited subdomain match; never substring."""
    host = (urlparse(url if "://" in url else "//" + url).hostname or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in (d.lower().strip(".") for d in domains))


def mentions_alias(text: str, aliases: list[str]) -> bool:
    """Case-sensitive, word-bounded: 'the notion of' is not a brand mention."""
    return any(re.search(rf"(?<![\w.]){re.escape(a)}(?![\w])", text) for a in aliases)


def visibility_score(strengths: list[int]) -> Optional[float]:
    return None if not strengths else round(100 * sum(strengths) / (2 * len(strengths)), 1)


def visibility_by_question(per_question: list[list[int]]) -> Optional[float]:
    """Buyer visibility: the mean over QUESTIONS, each question worth the mean of its own tries.

    Questions carry equal weight however many times they were asked, so re-asking a sample of them
    (providers/live.REPEAT_SAMPLE) sharpens the wobble estimate without giving those questions
    three votes. A question with no eligible answer is left out rather than counted as zero.
    """
    values = [sum(q) / len(q) for q in per_question if q]
    return None if not values else round(100 * sum(values) / (2 * len(values)), 1)


def visibility_over_tries(per_try: list[list[int]]) -> tuple[Optional[float], Optional[list[float]]]:
    """-> (mean of the per-try visibility scores, [lowest, highest]). A try with no eligible answer
    has no score and is left out rather than counted as zero; one try is its own mean and range.

    Used for the wobble: the same questions re-asked, scored try by try.
    """
    scores = [v for v in map(visibility_score, per_try) if v is not None]
    if not scores:
        return None, None
    return round(sum(scores) / len(scores), 1), [min(scores), max(scores)]


# Bootstrap 95% intervals, with a fixed seed so the same saved answers always give the same interval.
BOOT_RESAMPLES, BOOT_SEED = 2000, 7
MIN_INTERVAL_ANSWERS = 5  # fewer eligible brand answers, or scored buyer questions, than this: no interval


def interval(draws: list[float]) -> list[float]:
    """The middle 95% of the bootstrap draws, as [low, high]."""
    xs = sorted(draws)
    return [round(xs[int(0.025 * len(xs))], 1), round(xs[int(0.975 * len(xs)) - 1], 1)]


def visibility_draws(per_question: list[list[int]], key: str = "") -> Optional[list[float]]:
    """Bootstrap draws of visibility: resample the questions, then each chosen question's tries.

    per_question: one list per buyer question of its tries' strengths. Drawn exactly as
    `visibility_by_question` scores, so a question re-asked three times still counts once — the
    interval is dominated by how much DIFFERENT questions disagree, which is where the width
    actually comes from. None when no question has a second try (one try shows nothing of how
    answers vary between asks) or fewer than MIN_INTERVAL_ANSWERS questions were scored. `key`
    seeds each set apart, so two fronts are resampled independently.
    """
    qs = [q for q in per_question if q]
    if len(qs) < MIN_INTERVAL_ANSWERS or max(map(len, qs)) < 2:
        return None
    rng = random.Random(f"{BOOT_SEED}:{key}")
    out = []
    for _ in range(BOOT_RESAMPLES):
        picked = [rng.choice(qs) for _ in qs]
        out.append(visibility_by_question([[rng.choice(q) for _ in q] for q in picked]))
    return out


def gap_verdict(a: list[float], b: list[float]) -> Optional[tuple[list[float], bool]]:
    """-> (95% interval of a minus b, draw by draw; whether it excludes 0: a real gap), or None when
    either side's interval has zero width: answers that never varied cannot say how sure the gap is."""
    if any(lo == hi for lo, hi in (interval(a), interval(b))):
        return None
    lo, hi = interval([x - y for x, y in zip(a, b)])
    return [lo, hi], lo > 0 or hi < 0


def echo_draws(kept: list[str], weights: dict[str, float],
               endorsed: dict[str, set[str]]) -> Optional[list[float]]:
    """Bootstrap draws of a weighted echo score (claim echo, alignment), resampling brand answers.

    kept: eligible brand answer ids; weights: attribute id -> its weight in the score; endorsed:
    answer id -> the attributes it endorsed. None below MIN_INTERVAL_ANSWERS or with no weight.
    """
    total = sum(weights.values())
    if len(kept) < MIN_INTERVAL_ANSWERS or not total:
        return None
    rng = random.Random(f"{BOOT_SEED}:echo")
    out = []
    for _ in range(BOOT_RESAMPLES):
        picked = [rng.choice(kept) for _ in kept]
        out.append(100 * sum(w * sum(a in endorsed.get(p, ()) for p in picked)
                             for a, w in weights.items()) / (total * len(picked)))
    return out


MIN_CONTROL_VENDORS = 2  # a control answer naming fewer companies than this does not know the category


def low_confidence(brand: str, category: str, control: Optional[QueryEvaluation],
                   control_answer: Optional[Answer]) -> Optional[str]:
    """Why a set's buyer visibility is not to be trusted, or None.

    The set's control question ("Which companies lead in <category>?") decides it, whatever
    the buyer answers scored — a brand named once by chance is still not known in the category:
      * the control could not be scored          -> low confidence: nothing to check the number against
      * it names fewer than MIN_CONTROL_VENDORS  -> low confidence: the model does not know the category
      * it names companies but not the brand     -> low confidence: the model does not count the brand
                                                    among the category's leaders, so buyer questions
                                                    were unlikely to surface it
      * it names the brand                       -> None: the model knows the brand as a leader, so
                                                    the buyer number is a finding
    """
    if control is None or control_answer is None or not eligible(control_answer, control)[0]:
        why = control.explanation if control else "the control question was not answered"
        return (f"The control question on {category} could not be scored ({why}), so this number "
                f"cannot be checked against what the answering model knows about the category.")
    vendors = control.competitor_recommendations
    if len(vendors) < MIN_CONTROL_VENDORS:
        found = f"only {', '.join(vendors)}" if vendors else "no company at all"
        return (f"Asked which companies lead in {category}, the answering model named {found}. It "
                f"does not seem to know this category, so this number says more about the model "
                f"than about {brand}.")
    if not control.mentioned:
        return (f"Asked which companies lead in {category}, the answering model named "
                f"{', '.join(vendors[:5])} but not {brand}. It does not count {brand} among this "
                f"category's leaders, so unbranded questions were unlikely to surface it: low confidence, "
                f"not a finding about how buyers see {brand}.")
    return None


def eligible(answer: Answer, ev: QueryEvaluation) -> tuple[bool, Optional[str]]:
    if answer.provenance == "web_research_snapshot":
        return False, "search snapshot (not a chatbot observation)"
    if answer.status != "ok":
        return False, answer.status
    if answer.provenance == "live_api" and not answer.search_executed:
        return False, "ungrounded (no search executed)"
    if not ev.valid:
        return False, "needs review"
    return True, None


def rate(k: int, n: int) -> Optional[float]:
    return None if n == 0 else round(k / n, 3)


def score_topic(topic: Topic, phase: str, answers: list[Answer], evals: list[QueryEvaluation]) -> TopicEvaluation:
    """answers/evals: same order, already filtered to this topic + phase + one provenance."""
    provenance = answers[0].provenance if answers else "synthetic"
    assert all(a.provenance == provenance for a in answers), "never pool provenance types"
    kept, reasons = [], []
    for a, e in zip(answers, evals):
        ok, why = eligible(a, e)
        kept.append(e) if ok else reasons.append(f"{a.probe_id}: {why}")
    n = len(kept)
    rec = sum(e.recommended for e in kept)
    comp = sum(bool(e.competitor_recommendations) and not e.mentioned for e in kept)
    te = TopicEvaluation(
        topic_id=topic.id, phase=phase, provenance=provenance, n=n, excluded=len(reasons), excluded_reasons=reasons,
        mentions=sum(e.mentioned for e in kept), recommendations=rec,
        owned_citations=sum(e.owned_citation for e in kept), competitor_answers=comp,
        mention_rate=rate(sum(e.mentioned for e in kept), n), recommendation_rate=rate(rec, n),
        citation_rate=rate(sum(e.owned_citation for e in kept), n),
        visibility_score=visibility_score([e.strength for e in kept]), competitor_rate=rate(comp, n),
        # A competitor is whoever AI names in a buyer answer that never names the brand: a name beside
        # the brand is alongside it — often a tool it integrates with — not instead of it.
        status="", top_competitors=[c for c, _ in Counter(c for e in kept if not e.mentioned
                                                          for c in e.competitor_recommendations).most_common(4)],
        limitations=["Small sample: at most three baseline questions per topic."],
    )
    if provenance == "synthetic":
        te.limitations.append("Simulated score from sample answers; not a chatbot measurement.")
    if n < 3:
        te.status = "insufficient evidence"
        te.limitations.append(f"Only {n} eligible observation(s); priority ranking omitted.")
        return te
    te.gap_priority = round(100 * FIT_WEIGHT[topic.fit] * (1 - rec / n) * (comp / n), 1)
    if n == 3 and rec == 3:
        te.status = "observed presence"
    elif n == 3 and rec in (1, 2):
        te.status = "mixed"
    elif n == 3 and rec == 0 and topic.fit == "strong" and comp >= 2:
        te.status = "candidate gap"
    else:
        te.status = "unclear"
    return te


if __name__ == "__main__":
    assert visibility_score([2, 1, 0]) == 50.0 and visibility_score([]) is None
    assert visibility_over_tries([[2, 0], [0, 0], [1, 0]]) == (25.0, [0.0, 50.0])
    assert visibility_by_question([[2, 2, 2], [0], [1]]) == 50.0   # one vote per question
    assert visibility_by_question([[1], []]) == 50.0 and visibility_by_question([]) is None
    assert domain_matches("https://help.notion.com/x", ["notion.com"])
    assert not domain_matches("https://notion.com.evil.net", ["notion.com"])
    assert not domain_matches("https://mynotion.com", ["notion.com"])
    assert not mentions_alias("the notion of a second brain", ["Notion"])
    print("ok")
