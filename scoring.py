"""Deterministic arithmetic (.claude/skills/evaluation-and-scoring). No model judgment lives here."""
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


def visibility_over_tries(per_try: list[list[int]]) -> tuple[Optional[float], Optional[list[float]]]:
    """-> (mean of the per-try visibility scores, [lowest, highest]). A try with no eligible answer
    has no score and is left out rather than counted as zero; one try is its own mean and range."""
    scores = [v for v in map(visibility_score, per_try) if v is not None]
    if not scores:
        return None, None
    return round(sum(scores) / len(scores), 1), [min(scores), max(scores)]


MIN_CONTROL_VENDORS = 2  # a control answer naming fewer tools than this does not know the category


def low_confidence(brand: str, category: str, control: Optional[QueryEvaluation],
                   control_answer: Optional[Answer]) -> Optional[str]:
    """Why a buyer visibility in which the brand was never named is not to be trusted, or None.

    Only asked of a run where no buyer answer, on any try, named the brand. The control question
    ("What are the leading tools for <category>?") then decides what that 0 means:
      * the control could not be scored          -> low confidence: nothing to check the 0 against
      * it names fewer than MIN_CONTROL_VENDORS  -> low confidence: the model does not know the category
      * it names tools but not the brand         -> low confidence: the model does not count the brand
                                                    among the category's leaders, so buyer questions
                                                    were never going to surface it
      * it names the brand                       -> None: the model knows the brand as a leader and
                                                    still does not bring it up for buyers; a real 0
    """
    if control is None or control_answer is None or not eligible(control_answer, control)[0]:
        why = control.explanation if control else "the control question was not answered"
        return (f"The control question on {category} could not be scored ({why}), so this 0 cannot "
                f"be checked against what the answering model knows about the category.")
    vendors = control.competitor_recommendations
    if len(vendors) < MIN_CONTROL_VENDORS:
        found = f"only {', '.join(vendors)}" if vendors else "no tool at all"
        return (f"Asked for the leading tools for {category}, the answering model named {found}. It "
                f"does not seem to know this category, so this 0 says more about the model than "
                f"about {brand}.")
    if not control.mentioned:
        return (f"Asked for the leading tools for {category}, the answering model named "
                f"{', '.join(vendors[:5])} but not {brand}. It does not count {brand} among this "
                f"category's leaders, so buyer questions were unlikely to surface it: low confidence, "
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
    assert domain_matches("https://help.notion.com/x", ["notion.com"])
    assert not domain_matches("https://notion.com.evil.net", ["notion.com"])
    assert not domain_matches("https://mynotion.com", ["notion.com"])
    assert not mentions_alias("the notion of a second brain", ["Notion"])
    print("ok")
