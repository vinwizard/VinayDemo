"""How to win it back: every kept action points at a page the run read and questions it asked."""
import json

from agents import win_back
from agents.evaluator_model import ModelEvaluator
from agents.onboarding_model import build_profile
from fakes import replay as run_for

PAGE = "https://example.com/demo-source-claim-1"


MTG3 = "Which meeting notes tool can transcribe and summarize calls without adding a separate bot to every meeting?"


def good(**kw):
    return {"attribute_id": "ai_native", "page_url": PAGE, "current_copy": None, "heading": MTG3,
            "rewrite": "Notion AI drafts inside your pages and answers from your own docs.",
            "question_ids": ["mtg-3"], "why": "w", **kw}


def test_fixture_plans_cover_every_target_and_move_no_number():
    for scenario, echo, align in (("A", 30.1, 21.4), ("B", 32.4, 27.9)):
        run = run_for(scenario)
        assert (run.drift.claim_echo, run.drift.alignment) == (echo, align)
        assert {w.attribute_id for w in run.win_back} == {s.attribute_id for s in win_back.targets(run)}
        # an authored fix that targets no question is kept, never also listed as unconfirmed
        assert run.win_back_notes == []
        assert all(w.provenance == "synthetic" for w in run.win_back)


def test_the_plan_follows_the_scenario():
    a, b = run_for("A"), run_for("B")
    assert "replaces_stack" in {w.attribute_id for w in a.win_back}
    assert "connected_docs" in {w.attribute_id for w in b.win_back}


def test_unverifiable_actions_are_dropped_with_a_reason():
    run = run_for("A")
    kept, dropped = win_back.validate([
        good(attribute_id="connected_docs"),                   # landed, not a target
        good(page_url="https://evil.example/page"),            # never read
        good(current_copy="words that are not on the page"),   # not verbatim
        good(rewrite="A seamless, powerful workspace."),       # marketing language
        good(rewrite=" ".join(["word"] * 61)),                 # too long
        good(question_ids=["zz-9", "kb-1", "mtg-3"]),          # unknown; already recommended; ok
        good(),                                                # duplicate of the one above
    ], run)
    assert [(k.attribute_id, k.question_ids) for k in kept] == [("ai_native", ["mtg-3"])]
    text = " | ".join(dropped)
    for reason in ("not one of this run's claims with room to grow", "a page we did not read",
                   "is not on https://", "marketing words", "longer than 60 words",
                   "cited zz-9, which is not an unbranded question", "already recommending you",
                   "a second suggestion"):
        assert reason in text


def test_a_fix_citing_no_question_cites_the_claims_own_unrecommended_questions():
    # Amgen on gpt-6-luna, 22 Sep 2026: all three kept fixes had question_ids [], because none of the
    # claims had been asked about. Each claim now has questions of its own (ana.blind_probes_for_fronts)
    # and a fix is for them.
    from schemas import Probe, QueryEvaluation
    run = run_for("A")
    run.probes.append(Probe(id="ai_native-b1", topic_id="pos-ai_native", kind="blind", phase="baseline",
                            purpose="p", text="Which workspace drafts documents with AI?"))
    run.evaluations.append(QueryEvaluation(probe_id="ai_native-b1", valid=True, strength=0, explanation="x"))
    kept, dropped = win_back.validate([good(question_ids=[], heading="Which workspace drafts documents with AI?")], run)
    assert kept[0].question_ids == ["ai_native-b1"] and not dropped
    assert "its own buyer questions: ai_native-b1" in win_back.build_prompt(run)


def test_verbatim_current_copy_is_kept():
    run = run_for("A")
    kept, _ = win_back.validate([good(current_copy="Illustrative placeholder for the AI product page")], run)
    assert kept[0].current_copy and kept[0].heading == MTG3


def test_live_path_uses_the_evaluator_and_a_failed_call_is_stated():
    run = run_for("A")
    run.mode = "live_api"
    seen = []
    ev = ModelEvaluator(model="m", transport=lambda p, m, t: seen.append(p) or json.dumps({"actions": [good()]}))
    run.win_back, run.win_back_notes = [], []
    win_back.plan(run, type("P", (), {"win_back": lambda self, prompt: ev.win_back(prompt)})())
    assert [w.provenance for w in run.win_back] == ["live_api"]
    assert PAGE in seen[0] and "mtg-3" in seen[0] and "[recommended]" in seen[0]
    assert run.win_back_notes and "No suggested fix passed our checks for" in run.win_back_notes[-1]

    bad = ModelEvaluator(model="m", transport=lambda *_: "no json")
    run.win_back, run.win_back_notes = [], []
    win_back.plan(run, type("P", (), {"win_back": lambda self, prompt: bad.win_back(prompt)})())
    assert run.win_back == [] and "failed" in run.win_back_notes[0]


def test_malformed_field_types_are_dropped_not_crashing():
    run = run_for("A")
    kept, dropped = win_back.validate([
        good(attribute_id=["ai_native"]),
        good(page_url={"u": 1}),
        good(question_ids="mtg-3"),
        good(question_ids=3),
    ], run)
    assert kept == []
    text = " | ".join(dropped)
    assert text.count("did not say which claim or page") == 2 and text.count("list of questions was malformed") == 2


