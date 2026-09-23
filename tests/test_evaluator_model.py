"""The model-backed evaluator's input framing and quote repair. No key, no network."""
import json

from agents.evaluator_model import ModelEvaluator, answer_lines, build_prompt, repair_quotes
from schemas import Answer, Attribute, CompanyProfile, Probe

TEXT = ("**Linear** is a fast issue tracker. ([linear.app](https://linear.app/?utm_source=openai))\n\n"
        "[Linear review: the best tracker](https://example.com/review?utm_source=openai)\n"
        "- **Speed:** Its interface opens issues instantly. Teams also use Jira.")
PROFILE = CompanyProfile(name="Linear", domain="linear.app", aliases=["Linear"])
PROBE = Probe(id="np-1", topic_id="perception", text="What is Linear?", kind="named", phase="baseline",
              purpose="p")
ANSWER = Answer(probe_id="np-1", text=TEXT, provenance="live_api", provider="openai", model="m",
                collected_at="2026-09-20T00:00:00", search_executed=True)
ATTRS = [Attribute(id="speed", label="Fast by design",
                   description="Linear opens issues instantly and is keyboard-first.")]


def labels(**over):
    return {"mentioned": True, "recommended": False, "negative_mention": False,
            "competitor_recommendations": [], "evidence_quotes": [], "on_topic": True,
            "outdated_claim_quote": None, "attributes": [], **over}


def test_every_line_is_verbatim_and_no_citation_or_bold_survives():
    lines = answer_lines(TEXT)
    assert lines and all(x in TEXT for x in lines)
    joined = "\n".join(lines)
    assert "http" not in joined and "**" not in joined and "best tracker" not in joined
    assert "Its interface opens issues instantly." in lines


def test_prompt_carries_the_claim_statement_and_not_the_citations():
    prompt = build_prompt(PROBE, ANSWER, ATTRS, PROFILE)
    assert "Linear opens issues instantly and is keyboard-first." in prompt
    assert "utm_source" not in prompt and "best tracker" not in prompt


def test_a_near_miss_quote_is_replaced_by_an_exact_copy():
    asked = []
    def ask(prompt):
        asked.append(prompt)
        return json.dumps({"fixed": {"its interface opens issues instantly":
                                     "Its interface opens issues instantly"}})
    got = repair_quotes(labels(attributes=[{"attribute_id": "speed", "polarity": "positive",
                                            "quote": "its interface opens issues instantly"}]), TEXT, ask)
    assert got["attributes"][0]["quote"] == "Its interface opens issues instantly"
    assert "Its interface opens issues instantly." in asked[0]   # shown the one line it came from


def test_an_invented_quote_is_never_offered_for_repair():
    def ask(prompt):
        raise AssertionError("an invention must not get a second chance")
    got = repair_quotes(labels(evidence_quotes=["Linear is loved by every Fortune 500 company"]), TEXT, ask)
    assert got["evidence_quotes"] == ["Linear is loved by every Fortune 500 company"]  # left to fail


def test_a_repair_that_is_still_not_verbatim_changes_nothing():
    bad = "linear is a fast issue tracker"
    got = repair_quotes(labels(evidence_quotes=[bad]), TEXT,
                        lambda _: json.dumps({"fixed": {bad: "Linear is a really fast issue tracker"}}))
    assert got["evidence_quotes"] == [bad]


def test_evaluator_runs_the_repair_round_once():
    slip = "its interface opens issues instantly"
    replies = [json.dumps(labels(evidence_quotes=[slip])),
               json.dumps({"fixed": {slip: "Its interface opens issues instantly"}})]
    ev = ModelEvaluator(model="test", transport=lambda *_: replies.pop(0))
    got = ev.label(PROBE, ANSWER, ATTRS, PROFILE)
    assert got["evidence_quotes"] == ["Its interface opens issues instantly"] and ev.calls == 2


def test_a_repair_cannot_swap_in_a_different_span_or_a_blank():
    slip = "its interface opens issues instantly"
    for bad_fix in ["Teams also use Jira", "interface opens issues", "", "   "]:   # verbatim, wrong words
        got = repair_quotes(labels(evidence_quotes=[slip]), TEXT,
                            lambda _: json.dumps({"fixed": {slip: bad_fix}}))
        assert got["evidence_quotes"] == [slip]


def test_a_repair_may_bring_the_rest_of_the_line():
    """gpt-4o-mini answers a repair with the whole line; the original words are all in it, in order."""
    slip = "its interface opens issues instantly"
    got = repair_quotes(labels(evidence_quotes=[slip]), TEXT,
                        lambda _: json.dumps({"fixed": {slip: "Its interface opens issues instantly."}}))
    assert got["evidence_quotes"] == ["Its interface opens issues instantly."]


def test_the_repair_prompt_shows_a_dash_as_a_dash():
    # json.dumps escapes by default: a line with "—" reached the model as "—", and a copy of
    # that could never be verbatim in the answer.
    text = "Linear—the issue tracker—opens issues instantly."
    asked = []
    repair_quotes(labels(evidence_quotes=["linear—the issue tracker"]), text,
                  lambda prompt: asked.append(prompt) or "{}")
    assert "Linear—the issue tracker—opens" in asked[0] and "\\u2014" not in asked[0]


def test_rivals_asked_for_are_companies_named_in_the_answer():
    # With "other products … the product NAME only", a drugmaker's rivals were drugs (Yescarta,
    # Kymriah) beside companies (AbbVie, Novartis). Re-judged asking for companies, the drug names
    # went and "Regeneron, Sanofi, Novo Nordisk" came back.
    prompt = build_prompt(PROBE, ANSWER, ATTRS, PROFILE)
    assert "other COMPANIES the answer recommends" in prompt and "other products" not in prompt
    assert "if the lines never name that company, leave it" in prompt
