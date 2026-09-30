"""A quick win's replay test (why.test_rewrite, verify.verify_investigation), offline: a recorded Amgen
reading list (tests/cassettes) and a fake model that names Amgen only when the rewrite is in what it
reads, so a working rewrite, a useless one and a harmful one each have to be told apart by the loop."""
import pytest

import verify
import why
from providers import live
from schemas import Attribute, Probe, QueryEvaluation, Run, WinBackAction
from test_why import PROFILE, STRENGTHS, Fake

ABOUT = "https://www.amgen.com/about"
QUESTION = "Which biotech companies develop medicines using living cells for serious diseases?"
HEADING_REWRITE = ("Amgen makes biologic medicines from living cells, for cancer, heart disease and bone loss. "
                   "Its plants in Ohio and Puerto Rico grow the cells that make them.")
CLAIM = Attribute(id="biologics", label="Biologic medicines made using living cells", intended_weight=1.0)
NAMED = "Amgen and Regeneron both develop cell-grown biologics."
MISSED = "Regeneron, Genentech and Novartis lead cell-based biologics."


def rewrite_run(page=ABOUT, named=False) -> Run:
    probe = Probe(id="biologics-b1", topic_id="pos-biologics", text=QUESTION, kind="blind", phase="baseline", purpose="p")
    action = WinBackAction(attribute_id="biologics", label=CLAIM.label, zone="unstated_intent", page_url=page,
                           heading=QUESTION, rewrite=HEADING_REWRITE, question_ids=["biologics-b1"],
                           why="The question asks who grows medicines from living cells; no page says Amgen does.",
                           provenance="live_api")
    return Run(id="r1", mode="live_api", profile=PROFILE, attributes=[CLAIM], probes=[probe], win_back=[action],
               evaluations=[QueryEvaluation(probe_id="biologics-b1", valid=True, mentioned=named, strength=int(named),
                                            explanation="x")])


def fake(says) -> Fake:
    # live answers missed Amgen; search off, it never names it either
    return Fake(STRENGTHS, says, off="Regeneron and Genentech.", live_text=MISSED)


def rewrite_named(text):
    return NAMED if "Its plants in Ohio" in text else MISSED


def test_a_rewrite_that_makes_ai_name_you_is_proven_before_anything_is_published():
    f = fake(rewrite_named)
    inv = why.test_rewrite(rewrite_run(), "biologics", "biologics-b1", lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=f))
    assert inv.kind == "buyer" and inv.counts == "names" and inv.question == QUESTION and inv.status == "complete"
    assert (inv.live.k, inv.live.n) == (0, 3) and inv.off.k == 0
    base, arm = inv.arms
    assert base.k == 0 and arm.kind == "inject" and arm.hypothetical and arm.urls == [ABOUT]
    assert arm.text == [f"{QUESTION}\n{HEADING_REWRITE}"]            # the passage as it would go on the page
    verdict = inv.verdicts[-1]
    # AI's search never returned amgen.com/about for this question: the rewrite works once it is found
    assert verdict.kind == "authority_fix" and verdict.fix == "authority" and verdict.arm_id == arm.id
    assert "names Amgen" in verdict.text and "has to be found" in verdict.text
    assert inv.spent_usd <= inv.budget_usd


def test_on_a_page_ai_already_read_the_rewrite_leads_it():
    read = "https://www.amgen.com/stories/2026/03/2025-letter-to-shareholders"   # in the recorded reading list
    inv = why.test_rewrite(rewrite_run(page=read), "biologics", "biologics-b1",
                           lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=fake(rewrite_named)))
    arm = inv.arms[1]
    assert arm.kind == "edit" and arm.urls == [read]
    assert inv.verdicts[-1].kind == "copy_fix" and "once the page is re-crawled" in inv.verdicts[-1].text


