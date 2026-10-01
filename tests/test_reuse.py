"""Answers reused across runs (sharing.py, LiveProvider.plan_reuse) and the judge grading each answer
as it lands, offline: sleeping transports, a judge that labels what the answer says, fixed vectors."""
import threading
import time

import pytest

import access
import dispatch
import embeddings
import graph
import reports
import sampler
import sharing
from fakes import Judge, openai_reply
from providers import fixture, live
from schemas import Answer, Probe
from test_fronts import AIM_QS, AIMING, ENDORSE, WRITTEN
from test_parallel import USAGE, Clock, content, says

F = fixture.FixtureProvider("A")
BRAND_QS = {p.text for p in F.named_probes()}


@pytest.fixture(autouse=True)
def small_fronts(monkeypatch):
    monkeypatch.setenv(sampler.MARGIN_ENV, "33")


def measure(store, clock=None, fresh=False, model="gpt-6-luna", judge=None, aim_qs=AIM_QS, aiming=AIMING):
    profile = F.profile.model_copy(update=dict(core_category=aiming, category_questions=aim_qs))
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=profile, model=model,
                             transport=clock or Clock(), evaluator=judge or Judge(endorse=ENDORSE),
                             writer=lambda l, d, n: WRITTEN[:n], share=store)
    prov.fresh = fresh
    run = graph.execute(graph.new_run(profile, prov, mode="live_api"), prov, dispatch.Dispatcher(16))
    return run, prov


def reused(run) -> list[Answer]:
    return [a for a in run.answers if a.shared]


def firsts(run) -> int:
    return len(run.answers)


def test_a_second_run_reuses_at_most_half_its_first_asks_and_labels_them(tmp_path):
    store = sharing.Store(tmp_path / "s.db")
    first, _ = measure(store)
    clock = Clock()
    second, prov = measure(store, clock)
    got = reused(second)
    assert got and len(got) <= sharing.MAX_SHARE * firsts(second)
    assert prov.shared == len(got) == second.sampler.shared
    before = {a.probe_id: a for a in first.answers}
    for a in got:   # the stored answer: its text and time, judged again for this run
        assert a.text == before[a.probe_id].text and a.collected_at == before[a.probe_id].collected_at
        assert a.evaluator_model == "test-judge" and a.reused_question is None
    assert len(clock.asks) == firsts(second) - len(got) + len(second.repeat_answers)
    assert any("reused from a run in the last 24 hours" in line for line in second.log)
    assert not any(a.shared for a in second.repeat_answers)   # a wobble re-ask is always fresh


def test_the_cap_is_a_setting_and_reuse_never_pays_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    store = sharing.Store(tmp_path / "s.db")
    measure(store)
    clock = Clock()
    second, _ = measure(store, clock)
    assert len(reused(second)) == firsts(second)
    # nothing asked again but the wobble's re-ask
    assert len(clock.asks) == len(second.repeat_answers)


def test_a_fresh_run_reuses_nothing_and_still_keeps_its_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    store = sharing.Store(tmp_path / "s.db")
    measure(store)
    fresh, prov = measure(store, fresh=True)
    assert not reused(fresh) and prov.shared == 0
    third, _ = measure(store)
    assert reused(third)


def test_a_saved_run_is_the_same_with_reuse_on_as_without_when_nothing_is_reused(tmp_path):
    with_store, _ = measure(sharing.Store(tmp_path / "s.db"))
    without, _ = measure(None)
    assert content(with_store) == content(without)


def test_answers_expire_after_24_hours(tmp_path, monkeypatch):
    store = sharing.Store(tmp_path / "s.db")
    measure(store)
    later = time.time() + sharing.REUSE_HOURS * 3600 + 1
    monkeypatch.setattr(sharing.time, "time", lambda: later)
    second, _ = measure(store)
    assert not reused(second)


def test_another_model_or_reasoning_effort_reuses_nothing(tmp_path, monkeypatch):
    store = sharing.Store(tmp_path / "s.db")
    measure(store)
    other, _ = measure(store, model="gpt-5-nano")
    assert not reused(other)
    monkeypatch.setattr(live, "REASONING", {"effort": "medium"})
    deeper, _ = measure(store)
    assert not reused(deeper)


def test_another_pass_reuses_only_buyer_questions_the_app_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DATA", tmp_path)            # the access database
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    pass_a, pass_b = access.create_pass("a", 5), access.create_pass("b", 5)
    store = sharing.Store(tmp_path / "s.db")
    with access.spending(pass_a):
        first, _ = measure(store)
    with access.spending(pass_b):
        second, _ = measure(store)
    texts = {p.id: p.text for p in second.probes}
    source = lambda run: {a.reused_question or texts[a.probe_id] for a in reused(run)}
    assert source(second) and source(second) <= set(WRITTEN)   # never a brand question, nor the customer's own
    with access.spending(pass_a):
        again, _ = measure(store)
    assert source(again) & (BRAND_QS | set(AIM_QS))   # its own pass: any


def test_only_a_fresh_grounded_live_answer_is_stored(tmp_path):
    store = sharing.Store(tmp_path / "s.db")
    a = Answer(probe_id="x", text="t", provenance="live_api", model="m", search_executed=False)
    store.save("q", a, "mode", "run1")
    assert store.exact("q", "mode", "run2", set()) is None
    store.save("q", a.model_copy(update=dict(search_executed=True, shared=True)), "mode", "run1")
    assert store.exact("q", "mode", "run2", set()) is None
    store.save("q", a.model_copy(update=dict(search_executed=True, evaluator_labels={"x": 1})), "mode", "run1")
    hit = store.exact("Q ", "mode", "run2", set())
    assert hit.answer.text == "t" and hit.answer.evaluator_labels is None and hit.similarity is None
    assert store.exact("q", "other mode", "run2", set()) is None
    assert store.exact("q", "mode", "run1", set()) is None             # never within the run that asked it
    assert store.exact("q", "mode", "run2", {hit.id}) is None          # nor twice in one run


