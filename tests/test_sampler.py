"""Sampler-lite (sampler.py) and category sharing (sharing.py), offline: injected transports and a
judge that labels what the answer says."""
import random
from collections import Counter

import access
from fakes import CAT_QS, CATEGORY, Judge, openai_reply
import graph
import reports
import sampler
import sharing
from agents import ana
from providers import fixture, live
from scoring import wilson, z_for

F = fixture.FixtureProvider("A")


def measure(monkeypatch, says, margin="33", profile=None, share=None, budget=None):
    """One live run on the category front only. says(question, ask number) -> answer text."""
    monkeypatch.setenv(sampler.MARGIN_ENV, margin)
    if budget:
        monkeypatch.setenv(sampler.BUDGET_ENV, budget)
    asked = Counter()
    profile = profile or F.profile.model_copy(update=dict(core_category=CATEGORY, category_questions=CAT_QS))

    def transport(messages, model, timeout):
        q = messages[-1]["content"]
        asked[q] += 1
        text = ("Linear, Coda and Notion lead." if q.startswith("Which companies lead in")
                else says(q, asked[q]) if q in CAT_QS else "A workspace tool.")
        return openai_reply(text, searched=True, usage={"input_tokens": 1000, "output_tokens": 100})

    # no claims fill-in: only the front is sampled, so the counts below are the front's own
    prov = live.LiveProvider([a.model_copy(update=dict(buyer_questions=[])) for a in F.attributes()],
                             F.named_probes(), profile=profile, model="gpt-6-luna", transport=transport,
                             evaluator=Judge(rivals=("Linear", "Coda")), share=share)
    prov.concurrency = 1
    return graph.execute(graph.new_run(profile, prov, mode="live_api"), prov), asked, prov


def test_the_looks_are_the_design_reviews():
    assert sampler.looks(20) == (10, 23) and sampler.looks(15) == (16, 43)
    assert sampler.looks(33) == (4, 6)


def test_a_front_ai_never_names_you_in_stops_at_look_1(monkeypatch):
    run, asked, _ = measure(monkeypatch, lambda q, n: "Coda fits.")
    [f] = run.sampler.fronts
    assert (f.pool, f.asked, f.look, f.stopped_early, f.margin_met) == (6, 4, 1, True, True)
    assert (f.named, f.judged, f.rate, f.interval) == (0, 4, 0.0, [0.0, 62.4])
    assert sum(asked[q] for q in CAT_QS) == 4 + 1          # four fresh questions and one re-ask
    assert [p.text for p in run.sampler.unasked] == CAT_QS[4:]
    assert not {p.text for p in run.probes} & set(CAT_QS[4:])  # never needed, so not a question of the run


def test_a_front_that_is_not_clear_yet_asks_the_rest_of_its_pool(monkeypatch):
    run, asked, _ = measure(monkeypatch, lambda q, n: "Notion fits." if CAT_QS.index(q) % 2 == 0 else "Coda fits.")
    [f] = run.sampler.fronts
    assert (f.asked, f.look, f.stopped_early, f.named, f.judged) == (6, 2, False, 3, 6)
    lo, hi = wilson(3, 6, z_for(sampler.ALPHA2))
    assert f.interval == [round(100 * lo, 1), round(100 * hi, 1)] and f.margin_met
    assert run.sampler.unasked == [] and all(asked[q] >= 1 for q in CAT_QS)
    assert any("more question(s) asked" in line for line in run.log)


def test_a_run_budget_stops_look_2_and_says_the_margin_is_not_met(monkeypatch):
    run, asked, prov = measure(monkeypatch, lambda q, n: "Notion fits." if CAT_QS.index(q) % 2 == 0 else "Coda fits.",
                               budget="0.001")
    [f] = run.sampler.fronts
    assert (f.asked, f.look) == (4, 1) and not f.margin_met and "budget" in f.note
    assert prov.spent > 0