def test_a_rewrite_that_changes_nothing_or_lowers_it_is_disproven():
    idle = why.test_rewrite(rewrite_run(), "biologics", "biologics-b1",
                            lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=fake(lambda text: MISSED)))
    assert idle.verdicts[-1].kind == "not_movable" and idle.verdicts[-1].fix == "none"

    # live and replayed it names Amgen; the rewrite makes it stop
    lowers = Fake(STRENGTHS, lambda text: MISSED if "Its plants in Ohio" in text else NAMED, live_text=NAMED)
    inv = why.test_rewrite(rewrite_run(), "biologics", "biologics-b1",
                           lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=lowers))
    assert inv.verdicts[-1].kind == "copy_lowers" and "Do not publish it" in inv.verdicts[-1].text


RECOMMENDS = "Amgen is the one to pick: it grows its biologics in its own plants."


class Evaluator:
    """Labels an answer as the run's evaluator would: it recommends Amgen only when it says to pick it."""
    model = "judge"

    def label(self, probe, answer, attributes, profile):
        named = "Amgen" in answer.text
        return {"attributes": [], "mentioned": named, "recommended": "the one to pick" in answer.text,
                "negative_mention": False, "competitor_recommendations": [],
                "evidence_quotes": [answer.text] if named else [], "on_topic": True}


def test_a_question_that_already_names_you_counts_recommendation():
    # the baseline answer named Amgen without recommending it: naming cannot move, recommending can
    f = Fake(STRENGTHS, lambda text: RECOMMENDS if "Its plants in Ohio" in text else NAMED,
             off="Regeneron and Genentech.", live_text=NAMED)
    inv = why.test_rewrite(rewrite_run(named=True), "biologics", "biologics-b1", evaluator=Evaluator(),
                           lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=f))
    assert inv.counts == "recommends" and "recommends Amgen" in inv.judge
    assert (inv.live.k, inv.live.n) == (0, 3) and inv.arms[0].k == 0
    verdict = inv.verdicts[-1]
    assert verdict.kind == "authority_fix" and "AI recommends Amgen" in verdict.text


def test_a_question_already_at_the_top_gives_a_ceiling_not_a_disproof():
    f = Fake(STRENGTHS, lambda text: NAMED, off="Regeneron and Genentech.", live_text=NAMED)
    inv = why.test_rewrite(rewrite_run(), "biologics", "biologics-b1",
                           lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=f))
    verdict = inv.verdicts[-1]
    assert inv.counts == "names" and verdict.kind == "ceiling" and verdict.fix is None
    base = inv.arms[0]
    assert verdict.text == f"Already named in {base.k} of {base.n} replays without the rewrite: this question cannot show a gain."


def test_a_name_only_in_a_citation_is_not_naming_you():
    judge = why.NamesJudge(PROFILE)
    assert judge("Regeneron leads ([amgen.com](https://www.amgen.com/about)).") == (False, None)
    assert judge("Among them, Amgen grows its biologics in living cells. Others follow.") == \
        (True, "Among them, Amgen grows its biologics in living cells.")
    assert judge("") == (None, None)


def test_only_a_rewrite_against_a_question_it_was_written_for_can_be_tested():
    run = rewrite_run()
    run.probes.append(Probe(id="np-1", topic_id="perception", text="What is Amgen?", kind="named", phase="baseline",
                            purpose="p"))
    lab = why.Lab("m", live.SEARCH_TOOL, transport=fake(rewrite_named))
    for attribute, probe in (("biologics", "np-1"), ("other", "biologics-b1"), ("biologics", "nope")):
        with pytest.raises(ValueError):
            why.test_rewrite(run, attribute, probe, lab=lab)


