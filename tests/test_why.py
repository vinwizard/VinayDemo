"""The why agent (why.py), offline: recorded Amgen reading lists (tests/cassettes) and a fake model
whose answers depend only on what is in the reading list it is handed — so every cause is planted
and the loop must find it, stop on its rule, and stay inside its budget."""
import json
import re
from itertools import count
from pathlib import Path

import pytest

import why
from providers import live
from schemas import Answer, Attribute, CompanyProfile, Evidence, Run, WinBackAction
from scoring import eligible, newcombe, z_for
from schemas import QueryEvaluation

CASSETTES = Path(__file__).parent / "cassettes"
STRENGTHS = json.loads((CASSETTES / "amgen_strengths.json").read_text())
DIFFERENT = json.loads((CASSETTES / "amgen_different.json").read_text())
PILOT = json.loads((CASSETTES / "why_pilot_answers.json").read_text())
RELEASE = "https://www.sec.gov/Archives/edgar/data/318154/000031815426000124/amgn-20260630earningsrelea.htm"
AI_PAGE = "https://www.amgen.com/science/research-and-development-strategy/ai-in-research-and-development"
PROFILE = CompanyProfile(name="Amgen", domain="amgen.com",
                         evidence=[Evidence(id="pg3", url=AI_PAGE, excerpt="We bring R&D, AI and data closer together.",
                                            source_type="page_fetch")])
DEBT = Attribute(id="emergent_debt", label="Debt limits flexibility", discovered=True)
AI = Attribute(id="ai_rd", label="Uses AI and advanced technology in research and development",
               intended_weight=1.0, claim_quotes=["bring R&D, AI and data closer together"], claim_evidence_ids=["pg3"])
REWRITE = ("We use AI and other advanced technologies across R&D to accelerate drug discovery and "
           "clinical development.")


def message(text):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


def read_text(kw) -> str:
    return "\n".join(i["output"] for i in kw["input"] if i.get("type") == "function_call_output")


class Fake:
    """The model under test: live -> the recorded response, off -> `off`, replay -> `says(reading)`."""

    def __init__(self, cassette, says, off="Amgen makes medicines.", live_text=None):
        self.cassette, self.says, self.off_text, self.live_text = cassette, says, off, live_text
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if kw.get("include"):
            if self.live_text is None:
                return self.cassette
            return {**self.cassette, "output": [*[i for i in self.cassette["output"] if i["type"] != "message"],
                                                message(self.live_text)["output"][0]]}
        if not kw.get("tools"):
            return message(self.off_text)
        return message(self.says(read_text(kw)))


def run_with(attribute, win_back=()):
    return Run(id="r1", mode="live_api", profile=PROFILE, attributes=[attribute], win_back=list(win_back))


def investigate(fake, attribute, question, term, **kw):
    return why.start(run_with(attribute, **kw), attribute.id, question, term=term,
                     lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=fake))


# ---------------------------------------------------------------- the reading list
def test_a_replay_hands_back_the_recorded_reading_list_as_the_tools_own_output():
    fake = Fake(STRENGTHS, lambda text: "Amgen.")
    lab = why.Lab("m", transport=fake)
    reading = live.reading_of(STRENGTHS, cap=None)
    lab.replay(STRENGTHS["question"], reading)
    kw = fake.calls[-1]
    assert kw["tool_choice"] == "none" and kw["tools"] == [why.REPLAY_TOOL] and "include" not in kw
    calls = [i for i in kw["input"] if i.get("type") == "function_call"]
    outs = [i for i in kw["input"] if i.get("type") == "function_call_output"]
    assert len(calls) == len(outs) == len(reading)
    assert json.loads(calls[1]["arguments"]) == {"open": RELEASE}
    assert "debt outstanding totaled $57.3 billion" in outs[1]["output"]
    assert kw["input"][:2] == [{"role": "system", "content": live.NEUTRAL_INSTRUCTION},
                               {"role": "user", "content": STRENGTHS["question"]}]


def test_search_off_is_the_neutral_prompt_with_no_tool():
    fake = Fake(STRENGTHS, lambda text: "")
    why.Lab("m", transport=fake).off("What is Amgen?")
    kw = fake.calls[-1]
    assert "tools" not in kw and "web search" not in kw["input"][0]["content"].lower()


def test_dropping_lines_keeps_the_rest_of_the_page():
    reading = live.reading_of(STRENGTHS, cap=None)
    says = why.term_pattern("debt").search
    cut, gone = why.drop_lines(reading, RELEASE, says)
    text = "\n".join(r.text for s in cut for r in s.results if r.url == RELEASE)
    assert "debt" not in text.lower() and "Cash and Cash Equivalents" in text
    assert any("debt outstanding" in g for g in gone) and any(g.startswith("L223: Debt Outstanding") for g in gone)


