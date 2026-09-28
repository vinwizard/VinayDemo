"""What AI read: the reading trace every live answer records (providers/live.reading_of).

Offline: a recorded Amgen response (tests/cassettes, trimmed to Amgen's own pages and filings)
stands in for the API.
"""
import json
from pathlib import Path

import access
from providers import fixture, live
from schemas import Answer, Probe

CASSETTES = Path(__file__).parent / "cassettes"
STRENGTHS = json.loads((CASSETTES / "amgen_strengths.json").read_text())
RELEASE = "https://www.sec.gov/Archives/edgar/data/318154/000031815426000124/amgn-20260630earningsrelea.htm"
PROBE = Probe(id="np-4", topic_id="perception", text=STRENGTHS["question"], kind="named",
              phase="baseline", purpose="perception")


def test_the_trace_keeps_every_step_in_order_with_what_was_read():
    steps = live.reading_of(STRENGTHS, cap=None)
    assert [s.kind for s in steps] == ["search", "open_page", "find_in_page", "open_page"]
    assert steps[0].queries[0] == "Amgen 2025 annual report 10-K 2025 revenue products risks"
    assert steps[1].url == RELEASE and steps[2].pattern == "Total revenues increased"
    window = next(r for r in steps[1].results if r.url == RELEASE)
    assert "debt outstanding totaled $57.3 billion" in window.text   # the page lines themselves
    assert window.crawled == "today"


def test_one_find_call_records_every_find_it_bundled():
    """The action names one pattern; the results carry all of them. Results are the record."""
    find = live.reading_of(STRENGTHS, cap=None)[2]
    assert len(find.results) == 3 and any("TEZSPIRE" in r.text for r in find.results)


def test_api_markup_is_not_page_text():
    for step in live.reading_of(STRENGTHS, cap=None):
        for r in step.results:
            assert "" not in r.text and "[wordlim" not in r.text


def test_a_run_keeps_a_capped_copy():
    for step in live.reading_of(STRENGTHS):
        assert all(len(r.text) <= live.TRACE_CAP for r in step.results)


def test_no_search_no_trace():
    assert live.reading_of({"output": [{"type": "message", "content": []}]}) is None


def test_the_measured_call_asks_for_what_was_read(monkeypatch):
    sent = {}
    monkeypatch.setenv(access.KEY_ENV, "test-key")
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: sent.update(kw) or STRENGTHS)
    live.default_transport(live.measured_prompt(PROBE), "test-model", 30)
    assert sent["include"] == ["web_search_call.action.sources", "web_search_call.results"]
    sent.clear()
    live.default_transport(live.measured_prompt(PROBE), "test-model", 30, tool=None)
    assert "include" not in sent   # no tool, nothing to include: the API would refuse it


def test_a_live_answer_carries_its_trace():
    f = fixture.FixtureProvider("A")
    prov = live.LiveProvider(f.attributes(), f.named_probes(), model="test-model",
                             transport=lambda msgs, model, timeout: STRENGTHS)
    a = prov.answer(PROBE)
    assert a.trace and a.trace[1].url == RELEASE
    assert Answer.model_validate_json(a.model_dump_json()).trace == a.trace


def test_an_answer_saved_before_traces_still_loads():
    a = Answer.model_validate({"probe_id": "np-1", "provenance": "live_api", "text": "x"})
    assert a.trace is None