def test_a_proven_rewrite_is_rechecked_live_by_naming(monkeypatch):
    run = rewrite_run()
    f = fake(rewrite_named)
    inv = why.test_rewrite(run, "biologics", "biologics-b1", lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=f))
    monkeypatch.setattr(verify.reports, "load_investigation", lambda _: inv)
    monkeypatch.setattr(verify.reports, "load_run", lambda _: run)
    # not on the page yet: nothing is asked, and it costs nothing
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", "<p>" + "Amgen medicines. " * 30 + "</p>"))
    v = verify.verify_investigation(inv.id, resolve=lambda: pytest.fail("no model is needed"))
    assert v.verdict == "not_published" and v.fleet_id is None and v.copy_text == f"{QUESTION}\n{HEADING_REWRITE}"
    # published, but no live answer reads the page yet
    page = f"<h2>{QUESTION}</h2><p>{HEADING_REWRITE}</p>" + "<p>More about Amgen.</p>" * 20
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", page))
    v = verify.verify_investigation(inv.id, resolve=lambda: pytest.fail("the lab is given"),
                                    lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=f))
    assert v.page_has_copy and v.verdict == "not_crawled" and v.read_by_ai.k == 0


def test_an_unproven_rewrite_cannot_be_rechecked(monkeypatch):
    inv = why.test_rewrite(rewrite_run(), "biologics", "biologics-b1",
                           lab=why.Lab("gpt-6-luna", live.SEARCH_TOOL, transport=fake(lambda text: MISSED)))
    monkeypatch.setattr(verify.reports, "load_investigation", lambda _: inv)
    with pytest.raises(ValueError):
        verify.verify_investigation(inv.id, resolve=lambda: pytest.fail("nothing is asked"))


# ---------------------------------------------------------------- over HTTP (api/why.py)
@pytest.fixture
def client(tmp_path, monkeypatch):
    import access
    import api.main as main
    import reports
    from fastapi.testclient import TestClient
    runs, invs = tmp_path / "runs", tmp_path / "investigations"
    runs.mkdir()
    for mod, name, value in ((reports, "DATA", tmp_path), (reports, "RUNS", runs), (main, "RUNS", runs),
                             (reports, "INVESTIGATIONS", invs)):
        monkeypatch.setattr(mod, name, value)
    reports.save_run(rewrite_run().model_copy(update={"id": "a1b2c3d4e5", "status": "complete"}))
    monkeypatch.setenv(live.KEY_ENV, "test-key")
    monkeypatch.setattr(live, "preflight", lambda: live.Resolved("gpt-6-luna", live.SEARCH_TOOL, "gpt-6-luna", None))
    f = fake(rewrite_named)
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: f(**kw))
    return TestClient(main.app, raise_server_exceptions=False)


def test_a_rewrite_test_streams_and_is_kept_then_rechecked_for_free_while_unpublished(client, monkeypatch):
    from test_why_api import events
    got = events(client.get("/api/runs/a1b2c3d4e5/rewrite-test/stream",
                            params={"attribute": "biologics", "probe": "biologics-b1"}).text)
    assert got[0][0] == "start" and got[0][1]["question"] == QUESTION and got[-1][0] == "done"
    inv = got[-1][1]
    assert inv["kind"] == "buyer" and inv["verdicts"][-1]["kind"] == "authority_fix"
    assert [i["id"] for i in client.get("/api/runs/a1b2c3d4e5/why").json()] == [inv["id"]]
    # a question the rewrite was not written for is refused before anything is asked
    refused = events(client.get("/api/runs/a1b2c3d4e5/rewrite-test/stream",
                                params={"attribute": "biologics", "probe": "np-1"}).text)
    assert refused[0][0] == "error" and "written for" in refused[0][1]["message"]
    # "Mark fix live" before the page carries it: free, and kept on the investigation
    monkeypatch.setattr(verify.audit, "get", lambda url: (url, 200, "text/html", "<p>" + "Amgen. " * 60 + "</p>"))
    checked = events(client.get(f"/api/investigations/{inv['id']}/verify/stream").text)
    assert checked[-1][0] == "done" and checked[-1][1]["verdict"] == "not_published"
    kept = client.get(f"/api/investigations/{inv['id']}").json()
    assert kept["verification"]["verdict"] == "not_published"
