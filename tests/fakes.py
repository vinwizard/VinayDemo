"""Fakes more than one test module builds: the wire formats the app reads and writes, a judge, a category."""
import json

from fastapi.testclient import TestClient

import access
import api.main as main
import graph
import reports
from providers import fixture, live

CATEGORY = "connected workspace software"
CAT_QS = [f"Which workspace tool suits a team of {n}?" for n in (5, 10, 20, 50, 100, 200)]


def sse_events(text) -> list[tuple[str, dict]]:
    """SSE text, or a stream generator's chunks, -> [(event, payload)]. An `id:` line is skipped."""
    if not isinstance(text, str):
        text = "".join(text)
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def openai_reply(text: str, searched: bool = False, usage: dict = None, annotations: list = None) -> dict:
    """A Responses API reply as a dict: one web search when `searched`, then the message."""
    content = {"type": "output_text", "text": text}
    if annotations is not None:
        content["annotations"] = annotations
    out = {"output": [*([{"type": "web_search_call"}] if searched else []),
                      {"type": "message", "content": [content]}]}
    if usage:
        out["usage"] = usage
    return out


def replay(scenario: str = "A"):
    """A bundled scenario run end to end offline: a fresh Run each call, safe to change."""
    prov = fixture.FixtureProvider(scenario)
    return graph.execute(graph.new_run(prov.profile, prov), prov)


def seeded_data(tmp_path, monkeypatch, company_id: str) -> None:
    """Companies, runs and the access database under tmp_path, holding one copy of the seed company."""
    companies, runs = tmp_path / "companies", tmp_path / "runs"
    companies.mkdir()
    runs.mkdir()
    seed = json.loads((reports.BUNDLED / "companies" / f"{main.SEED_COMPANY}.json").read_text())
    (companies / f"{company_id}.json").write_text(json.dumps(seed | {"id": company_id}))
    monkeypatch.setattr(reports, "DATA", tmp_path)
    monkeypatch.setattr(reports, "COMPANIES", companies)
    monkeypatch.setattr(reports, "RUNS", runs)


def why_client(tmp_path, monkeypatch, runs, model) -> TestClient:
    """The why routes over HTTP: every file under tmp_path, `runs` saved, a preflight that passes, and
    `model` (a fake Responses call) behind the metered path."""
    for name, value in (("DATA", tmp_path), ("RUNS", tmp_path / "runs"), ("INVESTIGATIONS", tmp_path / "investigations")):
        monkeypatch.setattr(reports, name, value)
    (tmp_path / "runs").mkdir()
    for run in runs:
        reports.save_run(run)
    monkeypatch.setenv(live.KEY_ENV, "test-key")
    monkeypatch.setattr(live, "preflight", lambda: live.Resolved("gpt-6-luna", live.SEARCH_TOOL, "gpt-6-luna", None))
    monkeypatch.setattr(access, "_create", lambda timeout, **kw: model(**kw))
    return TestClient(main.app, raise_server_exceptions=False)


class Judge:
    """Labels what the answer actually says, so the validators accept it. `endorse` = (attribute id,
    quote): a brand answer carrying the quote endorses that claim."""
    model = "test-judge"

    def __init__(self, rivals=("Linear", "Asana", "Coda"), endorse=None):
        self.rivals, self.endorse = rivals, endorse

    def label(self, probe, answer, attributes, profile):
        named = profile.name in answer.text
        endorsed = self.endorse and probe.kind == "named" and self.endorse[1] in answer.text
        return dict(mentioned=named, recommended=False, negative_mention=False,
                    competitor_recommendations=[c for c in self.rivals if c in answer.text],
                    evidence_quotes=[answer.text] if named else [], on_topic=True,
                    attributes=[dict(attribute_id=self.endorse[0], quote=self.endorse[1], polarity="positive")]
                    if endorsed else [])

    def discover(self, profile, attributes, answers):
        return []
