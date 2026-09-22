"""How to win it back: every kept action points at a page the run read and questions it asked."""
import json

import graph
from agents import win_back
from agents.evaluator_model import ModelEvaluator
from agents.onboarding_model import build_profile
from providers import fixture

PAGE = "https://example.com/demo-source-claim-1"


def run_for(scenario="A"):
    p = fixture.FixtureProvider(scenario)
    return graph.execute(graph.new_run(p.profile, p), p)


def good(**kw):
    return {"attribute_id": "ai_native", "page_url": PAGE, "current_copy": None,
            "rewrite": "Notion AI drafts inside your pages and answers from your own docs.",
            "question_ids": ["mtg-3"], "why": "w", **kw}


def test_fixture_plans_cover_every_target_and_move_no_number():
    for scenario, echo, align in (("A", 30.1, 21.4), ("B", 32.4, 27.9)):
        run = run_for(scenario)
        assert (run.drift.claim_echo, run.drift.alignment) == (echo, align)
        assert {w.attribute_id for w in run.win_back} == {s.attribute_id for s in win_back.targets(run)}
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
    for reason in ("not a claim to win back", "not among the pages read", "not on https://",
                   "marketing language", "over 60 words", "'zz-9' is not an unbranded question",
                   "already recommending you", "second action"):
        assert reason in text


def test_verbatim_current_copy_is_kept():
    run = run_for("A")
    kept, _ = win_back.validate([good(current_copy="Illustrative placeholder for the AI product page")], run)
    assert kept[0].current_copy


def test_live_path_uses_the_evaluator_and_a_failed_call_is_stated():
    run = run_for("A")
    run.mode = "live_api"
    seen = []
    ev = ModelEvaluator(model="m", transport=lambda p, m, t: seen.append(p) or json.dumps({"actions": [good()]}))
    run.win_back, run.win_back_notes = [], []
    win_back.plan(run, type("P", (), {"win_back": lambda self, prompt: ev.win_back(prompt)})())
    assert [w.provenance for w in run.win_back] == ["live_api"]
    assert PAGE in seen[0] and "mtg-3" in seen[0] and "[recommended]" in seen[0]
    assert run.win_back_notes and "No verified action for" in run.win_back_notes[-1]

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
    assert text.count("must be text") == 2 and text.count("must be a list") == 2


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
