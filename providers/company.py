"""A provider built from a saved onboarded company, rather than from a bundled fixture file.

It supplies the two things a run needs before any measuring starts — the attribute set and the
brand questions — and deliberately has no `answer()`. A company onboarded from a URL has no
authored answers, so `LiveProvider` does the measuring; there is no fixture fallback, because a
fixture answer served under a real company's name would be a fabricated measurement.
"""
from agents.onboarding import named_probes_for
from schemas import Attribute, Company, CompanyProfile, Probe


class CompanyProvider:
    name = "company"
    scenario = None

    def __init__(self, company: Company):
        self.company = company

    @property
    def profile(self) -> CompanyProfile:
        return self.company.profile

    def attributes(self) -> list[Attribute]:
        return list(self.company.attributes)

    def named_probes(self) -> list[Probe]:
        return named_probes_for(self.company.profile, self.company.attributes)
