"""Imported Claude Code research snapshots (provenance: web_research_snapshot).

Snapshots supply sourced company context only. They never produce chatbot answers or scores.
"""
import json
from pathlib import Path

from schemas import CompanyProfile, Evidence

RESEARCH = Path(__file__).resolve().parent.parent / "data" / "research"


def list_snapshots() -> list[Path]:
    return sorted(RESEARCH.glob("*.json"))


def load_snapshot(path: Path) -> dict:
    snap = json.loads(Path(path).read_text())
    if snap.get("provenance") != "web_research_snapshot":
        raise ValueError("not a research snapshot")
    return snap


def apply_snapshot(profile: CompanyProfile, snap: dict) -> CompanyProfile:
    """Replace illustrative evidence with sourced excerpts for matching positioning points.

    Evidence swap is a factual edit: identity and positioning text are unchanged.
    """
    if snap["company"].lower() != profile.name.lower():
        raise ValueError(f"snapshot is for {snap['company']}, not {profile.name}")
    p = profile.model_copy(deep=True)
    by_point = {}
    for e in snap["evidence"]:
        p.evidence = [x for x in p.evidence if x.id != e["id"]] + [Evidence(
            id=e["id"], url=e["url"], excerpt=e["excerpt"], retrieved_at=e["retrieved_at"],
            source_type="web_research_snapshot")]
        by_point.setdefault(e["supports"], []).append(e["id"])
    for pp in p.positioning_points:
        if pp.id in by_point:
            pp.evidence_ids, pp.support = by_point[pp.id], "sourced"
    used = {i for pp in p.positioning_points for i in pp.evidence_ids}
    p.evidence = [e for e in p.evidence if e.id in used]
    p.warnings = [w for w in p.warnings if "illustrative" not in w] + [
        f"Evidence from Claude Code research snapshot ({snap['retrieved_at'][:10]}); not cross-model chatbot visibility."]
    if any(pp.support != "sourced" for pp in p.positioning_points):
        p.warnings.append("Some positioning points remain unsourced (illustrative).")
    return p
