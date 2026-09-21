"""Stream endpoint checks. No HTTP client: run_events is the generator /api/stream serves, so it is
called directly.

The journey tests replace the Streamlit AppTest journeys that died with app.py: each bundled scenario
runs end to end through the stream the React app consumes, and the finished run reopens from disk.
The one rule worth pinning on setup is that a failure is visible to the browser without its detail,
because that detail can carry the API key.
"""
import json

import pytest

import api.main as main
import reports


def test_setup_failure_is_streamed_without_the_exception_detail(monkeypatch):
    def boom(mode, scenario=None, company_id=None):
        raise RuntimeError("boom: sk-secret")

    monkeypatch.setattr(main, "build_provider", boom)
    chunks = list(main.run_events("A", "live"))

    assert len(chunks) == 1
    assert chunks[0].startswith("event: error")
    assert "RuntimeError" in chunks[0]
    assert "sk-secret" not in chunks[0]
    assert "boom" not in chunks[0]


def events(scenario):
    out = []
    for chunk in main.run_events(scenario, "demo"):
        head, data = chunk.strip().split("\n")
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


@pytest.fixture
def journey(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "RUNS", tmp_path)
    return events


@pytest.mark.parametrize("scenario,alignment,landed", [
    ("A", 21.4, ["Connected docs and databases"]),
    ("B", 30.7, ["Replaces multiple tools"]),
])
def test_journey(journey, scenario, alignment, landed):
    evs = journey(scenario)
    kinds = [k for k, _ in evs]
    assert "error" not in kinds
    assert kinds[-1] == "done" and kinds.count("done") == 1
    nodes = [p["node"] for k, p in evs if k == "node"]
    assert set(nodes) == set(main.graph.STAGES)
    answers = [p for k, p in evs if k == "answer"]
    assert answers and [a["done"] for a in answers] == list(range(1, len(answers) + 1))
    assert all(a["status"] == "ok" for a in answers)

    run = evs[-1][1]["run"]
    assert run["status"] == "complete" and run["mode"] == "demo_replay"
    assert run["drift"]["alignment"] == alignment and run["drift"]["landed"] == landed
    assert {a["provenance"] for a in run["answers"]} == {"synthetic"}
    assert len(run["answers"]) == len(answers)
    # the finished run reopens from disk as the same run
    assert main.get_run(evs[-1][1]["run_id"]) == run


def test_scenarios_differ(journey):
    """Perception is fixture-driven, not a fixed animation: different data, different zones."""
    a, b = (journey(s)[-1][1]["run"]["drift"] for s in ("A", "B"))
    assert a["alignment"] != b["alignment"]
    assert set(a["landed"]) != set(b["landed"])
    assert set(a["imposed"]) != set(b["imposed"])