def test_questions_no_front_needed_keep_the_frozen_baseline_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    run, _, _ = measure(monkeypatch, lambda q, n: "Coda fits.")
    reports.save_run(run)
    loaded = reports.load_run(run.id)                      # raises if the hash no longer matches
    assert graph.frozen_hash(loaded) == run.baseline_hash and len(loaded.sampler.unasked) == 2


def test_the_two_looks_cover_the_true_rate_at_least_95_percent_of_the_time():
    """The error guarantee, simulated in-process: fresh questions, a stop at look 1 or look 2."""
    rng = random.Random(7)
    n1, n2 = sampler.looks(20)
    covered = total = 0
    for rate in (0.0, 0.02, 0.1, 0.3, 0.5, 0.7, 0.95):
        for _ in range(400):
            answers = [rng.random() < rate for _ in range(n2)]
            k1 = sum(answers[:n1])
            if sampler.half_width(k1, n1, z_for(sampler.ALPHA1)) <= 0.2:
                lo, hi = wilson(k1, n1, z_for(sampler.ALPHA1))
            else:
                lo, hi = wilson(sum(answers), n2, z_for(sampler.ALPHA2))
            covered += lo <= rate <= hi
            total += 1
    assert covered / total >= 0.95


def test_replay_runs_have_no_sampler():
    run = graph.execute(graph.new_run(F.profile, F), F)
    assert run.sampler is None and not any(line.startswith("Sampler") for line in run.log)


# ---------------------------------------------------------------- category sharing
def rival():
    return F.profile.model_copy(update=dict(name="Coda", domain="coda.io", aliases=[], branded_terms=[],
                                            owned_domains=[], core_category=CATEGORY, category_questions=[]))


def test_a_second_brand_in_the_category_asks_the_same_questions_and_pays_once(monkeypatch, tmp_path):
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    store = sharing.Store(tmp_path / "shared.db")
    first, asked, _ = measure(monkeypatch, lambda q, n: "Coda fits.", share=store)
    paid = sum(asked[q] for q in CAT_QS)
    second, asked2, prov = measure(monkeypatch, lambda q, n: "Coda fits.", profile=rival(), share=store)
    firsts = [a for a in second.answers if a.probe_id.startswith("cat-b")]
    assert {p.text for p in second.probes if p.id.startswith("cat-b")} <= set(CAT_QS)   # the shared pool
    assert all(a.shared for a in firsts) and prov.shared == sum(a.shared for a in second.answers)
    assert sum(asked2[q] for q in CAT_QS) == 1 < paid      # only the wobble re-ask is asked again
    assert not any(a.shared for a in second.repeat_answers)
    # the same answer, judged again for the brand it now scores: "Coda fits." names Coda, not Notion
    assert [f.named for f in first.sampler.fronts] == [0] and second.sampler.fronts[0].named == 4
    assert second.sampler.shared == prov.shared


def test_nothing_is_shared_across_access_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "DATA", tmp_path)            # the access database
    pass_a, pass_b = access.create_pass("a", 5), access.create_pass("b", 5)
    store = sharing.Store(tmp_path / "shared.db")
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    with access.spending(pass_a):
        first, _, _ = measure(monkeypatch, lambda q, n: "Coda fits.", share=store)
    with access.spending(pass_b):
        second, _, prov = measure(monkeypatch, lambda q, n: "Coda fits.", share=store,
                                  profile=rival().model_copy(update=dict(category_questions=CAT_QS[3:])))
    buyer = lambda run: {p.text for p in run.probes if p.id.startswith("cat-b")}
    a_only = buyer(first) - set(CAT_QS[3:])
    assert a_only and not a_only & buyer(second)
    assert prov.shared == 0 and not any(a.shared for a in [*second.answers, *second.repeat_answers])
    with access.spending(pass_a):
        _, _, again = measure(monkeypatch, lambda q, n: "Coda fits.", share=store, profile=rival())
    assert again.shared > 0