def test_near_takes_the_most_similar_question_at_or_above_the_threshold(tmp_path):
    store = sharing.Store(tmp_path / "s.db")
    a = Answer(probe_id="x", text="t", provenance="live_api", model="m", search_executed=True)
    store.save("close", a.model_copy(update=dict(text="close")), "mode", "r1", vec=[1.0, 0.3])
    store.save("closest", a.model_copy(update=dict(text="closest")), "mode", "r1", vec=[1.0, 0.1])
    store.save("far", a.model_copy(update=dict(text="far")), "mode", "r1", vec=[0.0, 1.0])
    hit = store.near([1.0, 0.0], "mode", "r2", set(), 0.9)
    assert (hit.answer.text, hit.question) == ("closest", "closest") and 0.99 < hit.similarity < 1
    assert store.near([1.0, 0.0], "mode", "r2", {hit.id}, 0.9).question == "close"
    assert store.near([0.0, 1.0], "mode", "r2", set(), 0.9).question == "far"
    assert store.near([1.0, -1.0], "mode", "r2", set(), 0.9) is None


def test_a_near_identical_buyer_question_reuses_the_answer_and_says_for_which(tmp_path, monkeypatch):
    """Two runs whose customer questions differ by a word: the vectors say they are near-identical."""
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    reworded = [q.replace("Which", "What") for q in AIM_QS]
    pair = dict(zip(reworded, AIM_QS))
    # a reworded question's vector is its original's with a small extra component: cosine just under 1
    monkeypatch.setattr(embeddings, "embed", lambda texts: [vector(pair.get(t, t)) + [3.0 if t in pair else 0.0]
                                                             for t in texts])
    store = sharing.Store(tmp_path / "s.db")
    first, _ = measure(store)
    clock = Clock(text=lambda q: says(pair.get(q, q)))
    # another category label, so the second run plans its own questions rather than the first's pool
    second, prov = measure(store, clock, aim_qs=reworded, aiming="connected workspace apps")
    texts = {p.id: p.text for p in second.probes}
    near = [a for a in reused(second) if a.reused_question]
    assert near and prov.near == len(near)
    for a in near:
        assert a.reused_question == pair[texts[a.probe_id]] and a.reused_similarity >= sharing.SIMILARITY
    assert any("near-identical" in line for line in second.log)
    # above the threshold only: the same rewording reuses nothing near once the threshold is higher
    monkeypatch.setattr(sharing, "SIMILARITY", 0.99999)
    third, _ = measure(store, aim_qs=reworded, aiming="connected team workspace apps")
    assert not any(a.reused_question for a in third.answers)


def vector(text: str) -> list[float]:
    """Unrelated texts get near-orthogonal vectors; the same text the same one."""
    import hashlib
    return [b - 127.5 for b in hashlib.sha256(text.encode()).digest()]


def test_one_stored_answer_is_never_reused_for_two_questions_of_one_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sharing, "MAX_SHARE", 1)
    monkeypatch.setattr(embeddings, "embed", lambda texts: [[1.0, 0.0] for _ in texts])  # every question alike
    store = sharing.Store(tmp_path / "s.db")
    a = Answer(probe_id="x", text="Coda fits.", provenance="live_api", model="gpt-6-luna", search_executed=True)
    prov = live.LiveProvider(F.attributes(), F.named_probes(), profile=F.profile, model="gpt-6-luna",
                             transport=Clock(), share=store)
    store.save("some buyer question", a, prov._mode, "earlier", vec=[1.0, 0.0])
    probes = [Probe(id=f"q{i}", topic_id="t", text=f"buyer question {i}", phase="baseline", purpose="")
              for i in range(4)]
    prov.plan_reuse([(p, 1) for p in probes])
    assert len(prov._reuse) == 1


def test_the_judge_grades_each_answer_as_it_lands_while_others_are_still_asked(tmp_path):
    """The slow question's ask waits for the judge to have labelled another answer: grading at the end,
    after every ask, would never set the event and the ask would time out."""
    labelled = threading.Event()

    class Streaming(Judge):
        def label(self, probe, answer, attributes, profile):
            labelled.set()
            return super().label(probe, answer, attributes, profile)

    slow = sorted(BRAND_QS)[0]
    seen = []

    def text(q):
        if q == slow:
            seen.append(labelled.wait(5))
        return says(q)
    run, _ = measure(None, Clock(text=text), judge=Streaming(endorse=ENDORSE))
    assert seen == [True]
    # the same content as a run whose judge had nothing to overlap with
    assert content(run) == content(measure(None)[0])


def test_reasoning_effort_is_sent_only_to_models_that_take_it(monkeypatch):
    assert live.reasoning_for("gpt-6-luna") == {"effort": "low"}
    assert live.reasoning_for("gpt-4.1-mini") is None
    sent = []
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: (sent.append(kw), openai_reply("ok", True, USAGE))[1])
    live.default_transport([{"role": "user", "content": "q"}], "gpt-6-luna", 5)
    from agents import evaluator_model
    evaluator_model.default_transport("p", "gpt-6-luna", 5)
    evaluator_model.default_transport("p", "gpt-4.1-mini", 5)
    assert [kw.get("reasoning") for kw in sent] == [{"effort": "low"}, {"effort": "low"}, None]
