"""Agent 1 — Onboarding: establish what the company offers and how it positions itself.

This module holds the brand questions and the replay fingerprint. Onboarding a real company from
its own website is agents/onboarding_model.py.
"""
import hashlib
import json

from agents.ana import attribute_leaks
from schemas import Attribute, CompanyProfile, Probe


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

