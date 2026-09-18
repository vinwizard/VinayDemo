"""Demo replay provider: authored deterministic fixtures. Everything it returns is synthetic."""
import json
from pathlib import Path

from agents.onboarding import structural_fingerprint
from schemas import Answer, CompanyProfile, Probe, Topic

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SCENARIOS = {"A": "demo_a.json", "B": "demo_b.json"}
CALLS = {"answer": 0}  # observable request counter (rerender tests)


def load(scenario: str) -> dict:
    return json.loads((FIXTURES / SCENARIOS[scenario]).read_text())


def bundled_profile(scenario: str = "A") -> CompanyProfile:
    return CompanyProfile(**load(scenario)["profile"])


class ReplayUnavailable(Exception):
    pass


class FixtureProvider:
    name = "fixture"

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.data = load(scenario)
        self.title = self.data["title"]

    def check_profile(self, profile: CompanyProfile):
        """Arbitrary or structurally edited companies must never receive the bundled report."""
        if structural_fingerprint(profile) != structural_fingerprint(CompanyProfile(**self.data["profile"])):
            raise ReplayUnavailable(
                f"Replay data exists only for the unmodified bundled {self.data['profile']['name']} profile. "
                "This profile differs in identity or positioning, so it needs regeneration, an imported research file, "
                "or a live provider.")

    def plan(self, profile: CompanyProfile) -> tuple[list[Topic], list[Probe]]:
        self.check_profile(profile)
        return [Topic(**t) for t in self.data["topics"]], [Probe(**p) for p in self.data["baseline_probes"]]

    def followup_bank(self) -> dict[str, list[dict]]:
        return self.data["followup_bank"]

    def answer(self, probe: Probe) -> Answer:
        """Only the probe id is used to look up the answer; a live provider would receive only probe.text."""
        CALLS["answer"] += 1
        pool = self.data["baseline_answers"] if probe.phase == "baseline" else list(self.data["followup_answers"].values())
        raw = next((a for a in pool if a["probe_id"] == probe.id), None)
        if raw is None:
            return Answer(probe_id=probe.id, provenance="synthetic", provider="fixture", status="error",
                          error="no fixture answer for this probe")
        return Answer(**raw)
