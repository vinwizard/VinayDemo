"""Nothing an engine identifier is called leaks onto a page, and the ids themselves never move.

The whole point of the display layer is that a reader who has never seen the code can read the
screen. That is only true if it stays true, so these are guards, not documentation.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import graph
import labels
from fakes import replay
from providers import fixture
from schemas import Probe


def probe(pid, kind="blind", phase="baseline"):
    return Probe(id=pid, topic_id="t", text="q", kind=kind, phase=phase, purpose="p")


@pytest.mark.parametrize("pid,kind,phase,expected", [
    ("np-1", "named", "baseline", "Branded question 1"),
    ("np-8", "named", "baseline", "Branded question 8"),
    ("kb-2", "blind", "baseline", "Unbranded question 2"),
    ("ai_native-b1", "blind", "baseline", "Unbranded question 1"),
    ("kb-c1", "blind", "control", "Control question"),
])
def test_probe_name(pid, kind, phase, expected):
    assert labels.probe_name(probe(pid, kind, phase)) == expected


def test_numbering_comes_from_the_id_not_the_list_order():
    """Reordering the list must not renumber the questions."""
    ps = [probe(f"np-{i}", "named") for i in range(1, 9)]
    assert [labels.probe_name(p) for p in reversed(ps)] == [labels.probe_name(p) for p in ps][::-1]


@pytest.fixture(scope="module")
def run_a():
    return replay("A")


# np-4, kb-2, pos-ai_native, ai_native-b1 — anything shaped like an engine id
ID_SHAPED = re.compile(r"(?<!\w)(np|pos|kb|pt|mtg|po)-[a-z0-9_]+", re.I)


def test_workflow_log_speaks_words_not_ids(run_a):
    for line in run_a.log:
        assert not ID_SHAPED.search(line), line


# One list of what a reader must never be shown: engine id shapes, stored provenance values and the
# acronyms this task removed. Add the next word here.
NEVER_SHOWN = re.compile("|".join([f"(?i:{ID_SHAPED.pattern})",
                                   *(rf"(?<!\w){v}(?!\w)" for v in labels.PROVENANCE_LABEL),
                                   r"(?<!\w)AnA(?!\w)"]))


@pytest.mark.parametrize("scenario", ["A", "B"])
def test_engine_strings_never_leave_an_id_as_the_only_name(scenario):
    """The sentences the engine builds and a page prints whole; ids may only trail a name."""
    prov = fixture.FixtureProvider(scenario)
    run = graph.execute(graph.new_run(fixture.bundled_profile(scenario), prov), prov)
    said = [*run.drift.excluded_reasons, *run.drift.limitations]
    assert said and [s for s in said if NEVER_SHOWN.search(s)] == []
    assert {a.provenance for a in run.answers} == {"synthetic"}


def test_exclusion_reasons_name_the_question(run_a):
    import drift
    answers = [a for a in run_a.answers if a.probe_id != "np-4"]
    _, reasons, asked = drift.named_eligibility(run_a.probes, answers, run_a.evaluations)
    assert reasons == ["Branded question 4: no answer collected"] and asked == 8


@pytest.mark.skipif(not shutil.which("node"), reason="needs node, as the web tests do")
def test_the_browser_and_the_engine_speak_the_same_words():
    # labels.ts and labels.py drifted apart: "Experiment —" against "Experiment:", and a control
    # question was "Control question" on screen but "Unbranded question 1" in the engine's text.
    probes = [probe(*args) for args in [("np-3", "named"), ("np-f1", "named", "followup"), ("kb-2",),
                                        ("kb-c1", "blind", "control"), ("x",)]]
    script = (f"const m = await import({json.dumps(str(Path(labels.__file__).parent / 'web/src/labels.ts'))});"
              f"console.log(JSON.stringify([m.PROVENANCE_LABEL, m.probeLabels({json.dumps([p.model_dump() for p in probes])})]));")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    provenance, names = json.loads(out.stdout)
    assert provenance == labels.PROVENANCE_LABEL
    assert names == {p.id: labels.probe_name(p) for p in probes}
