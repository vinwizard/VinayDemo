"""Agent 1 — Onboarding: establish what the company offers and how it positions itself.

Demo implementation loads a bundled profile. Arbitrary companies get a profile built only
from user-provided facts. URL fetching is disabled (see CHECKPOINT.md): pasted text only.
"""
import hashlib
import json
import re

from schemas import CompanyProfile, Evidence, PositioningPoint

MAX_POINTS = 8


def structural_fingerprint(p: CompanyProfile) -> str:
    """Identity + positioning claims. Changing any of these invalidates bundled replay data."""
    core = {"name": p.name.strip().lower(), "domain": p.domain.strip().lower(),
            "aliases": sorted(a.strip() for a in p.aliases),
            "points": [(pp.id, pp.text.strip()) for pp in p.positioning_points]}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def normalize_domain(raw: str) -> str:
    d = re.sub(r"^[a-z]+://", "", raw.strip().lower()).split("/")[0].split(":")[0]
    return d.removeprefix("www.")


def profile_from_user_input(name: str, website: str, pasted: str, points: list[str]) -> CompanyProfile:
    """Pasted text is untrusted data: stored as an evidence excerpt, never interpreted as instructions."""
    evidence, pps = [], []
    if pasted.strip():
        evidence.append(Evidence(id="user-1", excerpt=pasted.strip()[:12000], source_type="user_provided"))
    for i, text in enumerate([t.strip() for t in points if t.strip()][:MAX_POINTS], start=1):
        pps.append(PositioningPoint(id=f"pp{i}", text=text, evidence_ids=["user-1"] if evidence else [],
                                    support="user_provided"))
    return CompanyProfile(
        name=name.strip(), domain=normalize_domain(website), aliases=[name.strip()] if name.strip() else [],
        positioning_points=pps, evidence=evidence,
        warnings=["Built from user-provided facts only; nothing here was independently sourced.",
                  "No bundled replay answers exist for this company. Generating answers needs a live API key or an imported research file."],
    )


def edit_point(profile: CompanyProfile, point_id: str, new_text: str) -> CompanyProfile:
    """Changing a claim drops the evidence that supported the old wording."""
    p = profile.model_copy(deep=True)
    for pp in p.positioning_points:
        if pp.id == point_id and pp.text != new_text:
            pp.text, pp.evidence_ids, pp.support = new_text, [], "user_provided"
    p.approved = False
    return p


def research_plan(profile: CompanyProfile) -> list[str]:
    who = profile.name or "the company"
    return [
        f"Collect {who}'s homepage and two product pages as a sourced research snapshot (data/research/).",
        "Confirm aliases and owned domains; mark ambiguous aliases (common words) explicitly.",
        "Map each positioning point to a buyer topic with an evidence excerpt, or mark it not tested.",
        "Generate answers only via a configured live provider (see .env.example) — bundled Notion answers are never reused.",
    ]
