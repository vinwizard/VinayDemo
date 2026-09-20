"""One UI smoke journey per fixture, plus rerender, reopen and arbitrary-company checks.

The app is one screen now, so a journey is: pick scenario -> Measure drift -> results render.
Every acceptance guard the three-screen version enforced is still asserted here.
"""
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
    at.button(key="measure").click().run()
    assert not at.exception
    return at


@pytest.mark.parametrize("scenario,alignment,landed", [
    ("A", 21.4, ["Connected docs and databases"]),
    ("B", 30.7, ["Replaces multiple tools"]),
])
def test_journey(scenario, alignment, landed):
    at = journey(scenario)
    run = at.session_state.run
    assert run.status == "complete"
    assert run.drift.alignment == alignment
    assert run.drift.landed == landed
    assert any("SYNTHETIC DEMO" in m.value for m in at.markdown)


def test_scenarios_differ():
    """Perception is fixture-driven, not a fixed animation: different data, different zones."""
    a, b = journey("A").session_state.run.drift, journey("B").session_state.run.drift
    assert a.alignment != b.alignment
    assert set(a.landed) != set(b.landed)
    assert set(a.imposed) != set(b.imposed)


def test_rerenders_do_not_restart_runs():
    at = journey("A")
    run_id, calls = at.session_state.run.id, fixture.CALLS["answer"]
    for _ in range(3):
        at.run()
    assert at.session_state.run.id == run_id and fixture.CALLS["answer"] == calls


def test_completed_run_can_be_reopened():
    at = journey("B")
    run_id = at.session_state.run.id
    fresh = start()  # simulates a restart: new session, same data/runs
    fresh.selectbox(key="reopen_id").set_value(run_id).run()
    fresh.button(key="reopen_btn").click().run()
    assert fresh.session_state.run.id == run_id
    assert fresh.session_state.run.drift is not None
    assert not fresh.exception


def test_arbitrary_company_gets_research_plan_not_report():
    at = start()
    at.text_input(key="c_name").input("Acme Wiki").run()
    at.text_input(key="c_site").input("acme.example").run()
    at.text_area(key="c_points").input("Team wikis").run()
    at.button(key="build_custom").click().run()
    assert at.session_state.profile.name == "Acme Wiki"
    assert any("Replay data exists only" in w.value for w in at.warning)
    assert at.session_state.run is None
    assert not [b for b in at.button if b.key == "measure"]
