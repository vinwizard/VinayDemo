"""Nothing an engine identifier is called leaks onto a page, and the ids themselves never move.

The whole point of the display layer is that a reader who has never seen the code can read the
screen. That is only true if it stays true, so these are guards, not documentation.
"""
import re

import pytest

import graph
import labels
from providers import fixture
from reports import to_markdown
from schemas import Probe


def probe(pid, kind="blind", phase="baseline"):
    return Probe(id=pid, topic_id="t", text="q", kind=kind, phase=phase, purpose="p")


@pytest.mark.parametrize("pid,kind,phase,expected", [
    ("np-1", "named", "baseline", "Brand question 1"),
    ("np-8", "named", "baseline", "Brand question 8"),
    ("kb-2", "blind", "baseline", "Buyer question 2"),
    ("ai_native-b1", "blind", "baseline", "Buyer question 1"),
    ("kb-f1", "blind", "followup", "Follow-up question 1"),
])
def test_probe_name(pid, kind, phase, expected):
    assert labels.probe_name(probe(pid, kind, phase)) == expected


def test_numbering_comes_from_the_id_not_the_list_order():
    """Reordering the list must not renumber the questions."""
    ps = [probe(f"np-{i}", "named") for i in range(1, 9)]
    assert [labels.probe_name(p) for p in reversed(ps)] == [labels.probe_name(p) for p in ps][::-1]


@pytest.fixture(scope="module")
def run_a():
    prov = fixture.FixtureProvider("A")
    return graph.execute(graph.new_run(fixture.bundled_profile("A"), prov), prov)


# np-4, kb-2, pos-ai_native, ai_native-b1 — anything shaped like an engine id
ID_SHAPED = re.compile(r"(?<!\w)(np|pos|kb|pt|mtg|po)-[a-z0-9_]+", re.I)


def test_workflow_log_speaks_words_not_ids(run_a):
    for line in run_a.log:
        assert not ID_SHAPED.search(line), line


def test_followup_rationale_names_topics_and_keeps_the_ids_in_the_data(run_a):
    d = run_a.decisions[0]
    assert "Project tracking" in d.rationale and "Meeting documentation" in d.rationale
    assert not ID_SHAPED.search(d.rationale), d.rationale
    # display only: traceability still lives in the stored fields
    assert d.selected_topics == ["pt", "mtg"]
    assert d.evidence_probe_ids and all(ID_SHAPED.match(p) for p in d.evidence_probe_ids)


BACKTICKED = re.compile(r"`[^`]*`")

# synthetic, page_fetch, demo_replay — a stored value that was never turned into words
RAW_VALUE = re.compile(r"(?<!\w)(" + "|".join(labels.PROVENANCE_LABEL) + r")(?!\w)")


@pytest.mark.parametrize("scenario", ["A", "B"])
def test_markdown_report_never_leaves_an_id_as_the_only_name(scenario):
    """The Markdown export is the generated artefact a reader is handed; ids may only trail a name."""
    prov = fixture.FixtureProvider(scenario)
    run = graph.execute(graph.new_run(fixture.bundled_profile(scenario), prov), prov)
    md = to_markdown(run)
    spoken = BACKTICKED.sub("", md)  # backticked ids are traceability, and always follow their name
    assert [l for l in spoken.splitlines() if ID_SHAPED.search(l)] == []
    assert [l for l in spoken.splitlines() if RAW_VALUE.search(l)] == []
    # display only: the ids are still in the export and in the stored findings
    assert "`np-1`" in md
    stored = [i for f in run.findings for i in f.evidence_ids]
    assert stored and all(ID_SHAPED.fullmatch(i) for i in stored)
    assert {a.provenance for a in run.answers} == {"synthetic"}


def test_markdown_report_leads_with_names(run_a):
    md = to_markdown(run_a)
    assert "**Brand question 1** (`np-1`" in md
    assert "strength 2" not in md and "- Evaluation: recommended" in md
    assert "[Sample data]" in md


def test_exclusion_reasons_name_the_question(run_a):
    import drift
    answers = [a for a in run_a.answers if a.probe_id != "np-4"]
    _, reasons, asked = drift.named_eligibility(run_a.probes, answers, run_a.evaluations)
    assert reasons == ["Brand question 4: no answer collected"] and asked == 8
