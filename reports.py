"""Exports, persistence and import. Every export carries the mode label."""
import re
from pathlib import Path

from agents.ana import baseline_hash
from schemas import SCHEMA_VERSION, Run

RUNS = Path(__file__).resolve().parent / "data" / "runs"

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


def to_markdown(run: Run) -> str:
    topics = {t.id: t for t in run.topics}
    ev = {e.probe_id: e for e in run.evaluations}
    ans = {a.probe_id: a for a in run.answers}
    out = [f"# Visibility Explorer report — {run.profile.name}", "",
           f"> **{mode_label(run)}**", "",
           f"- Run `{run.id}` · scenario {run.scenario or '—'} · created {run.created_at} · schema v{run.schema_version}",
           f"- Baseline hash `{run.baseline_hash}`",
           f"- Profile evidence: {', '.join(sorted({e.source_type for e in run.profile.evidence})) or 'none'}", "",
           "## Baseline topics (simulated scores)" if run.mode == "demo_replay" else "## Baseline topics", "",
           "| Topic | Fit | Recommended | Visibility | Owned citations | Status | Heuristic investigation priority |",
           "|---|---|---|---|---|---|---|"]
    for te in [x for x in run.topic_evaluations if x.phase == "baseline"]:
        out.append(f"| {topics[te.topic_id].label} | {topics[te.topic_id].fit} | {te.recommendations}/{te.n} "
                   f"(excluded {te.excluded}) | {num(te.visibility_score)} | {te.owned_citations}/{te.n} | {te.status} | "
                   f"{num(te.gap_priority)} |")
    out += ["", "## Where Profound could help (possible fit, not a guarantee)", ""]
    for f in run.findings:
        out += [f"### {topics[f.topic_id].label}", f"- Observation: {f.observation}",
                f"- Interpretation: {f.interpretation}",
                f"- Capability: {f.profound_capability or 'Insufficient evidence — none mapped'}"
                + (f" ({f.capability_url})" if f.capability_url else ""),
                f"- Suggested action: {f.suggested_action}",
                f"- Evidence: {', '.join(f.evidence_ids)} · fit evidence: {', '.join(f.fit_evidence_ids) or 'none'}",
                f"- Provenance: {f.provenance}", f"- Limitations: {' '.join(f.limitations)}"]
        if f.exploratory_note:
            out.append(f"- {f.exploratory_note}")
        out.append("")
    out += ["## Positioning points", ""]
    for pp in run.profile.positioning_points:
        tested = [t for t in run.topics if pp.id in t.positioning_point_ids]
        res = "; ".join(f"{t.label}: {next((x.status for x in run.topic_evaluations if x.topic_id == t.id and x.phase == 'baseline'), '—')}" for t in tested)
        out.append(f"- {pp.id} ({pp.support}): {pp.text} → {res or 'not tested'}")
    for d in run.decisions:
        out += ["", "## AnA adaptive decision (" + d.policy + ")", "", f"- Selected: {', '.join(d.selected_topics) or 'stop'}",
                f"- Rationale: {d.rationale}", f"- Motivating probes: {', '.join(d.evidence_probe_ids)}"]
    for phase in ("baseline", "followup"):
        out += ["", f"## {'Baseline' if phase == 'baseline' else 'Exploratory follow-up'} questions", ""]
        for p in [p for p in run.probes if p.phase == phase]:
            e, a = ev.get(p.id), ans.get(p.id)
            out += [f"**{p.id}** ({p.purpose}) — {p.text}",
                    f"- Answer [{a.provenance if a else '—'}]: {a.text if a else '—'}",
                    f"- Citations: {', '.join(a.citations) if a and a.citations else 'none'}",
                    f"- Evaluation: strength {e.strength if e else '—'} — {e.explanation if e else '—'}",
                    *([f"- Warnings: {' | '.join(e.warnings)}"] if e and e.warnings else []), ""]
    out.append(f"_{mode_label(run)}_")
    return "\n".join(out)
