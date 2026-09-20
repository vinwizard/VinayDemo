"""Exports, persistence and import. Every export carries the mode label."""
import re
from datetime import datetime
from pathlib import Path

from agents.ana import baseline_hash
from labels import probe_names, source_names, with_ids
from schemas import SCHEMA_VERSION, Run

RUNS = Path(__file__).resolve().parent / "data" / "runs"

# QueryEvaluation.strength is 0/1/2 in the data and never on a page.
STRENGTH_LABEL = {0: "absent", 1: "mentioned", 2: "recommended"}

# TopicEvaluation.status. Statuses with no entry print as they are.
TOPIC_STATUS_LABEL = {"candidate gap": "Not recommended", "mixed": "Split results",
                      "observed presence": "Found"}

# Answer.provenance, spoken. Mirrors web/src/labels.ts.
PROVENANCE_LABEL = {"synthetic": "Sample data", "demo_replay": "Sample run",
                    "live_api": "Measured live", "page_fetch": "From their website",
                    "user_provided": "You told us", "web_research_snapshot": "Research snapshot"}

MODE_LABELS = {
    "demo_replay": "SYNTHETIC DEMO — fixture replay; no live chatbot measurements; model judgment simulated.",
    "live_api": "LIVE API — see per-answer provider, model, timestamp and grounding status.",
}


def mode_label(run: Run) -> str:
    return MODE_LABELS[run.mode]


def to_json(run: Run) -> str:
    return run.model_dump_json(indent=2)


def from_json(text: str) -> Run:
    run = Run.model_validate_json(text)
    if run.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {run.schema_version}")
    if run.baseline_hash and baseline_hash(run.probes) != run.baseline_hash:
        raise ValueError("baseline questions do not match the recorded baseline hash")
    return run


def save_run(run: Run) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{run.id}.json"
    path.write_text(to_json(run))
    return path


def list_runs() -> list[Path]:
    return sorted(RUNS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_run(run_id: str) -> Run:
    if not re.fullmatch(r"[0-9a-f]{6,32}", run_id):
        raise ValueError("bad run id")
    return from_json((RUNS / f"{run_id}.json").read_text())


def pct(x):
    return "—" if x is None else f"{x:.0%}"


def num(x):
    return "null" if x is None else f"{x:g}"


def when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y %H:%M")
    except ValueError:
        return iso


def to_markdown(run: Run) -> str:
    topics = {t.id: t for t in run.topics}
    ev = {e.probe_id: e for e in run.evaluations}
    ans = {a.probe_id: a for a in run.answers}
    src = source_names(run.profile.evidence)
    pn = probe_names(run.probes, run.topics)
    status = lambda s: TOPIC_STATUS_LABEL.get(s, s)
    out = [f"# Visibility Explorer report — {run.profile.name}", "",
           f"> **{mode_label(run)}**", "",
           f"- Run of {when(run.created_at)} · {run.profile.name} · id `{run.id}`",
           f"- Scenario {run.scenario or '—'} · schema v{run.schema_version}",
           f"- Baseline hash `{run.baseline_hash}`",
           f"- Profile evidence: {', '.join(sorted({e.source_type for e in run.profile.evidence})) or 'none'}", "",
           "## Baseline topics (simulated scores)" if run.mode == "demo_replay" else "## Baseline topics", "",
           "| Topic | Fit | Recommended | Visibility | Owned citations | Status | Heuristic investigation priority |",
           "|---|---|---|---|---|---|---|"]
    for te in [x for x in run.topic_evaluations if x.phase == "baseline"]:
        out.append(f"| {topics[te.topic_id].label} | {topics[te.topic_id].fit} | {te.recommendations}/{te.n} "
                   f"(excluded {te.excluded}) | {num(te.visibility_score)} | {te.owned_citations}/{te.n} | {status(te.status)} | "
                   f"{num(te.gap_priority)} |")
    out += ["", "## Where Profound could help (possible fit, not a guarantee)", ""]
    for f in run.findings:
        out += [f"### {topics[f.topic_id].label}", f"- Observation: {f.observation}",
                f"- Interpretation: {f.interpretation}",
                f"- Capability: {f.profound_capability or 'Insufficient evidence — none mapped'}"
                + (f" ({f.capability_url})" if f.capability_url else ""),
                f"- Suggested action: {f.suggested_action}",
                f"- Evidence: {with_ids(f.evidence_ids, pn)} · fit evidence: "
                f"{with_ids(f.fit_evidence_ids, src) or 'none'}",
                f"- Provenance: {f.provenance}", f"- Limitations: {' '.join(f.limitations)}"]
        if f.exploratory_note:
            out.append(f"- {f.exploratory_note}")
        out.append("")
    out += ["## Positioning points", ""]
    for i, pp in enumerate(run.profile.positioning_points, start=1):
        tested = [t for t in run.topics if pp.id in t.positioning_point_ids]
        res = "; ".join(f"{t.label}: {status(next((x.status for x in run.topic_evaluations if x.topic_id == t.id and x.phase == 'baseline'), '—'))}" for t in tested)
        sources = ", ".join(src.get(e, e) for e in pp.evidence_ids) or "no source"
        out.append(f"- Point {i} (`{pp.id}`, {pp.support}, {sources}): {pp.text} → {res or 'not tested'}")
    for d in run.decisions:
        picked = ", ".join(topics[t].label if t in topics else t for t in d.selected_topics) or "stop"
        out += ["", "## Follow-up decision (" + d.policy + ")", "", f"- Selected: {picked}",
                f"- Rationale: {d.rationale}", f"- Motivating questions: {with_ids(d.evidence_probe_ids, pn)}"]
    for phase in ("baseline", "followup"):
        out += ["", f"## {'Baseline' if phase == 'baseline' else 'Exploratory follow-up'} questions", ""]
        for p in [p for p in run.probes if p.phase == phase]:
            e, a = ev.get(p.id), ans.get(p.id)
            out += [f"**{pn[p.id]}** (`{p.id}`, {p.purpose}) — {p.text}",
                    f"- Answer [{PROVENANCE_LABEL.get(a.provenance, a.provenance) if a else '—'}]: "
                    f"{a.text if a else '—'}",
                    f"- Citations: {', '.join(a.citations) if a and a.citations else 'none'}",
                    f"- Evaluation: {STRENGTH_LABEL[e.strength] if e and e.strength is not None else '—'}"
                    f" — {e.explanation if e else '—'}",
                    *([f"- Warnings: {' | '.join(e.warnings)}"] if e and e.warnings else []), ""]
    out.append(f"_{mode_label(run)}_")
    return "\n".join(out)
