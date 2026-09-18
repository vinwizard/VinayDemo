"""One UI smoke journey per fixture, plus rerender and reopen checks (Streamlit AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import reports
from providers import fixture

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "RUNS", tmp_path)


def start():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at


def journey(scenario):
    at = start()
    at.radio(key="scenario").set_value(scenario).run()
    at.button(key="load_demo").click().run()
    at.checkbox(key="reviewed").check().run()
    at.button(key="explore").click().run()
    at.button(key="run_replay").click().run()
    assert not at.exception
    return at


@pytest.mark.parametrize("scenario,selected", [("A", ["pt", "mtg"]), ("B", ["po", "kb"])])
def test_journey(scenario, selected):
    at = journey(scenario)
    run = at.session_state.run
    assert run.status == "complete" and run.decisions[0].selected_topics == selected
    assert any("SYNTHETIC DEMO" in m.value for m in at.markdown)
    at.radio(key="screen").set_value("3 · Gap report").run()
    assert not at.exception
    assert any("Answer Engine Insights" in m.value for m in at.markdown)


def test_rerenders_do_not_restart_runs():
    at = journey("A")
    run_id, calls = at.session_state.run.id, fixture.CALLS["answer"]
    for _ in range(3):
        at.run()
    at.radio(key="screen").set_value("3 · Gap report").run()
    at.radio(key="screen").set_value("2 · Investigation").run()
    assert at.session_state.run.id == run_id and fixture.CALLS["answer"] == calls


def test_completed_run_can_be_reopened():
    at = journey("B")
    run_id = at.session_state.run.id
    fresh = start()  # simulates a restart: new session, same data/runs
    fresh.selectbox(key="reopen_id").set_value(run_id).run()
    fresh.button(key="reopen_btn").click().run()
    assert fresh.session_state.run.id == run_id and fresh.session_state.screen == "3 · Gap report"
    assert not fresh.exception


def test_arbitrary_company_gets_research_plan_not_report():
    at = start()
    at.text_input(key="c_name").input("Acme Wiki").run()
    at.text_input(key="c_site").input("acme.example").run()
    at.text_area(key="c_points").input("Team wikis").run()
    at.button(key="build_custom").click().run()
    assert at.session_state.profile.name == "Acme Wiki"
    assert any("Replay data exists only" in w.value for w in at.warning)
    assert not [b for b in at.button if b.key == "explore"]
    assert at.session_state.run is None
