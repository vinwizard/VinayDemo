"""Bootstrap 95% intervals on the numbers, and whether the gap between the two fronts is real.
Seeded, so a saved run always shows the same interval; no key, no network."""
import random

import graph
from providers import fixture
from scoring import echo_draws, gap_verdict, interval, visibility_draws
from test_fronts import run_fronts


def noisy(p_mention, questions=12, tries=3, seed=1):
    """Buyer questions whose tries name the brand (strength 1) with probability p_mention."""
    rng = random.Random(seed)
    return [[int(rng.random() < p_mention) for _ in range(tries)] for _ in range(questions)]


def test_the_same_answers_always_give_the_same_interval():
    q = noisy(0.5)
    assert visibility_draws(q, "placed") == visibility_draws(q, "placed")
    lo, hi = interval(visibility_draws(q))
    assert 0 < lo < hi < 50


def test_a_known_gap_is_real_and_no_gap_is_not():
    far, _ = gap_verdict(visibility_draws(noisy(0.9), "placed"), visibility_draws(noisy(0.1, seed=2), "aiming"))
    assert far[0] > 0 and _
    same = gap_verdict(visibility_draws(noisy(0.5), "placed"), visibility_draws(noisy(0.5, seed=2), "aiming"))
    assert same[0][0] < 0 < same[0][1] and not same[1]


def test_one_try_or_too_few_questions_has_no_interval():
    assert visibility_draws([[2], [0], [1], [2], [0], [1]]) is None
    assert visibility_draws(noisy(0.5, questions=4)) is None
    assert visibility_draws(noisy(0.5, questions=5)) is not None


def test_answers_that_never_vary_give_no_verdict():
    assert gap_verdict(visibility_draws([[1, 1, 1]] * 6, "placed"), visibility_draws(noisy(0.1), "aiming")) is None


def test_too_few_brand_answers_have_no_echo_interval():
    endorsed = {"a": {"x"}, "b": set(), "c": {"x"}}
    assert echo_draws(["a", "b", "c"], {"x": 1.0}, endorsed) is None
    ids = [f"q{i}" for i in range(8)]
    lo, hi = interval(echo_draws(ids, {"x": 1.0}, {i: {"x"} for i in ids[:4]}))
    assert lo < 50 < hi


def test_offline_replay_keeps_its_numbers_and_says_no_repeat_ask_means_no_interval():
    for scenario, align in (("A", 21.4), ("B", 27.9)):
        p = fixture.FixtureProvider(scenario)
        d = graph.execute(graph.new_run(p.profile, p), p).drift
        assert d.alignment == align and d.alignment_interval[0] <= align <= d.alignment_interval[1]
        assert d.visibility_interval is None and d.sets[0].interval is None
        assert "No question was asked twice" in d.na_reasons["visibility_interval"] == d.sets[0].interval_note


def test_fronts_whose_answers_never_vary_withhold_the_verdict_through_a_rescore(monkeypatch):
    run, _ = run_fronts(monkeypatch)
    for rescored in (False, True):
        if rescored:
            graph.rescore(run, {a.id: 1.0 for a in run.attributes[:1]})
        d = run.drift
        placed, aiming = d.sets
        assert (placed.interval, aiming.interval) == ([50.0, 50.0], [0.0, 0.0])
        assert (d.gap_interval, d.gap_real) == (None, None)
        assert d.na_reasons["visibility_gap_interval"].startswith("Too few questions to call the gap")
