"""Agent 1 — Onboarding: establish what the company offers and how it positions itself.

Demo implementation loads a bundled profile. Arbitrary companies get a profile built only
from user-provided facts. URL fetching is disabled (see CHECKPOINT.md): pasted text only.
"""
import hashlib
import json
import re

from agents.ana import attribute_leaks
from schemas import Attribute, CompanyProfile, Evidence, PositioningPoint, Probe

MAX_POINTS = 8

# Brand questions live HERE, not in AnA. Onboarding is the only agent allowed to know the brand
# name; AnA's whole job is to ask what a buyer would ask, and it must never see the name it is
# testing for. Each template says the brand and nothing else about it — never an attribute, or the
# answer would only echo the question back (see ana.attribute_leaks).
NAMED_TEMPLATES = [
    "What is {brand}, and who is it for?",
    "How would you describe {brand} to someone who has never used it?",
    "What do people typically use {brand} for day to day?",
    "What are {brand}'s main strengths and weaknesses?",
    "Would you recommend {brand} to a 200-person company? Why or why not?",
    "What has changed about {brand} in the past year?",
    "What kind of team gets the most value out of {brand}?",
]
NAMED_PURPOSE = "Measure how AI characterises the brand when asked about it directly."


def named_probes_for(profile: CompanyProfile, attributes: list[Attribute] = ()) -> list[Probe]:
    """The perception axis for any company, templated on its name alone.

    There is deliberately no "how does {brand} compare to X?" question here: naming a competitor
    up front would put the answer in the model's mouth. Competitors are discovered from the blind
    answers instead, and the comparison is asked in the adaptive round (ana.comparison_probe).

    A template whose ordinary English collides with a measured claim ("What kind of TEAM…" against
    the alias "team") is dropped here rather than rewritten, so the collision costs one question at
    onboarding instead of failing validation and killing every later run. Ids come from the template
    position, so np-3 is the same question whether or not np-7 survived.
    """
    probes = [Probe(id=f"np-{i}", topic_id="perception", text=t.format(brand=profile.name),
                    kind="named", phase="baseline", purpose=NAMED_PURPOSE)
              for i, t in enumerate(NAMED_TEMPLATES, start=1)]
    return [p for p in probes if not attribute_leaks(p.text, list(attributes))]


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
