"""Demo replay provider: authored deterministic fixtures. Everything it returns is synthetic."""
import json
import os
import time
from pathlib import Path

from agents.onboarding import structural_fingerprint
from schemas import Answer, Attribute, CompanyProfile, Probe, Topic

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SCENARIOS = {"A": "demo_a.json", "B": "demo_b.json"}
CALLS = {"answer": 0}  # observable request counter (rerender tests)

DEV_DELAY_ENV = "VISEXP_DEV_DELAY"


def dev_delay() -> float:
    """Seconds to stall per replayed answer — a DEVELOPMENT aid only, off unless the env var is set.

    .claude/skills/build-history forbids simulated latency in the demo, and this must never be used to imply a
    provider was called. Its only purpose is to expose how the UI behaves when `execute_or_replay`
    blocks, which is what a real per-call provider will do. When it is on, the app says so loudly.
    """
    try:
        return max(0.0, float(os.environ.get(DEV_DELAY_ENV, "0") or 0))
    except ValueError:
        return 0.0


def load(scenario: str) -> dict:
    return json.loads((FIXTURES / SCENARIOS[scenario]).read_text())


def bundled_profile(scenario: str = "A") -> CompanyProfile:
    return FixtureProvider(scenario).profile


class ReplayUnavailable(Exception):
    pass


class FixtureProvider:
    name = "fixture"
    concurrency = 1  # deterministic replay order, and keeps the CALLS counter race-free

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.data = load(scenario)
        self.title = self.data["title"]

    @property
    def profile(self) -> CompanyProfile:
        """Same accessor CompanyProvider exposes, so a caller need not know which it holds."""
        return CompanyProfile(**self.data["profile"])

    def check_profile(self, profile: CompanyProfile):
        """Arbitrary or structurally edited companies must never receive the bundled report."""
        if structural_fingerprint(profile) != structural_fingerprint(self.profile):
            raise ReplayUnavailable(
                f"Replay data exists only for the unmodified bundled {self.data['profile']['name']} profile. "
                "This profile differs in identity or positioning, so it needs regeneration, an imported research file, "
                "or a live provider.")

    def plan(self, profile: CompanyProfile) -> tuple[list[Topic], list[Probe]]:
        self.check_profile(profile)
        return [Topic(**t) for t in self.data["topics"]], [Probe(**p) for p in self.data["baseline_probes"]]

    def attributes(self) -> list[Attribute]:
        """Intended + claimed layers. Emergent attributes are authored too, but with no intent weight."""
        return [Attribute(**a) for a in self.data.get("attributes", [])]

    def named_probes(self) -> list[Probe]:
        """Perception probes: they name the brand, never the attribute being measured."""
        return [Probe(**p) for p in self.data.get("named_probes", [])]

    def followup_bank(self) -> dict[str, list[dict]]:
        return self.data["followup_bank"]

    def answer(self, probe: Probe) -> Answer:
        """Only the probe id is used to look up the answer; a live provider would receive only probe.text."""
        CALLS["answer"] += 1
        if d := dev_delay():
            time.sleep(d)  # dev-only stall; see dev_delay(). Never on by default.
        if probe.kind == "named":
            pool = self.data.get("named_answers", [])
        elif probe.phase == "baseline":
            pool = self.data["baseline_answers"]
        else:
            pool = list(self.data["followup_answers"].values())
        raw = next((a for a in pool if a["probe_id"] == probe.id), None)
        if raw is None:
            return Answer(probe_id=probe.id, provenance="synthetic", provider="fixture", status="error",
                          error="no fixture answer for this probe")
        return Answer(**raw)