def test_an_acronym_counts_only_in_capitals_and_whole():
    ai = why.term_pattern("AI")
    assert ai.search("tools like AI, generative biology") and not ai.search("said, Ai, AIM, maintain")
    assert why.term_pattern("debt").search("Debt Outstanding")


# ---------------------------------------------------------------- the loop finds planted causes
def says_debt(text):
    return "Meaningful debt: $57.3 billion." if "debt outstanding" in text.lower() else "Revenue grew 10%."


def test_it_traces_debt_to_the_two_lines_of_the_release():
    fake = Fake(STRENGTHS, says_debt, live_text="Amgen carries meaningful debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert inv.status == "complete" and (inv.live.k, inv.live.n) == (3, 3)
    verdict = inv.verdicts[-1]
    assert verdict.kind == "caused_by" and "sec.gov" in verdict.text
    passage = next(a for a in inv.arms if a.id == verdict.arm_id)
    assert passage.kind == "drop_passage" and passage.urls == [RELEASE] and passage.decided == "effect"
    assert any("debt outstanding" in line for line in passage.text)
    assert passage.interval[1] < 0 and passage.k == 0
    assert all(a.decided != "undecided" for a in inv.arms)
    assert not any(v.kind in ("copy_fix", "authority_fix") for v in inv.verdicts)   # imposed: no fix to test


def test_a_claim_two_pages_each_carry_is_over_determined():
    reading = live.reading_of(STRENGTHS, cap=None)
    two = [u for u in why.urls_of(reading) if "amgen.com/stories/2026/03/2025-letter" in u or u == RELEASE]
    assert len(two) == 2

    def says(text):   # either page alone is enough
        return "Strong cash flow." if "free cash flow" in text or "debt outstanding" in text else "Amgen."
    fake = Fake(STRENGTHS, says, live_text="Strong cash flow.")
    attr = Attribute(id="cash", label="Strong cash flow", discovered=True)
    inv = investigate(fake, attr, STRENGTHS["question"], "cash flow")
    kinds = [v.kind for v in inv.verdicts]
    assert kinds[-1] in ("over_determined", "caused_by")
    group = inv.arms[1]
    assert group.kind == "drop_source" and group.decided == "effect"


def test_what_survives_every_source_removed_is_prior_belief():
    fake = Fake(STRENGTHS, lambda text: "Amgen has debt.", off="Amgen has debt.", live_text="Amgen has debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert inv.off.k == inv.off.n == 3
    assert inv.verdicts[-1].kind == "prior_belief" and "no page edit" in inv.verdicts[-1].text
    assert inv.arms[1].decided == "no_effect"


def test_what_survives_every_source_removed_but_not_search_off_is_not_prior_belief():
    fake = Fake(STRENGTHS, lambda text: "Amgen has debt.", live_text="Amgen has debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert inv.off.k == 0 and inv.arms[1].decided == "no_effect"
    assert inv.verdicts[-1].kind == "not_in_reading" and "no page edit" not in inv.verdicts[-1].text


def test_halves_that_are_only_undecided_are_not_over_determined():
    ticks = {}

    def says(text):   # both pages: every other answer; one: every fourth; neither: never
        held = ("free cash flow" in text) + ("debt outstanding" in text)
        n = next(ticks.setdefault(held, count()))
        return "Strong cash flow." if held and n % (2 if held == 2 else 4) == 0 else "Amgen."
    fake = Fake(STRENGTHS, says, live_text="Strong cash flow.")
    inv = investigate(fake, Attribute(id="cash", label="Strong cash flow", discovered=True),
                      STRENGTHS["question"], "cash flow")
    assert inv.arms[1].decided == "effect"
    assert any(a.decided == "undecided" for a in inv.arms[2:])
    assert inv.verdicts[-1].kind == "undecided"


def test_pages_that_hold_a_claim_back_are_never_called_prior_belief():
    ticks = count()

    def says(text):   # with the pages: every other answer; without them: always
        if "debt outstanding" not in text.lower() or next(ticks) % 2 == 0:
            return "Amgen has debt."
        return "Revenue grew 10%."
    fake = Fake(STRENGTHS, says, off="Amgen has debt.", live_text="Amgen has debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    group = inv.arms[1]
    assert inv.off.k and group.decided == "effect" and group.effect > 0
    assert inv.verdicts[-1].kind == "not_in_reading" and "no page edit" not in inv.verdicts[-1].text


def test_halves_each_decided_without_a_drop_are_over_determined():
    reading = live.reading_of(STRENGTHS, cap=None)
    pages = {r.url for s in reading for r in s.results if "cash flow" in r.text}
    assert len(pages) == 2
    ticks = count()

    def says(text):   # both pages: every other answer; either one alone: always; neither: never
        held = sum(u in text for u in pages)
        return "Strong cash flow." if held == 1 or held == 2 and next(ticks) % 2 == 0 else "Amgen."
    fake = Fake(STRENGTHS, says, live_text="Strong cash flow.")
    inv = investigate(fake, Attribute(id="cash", label="Strong cash flow", discovered=True),
                      STRENGTHS["question"], "cash flow")
    halves = inv.arms[2:]
    assert inv.arms[1].decided == "effect" and all(a.decided == "effect" and a.effect > 0 for a in halves)
    assert inv.verdicts[-1].kind == "over_determined"


def test_a_replay_that_does_not_match_live_stops_before_any_experiment():
    fake = Fake(STRENGTHS, lambda text: "Amgen is growing.", live_text="Amgen has a lot of debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert [v.kind for v in inv.verdicts] == ["not_reproducible"] and len(inv.arms) == 1


# ---------------------------------------------------------------- copy or authority
def ai_model():
    """Says AI on every third ask while the splash page's AI line is read, always once the rewrite
    leads a page, never otherwise."""
    tick = count()

    def says(text):
        if REWRITE in text:
            return "It uses AI across research."
        if "tools like AI" in text:
            return "It uses AI in research." if next(tick) % 3 == 0 else "It is a biotech pioneer."
        return "It is a biotech pioneer."
    return says


def test_the_rewrite_on_a_page_ai_reads_is_a_copy_fix():
    fake = Fake(DIFFERENT, ai_model())
    action = WinBackAction(attribute_id=AI.id, label=AI.label, zone="unstated_intent", page_url=AI_PAGE,
                           rewrite=REWRITE, provenance="live_api")
    inv = investigate(fake, AI, DIFFERENT["question"], "AI", win_back=[action])
    fix = next(v for v in inv.verdicts if v.fix)
    assert fix.kind == "copy_fix" and fix.fix == "copy"
    edit = next(a for a in inv.arms if a.id == fix.arm_id)
    assert edit.kind == "edit" and edit.hypothetical and edit.text == [REWRITE] and edit.interval[0] > 0
    assert "amgen.com" in edit.urls[0]
    inject = next(a for a in inv.arms if a.kind == "inject")
    assert inject.urls == [AI_PAGE] and not inject.hypothetical   # the site's own quote, not new copy
    cause = next(v for v in inv.verdicts if not v.fix)
    assert cause.kind in ("caused_by", "over_determined", "undecided")


def test_copy_that_moves_nothing_is_not_movable():
    fake = Fake(DIFFERENT, lambda text: "It is a biotech pioneer.")
    inv = investigate(fake, AI, DIFFERENT["question"], "AI")
    assert inv.verdicts[-1].kind == "not_movable" and inv.verdicts[-1].fix == "none"
    assert all(a.decided == "no_effect" for a in inv.arms[1:])


def test_a_page_only_injection_moves_is_an_authority_fix():
    fake = Fake(DIFFERENT, lambda text: "It uses AI." if "ai-in-research-and-development" in text else "It is a pioneer.")
    inv = investigate(fake, AI, DIFFERENT["question"], "AI")
    assert inv.verdicts[-1].kind == "authority_fix" and AI_PAGE in inv.arms[-1].urls


# ---------------------------------------------------------------- budget, metering, provenance
def test_it_stops_at_its_budget(monkeypatch):
    monkeypatch.setenv(why.BUDGET_ENV, "0.05")
    fake = Fake(STRENGTHS, says_debt)
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert inv.status == "stopped" and inv.verdicts[-1].kind == "budget" and inv.budget_usd == 0.05
    assert not fake.calls   # refused before the first live call, whose estimate alone is over


def test_spend_is_counted_from_reported_usage():
    fake = Fake(STRENGTHS, says_debt, live_text="Amgen carries meaningful debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    assert 0 < inv.spent_usd <= inv.budget_usd


def test_the_default_calls_go_through_the_metered_path(monkeypatch):
    import access
    sent = []
    monkeypatch.setenv(access.KEY_ENV, "k")
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: sent.append(kw) or message("Amgen."))
    why.Lab("gpt-6-luna").off("What is Amgen?")
    assert sent and sent[0]["model"] == "gpt-6-luna"


def test_an_experiment_answer_never_counts():
    a = Answer(probe_id="np-1", text="x", provenance="counterfactual_replay", search_executed=True)
    e = QueryEvaluation(probe_id="np-1", valid=True, explanation="")
    assert eligible(a, e) == (False, "why-agent experiment (a replayed reading list, not a measurement)")


def test_the_evaluator_judges_when_there_is_no_term():
    class Evaluator:
        model = "judge"

        def label(self, probe, answer, attributes, profile):
            quote = "meaningful debt"
            found = quote in answer.text
            return {"attributes": [{"attribute_id": DEBT.id, "quote": quote, "polarity": "negative"}] if found else [],
                    "mentioned": True, "recommended": False, "negative_mention": False,
                    "competitor_recommendations": [], "evidence_quotes": [], "on_topic": True}
    judge = why.Judge(DEBT, PROFILE, "q", evaluator=Evaluator())
    assert judge("Amgen carries meaningful debt.") == (True, "meaningful debt")
    assert judge("Amgen grew.") == (False, None)


# ---------------------------------------------------------------- recorded answers, re-derived
def rate(texts, term):
    judge = why.Judge(DEBT, PROFILE, "q", term=term)
    got = [judge(t)[0] for t in texts]
    return sum(got), len(got)


def test_the_pilots_debt_arms_re_derive_from_their_recorded_answers():
    base = rate(PILOT["debt"]["base"], "debt")
    cut = rate(PILOT["debt"]["without_the_two_lines"], "debt")
    assert (base, cut) == ((6, 6), (0, 6))
    lo, hi = newcombe(*cut, *base, why.Z)
    assert hi < 0   # decided even under the investigation-wide correction, at six asks


def test_the_pilots_ai_arms_re_derive_and_need_the_last_look():
    base = rate(PILOT["ai"]["base"], "AI")
    fixed = rate(PILOT["ai"]["rewrite_leads_about"], "AI")
    gone = rate(PILOT["ai"]["without_the_ai_pages"], "AI")
    assert (base, fixed, gone) == ((6, 18), (14, 18), (0, 18))
    assert newcombe(*fixed, *base, z_for(0.05))[0] > 0      # decided at a plain 95%, as the pilot reported
    assert newcombe(*fixed, *base, why.Z)[0] < 0           # not yet, corrected: the agent asks to 36


# ---------------------------------------------------------------- found live, 2026-09-28
def test_the_copy_test_edits_a_page_that_does_not_say_it_yet():
    """Live, search returned Amgen's AI page itself: leading it with the rewrite repeated what it
    already said and moved nothing. The copy question is about a page AI reads that is silent."""
    fake = Fake(DIFFERENT, ai_model())
    action = WinBackAction(attribute_id=AI.id, label=AI.label, zone="unstated_intent", page_url=AI_PAGE,
                           rewrite=REWRITE, provenance="live_api")
    inv = investigate(fake, AI, DIFFERENT["question"], "AI", win_back=[action])
    edit = next(a for a in inv.arms if a.kind == "edit")
    said = why.term_pattern("AI")
    assert not any(said.search(r.text) for s in inv.reading for r in s.results if r.url == edit.urls[0])


def test_whether_ai_says_it_is_decided_on_the_second_looks_asks():
    """Live, the base read 0 of 6 and 12 of 36 once topped up: a claim said a third of the time
    must still get its cause searched."""
    tick = count()
    fake = Fake(DIFFERENT, lambda text: "It uses AI." if "tools like AI" in text and next(tick) % 7 == 6
                else "It is a biotech pioneer.")
    inv = investigate(fake, AI, DIFFERENT["question"], "AI")
    assert inv.arms[0].n >= why.LOOKS[1] and any(a.kind == "drop_source" for a in inv.arms)


def test_each_experiment_keeps_the_base_it_was_decided_against():
    fake = Fake(STRENGTHS, says_debt, live_text="Amgen carries meaningful debt.")
    inv = investigate(fake, DEBT, STRENGTHS["question"], "debt")
    for a in inv.arms[1:]:
        assert a.base_n and a.effect == round(a.k / a.n - a.base_k / a.base_n, 2)
    passage = next(a for a in inv.arms if a.id == inv.verdicts[-1].arm_id)
    assert f"from {passage.base_k}/{passage.base_n} to {passage.k}/{passage.n}" in inv.verdicts[-1].text


def test_a_page_that_does_not_state_the_claim_is_never_injected_as_its_copy():
    unstated = AI.model_copy(update=dict(claim_evidence_ids=[]))
    fake = Fake(DIFFERENT, lambda text: "It uses AI." if "ai-in-research-and-development" in text else "It is a pioneer.")
    inv = investigate(fake, unstated, DIFFERENT["question"], "AI")
    assert not any(a.kind == "inject" for a in inv.arms)
    assert not any(v.kind == "authority_fix" for v in inv.verdicts)
    action = WinBackAction(attribute_id=AI.id, label=AI.label, zone="unstated_intent", page_url=AI_PAGE,
                           rewrite=REWRITE, provenance="live_api")
    inv = investigate(Fake(DIFFERENT, lambda text: "It is a pioneer."), unstated, DIFFERENT["question"], "AI",
                      win_back=[action])
    inject = next(a for a in inv.arms if a.kind == "inject")
    assert inject.urls == [AI_PAGE] and inject.hypothetical and inject.text == [REWRITE]


def test_a_rewrite_injected_on_an_unread_page_needs_the_rewrite_and_authority():
    unstated = AI.model_copy(update=dict(claim_evidence_ids=[]))
    action = WinBackAction(attribute_id=AI.id, label=AI.label, zone="unstated_intent", page_url=AI_PAGE,
                           rewrite=REWRITE, provenance="live_api")
    fake = Fake(DIFFERENT, lambda text: "It uses AI." if REWRITE in text and "ai-in-research-and-development" in text
                else "It is a pioneer.")
    inv = investigate(fake, unstated, DIFFERENT["question"], "AI", win_back=[action])
    fix = inv.verdicts[-1]
    assert fix.kind == "authority_fix" and next(a for a in inv.arms if a.id == fix.arm_id).hypothetical
    assert "your rewrite" in fix.text and "not rewriting it" not in fix.text


# ---------------------------------------------------------------- media-library files are not pages
MEDIA = ("https://www-ext.amgen.com/-/media/Themes/CorporateAffairs/amgen-com/amgen-com/downloads/"
         "fact-sheets/fact_sheet_amgen.ashx?la=en")


def with_media_first(cassette, text):
    """The cassette with an Amgen media-library file read first: a live answer on 2026-09-28 had its
    rewrite put on exactly such a file."""
    out, done = [], False
    for item in cassette["output"]:
        if item["type"] == "web_search_call" and not done:
            item = {**item, "results": [{"type": "text_result", "url": MEDIA, "title": "Fact sheet",
                                         "snippet": text}, *item["results"]]}
            done = True
        out.append(item)
    return {**cassette, "output": out}


def test_asset_files_are_documents_not_pages():
    assert why.is_asset(MEDIA) and why.is_asset("https://investors.amgen.com/static-files/06d47b6a")
    assert why.is_asset("https://www.amgen.com/stories/2026/03/-/media/x/2025-annual-report.pdf")
    assert not why.is_asset("https://www.amgen.com/about")
    assert not why.is_asset(AI_PAGE)
    assert why.page_name(MEDIA) == "the www-ext.amgen.com document fact_sheet_amgen.ashx"
    assert why.count_pages([MEDIA, AI_PAGE, "https://www.amgen.com/about"]) == "2 pages and 1 document"


def test_a_media_file_is_never_the_rewrite_target_or_the_added_page():
    cassette = with_media_first(DIFFERENT, "Amgen is a biotechnology company.")   # silent, own domain, first
    fake = Fake(cassette, ai_model())
    media_action = WinBackAction(attribute_id=AI.id, label=AI.label, zone="unstated_intent", page_url=MEDIA,
                                 rewrite=REWRITE, provenance="live_api")
    inv = investigate(fake, AI, cassette["question"], "AI", win_back=[media_action])
    assert MEDIA in why.urls_of(inv.reading)
    for arm in inv.arms:
        if arm.kind in ("edit", "inject"):
            assert not any(why.is_asset(u) for u in arm.urls), arm.label


def test_a_media_file_can_still_be_the_cause_and_is_called_a_document():
    cassette = with_media_first(STRENGTHS, "Debt outstanding totaled $57.3 billion.")
    fake = Fake(cassette, lambda text: "Meaningful debt." if "debt outstanding" in text.lower() else "Revenue grew.",
                live_text="Amgen carries meaningful debt.")
    inv = investigate(fake, DEBT, cassette["question"], "debt")
    group = inv.arms[1]
    assert MEDIA in group.urls and "document" in group.label and group.decided == "effect"