def test_a_real_sentence_late_on_the_page_and_with_a_dash_can_be_replaced():
    # amgen.com, 22 Sep 2026: "…at Amgen—and it goes beyond…" sits ~5,800 characters into the
    # homepage. The prompt showed it as "Amgen—and" (json.dumps escapes by default), the model
    # copied that, and the check read only the page's first 1,200 characters: a sentence that IS on
    # the page was dropped as "not on the page", however it was copied.
    url = "https://www.amgen.com/"
    sentence = ("Making a positive difference in the world is at the heart of what we do at Amgen"
                "—and it goes beyond making vital medicines.")
    page = "Our medicines and pipeline. " * 200 + sentence
    run = run_for("A")
    run.profile.evidence = build_profile({"name": "Amgen"}, [(url, page)], "amgen.com").evidence
    target = win_back.targets(run)[0].attribute_id
    next(a for a in run.attributes if a.id == target).claim_quotes = [sentence]
    prompt = win_back.build_prompt(run)
    assert sentence in prompt and "\\u2014" not in prompt
    kept, dropped = win_back.validate([good(attribute_id=target, page_url=url, current_copy=sentence)], run)
    assert [k.current_copy for k in kept] == [sentence], dropped


# ---------------------------------------------------------------- question-headed rewrites
# Amgen on gpt-6-luna, 28 Sep 2026: all three suggested rewrites rephrased the sentence already on
# amgen.com/about. The biologics one kept 11 of its words and added 5; two of the three matched their
# buyer questions worse than the copy they replaced (retrieval scores 0.56 -> 0.53, 0.50 -> 0.44).
AMGEN_COPY = "Many of Amgen's medicines are made through a highly complex process involving living cells."
AMGEN_REWRITE = ("Amgen develops and manufactures biologic medicines using living cells. Many of Amgen's "
                 "medicines are made through this highly complex process.")


def test_a_rewrite_that_repeats_the_copy_it_replaces_is_dropped():
    assert win_back.repeated(AMGEN_REWRITE, AMGEN_COPY) > win_back.MAX_REPEATED
    run = run_for("A")
    copy = "Illustrative placeholder for the AI product page"
    kept, dropped = win_back.validate([good(current_copy=copy, rewrite=copy + " with drafts.")], run)
    assert kept == [] and "repeats most of the words of the sentence it replaces" in dropped[0]


def test_a_rewrite_must_say_why_it_should_work():
    kept, dropped = win_back.validate([good(why="  ")], run_for("A"))
    assert kept == [] and "did not say why it should make AI name Notion" in dropped[0]


def test_the_heading_is_one_of_the_buyer_questions_it_answers():
    run = run_for("A")
    for heading, reason in ((None, "no buyer question heading it"),
                            ("How does Notion summarise meetings?", "is not one of the buyer questions it cites")):
        kept, dropped = win_back.validate([good(heading=heading)], run)
        assert kept == [] and reason in dropped[0]
    # copied with different case and spacing, it is that question, and the passage is for it
    kept, dropped = win_back.validate([good(heading="  which meeting notes tool CAN transcribe and summarize calls "
                                                    "without adding a separate bot to every meeting ", question_ids=[])], run)
    assert kept[0].heading == MTG3 and kept[0].question_ids == ["mtg-3"] and not dropped


def test_a_heading_that_copies_a_question_already_won_or_excluded_is_dropped():
    run = run_for("A")
    kb1 = next(p.text for p in run.probes if p.id == "kb-1")
    assert win_back.verdicts(run)["kb-1"] == "recommended"
    kept, dropped = win_back.validate([good(heading=kb1, question_ids=[])], run)
    assert kept == [] and "AI already recommends Notion for" in dropped[0]
    next(e for e in run.evaluations if e.probe_id == "mtg-3").valid = False
    kept, dropped = win_back.validate([good()], run)
    assert kept == [] and "excluded from the scores" in dropped[0]


def test_a_heading_of_its_own_is_held_to_the_buyer_question_rules():
    run = run_for("A")
    own = dict(attribute_id="enterprise", question_ids=[])
    for heading, reason in (("Notion SSO and audit logs", "not a question a buyer would ask"),
                            ("Does Notion offer SAML single sign-on?", "names Notion or addresses the vendor"),
                            ("Does your platform offer SAML single sign-on?", "names Notion or addresses the vendor")):
        kept, dropped = win_back.validate([good(heading=heading, **own)], run)
        assert kept == [] and reason in dropped[0], heading
    kept, _ = win_back.validate([good(heading="Which workspace tools offer SAML single sign-on?", **own)], run)
    assert kept[0].heading == "Which workspace tools offer SAML single sign-on?"


def test_the_passage_is_the_heading_then_its_answer_wherever_it_is_tested():
    run = run_for("A")
    action = next(w for w in run.win_back if w.attribute_id == "ai_native")
    assert action.passage() == f"{MTG3}\n{action.rewrite}"
    assert "heading" in win_back.build_prompt(run) and "Not a rephrasing" in win_back.build_prompt(run)
