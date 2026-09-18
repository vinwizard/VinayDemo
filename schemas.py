"""Pydantic state contracts (agents.md section 5)."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1
Provenance = Literal["synthetic", "web_research_snapshot", "live_api"]
SYNTHETIC_PROVIDERS = {None, "fixture"}


class Evidence(BaseModel):
    id: str
    url: Optional[str] = None
    excerpt: str
    retrieved_at: Optional[str] = None
    # illustrative | web_research_snapshot | user_provided | page_fetch
    source_type: str


class PositioningPoint(BaseModel):
    id: str
    text: str
    evidence_ids: list[str] = []
    # sourced | user_provided | uncertain
    support: str = "uncertain"


class CompanyProfile(BaseModel):
    name: str
    domain: str
    owned_domains: list[str] = []
    aliases: list[str] = []
    branded_terms: list[str] = []  # distinctive feature names that would identify the target
    customer_types: list[str] = []
    capabilities: list[str] = []
    use_cases: list[str] = []
    positioning_points: list[PositioningPoint] = []
    evidence: list[Evidence] = []
    warnings: list[str] = []
    approved: bool = False

    def all_domains(self) -> list[str]:
        return sorted({self.domain, *self.owned_domains})


class Topic(BaseModel):
    id: str
    label: str
    buyer_need: str
    positioning_point_ids: list[str]
    fit: Literal["strong", "partial", "unsupported"]
    fit_evidence_ids: list[str] = []


class Probe(BaseModel):
    id: str
    topic_id: str
    text: str
    phase: Literal["baseline", "followup"]
    purpose: str
    parent_probe_ids: list[str] = []


class Answer(BaseModel):
    probe_id: str
    text: str = ""
    citations: list[str] = []
    provider: Optional[str] = None
    model: Optional[str] = None
    collected_at: Optional[str] = None
    provenance: Provenance
    search_executed: Optional[bool] = None
    status: Literal["ok", "timeout", "error"] = "ok"
    error: Optional[str] = None
    fixture_labels: Optional[dict] = None  # authored labels; synthetic only

    @model_validator(mode="after")
    def _honest_provenance(self):
        if self.provenance == "synthetic":
            if self.provider not in SYNTHETIC_PROVIDERS or self.model or self.collected_at:
                raise ValueError("synthetic answers may not carry a real provider, model or live timestamp")
            if self.search_executed:
                raise ValueError("synthetic answers may not claim search_executed=true")
        elif self.fixture_labels is not None:
            raise ValueError("fixture labels are only allowed on synthetic answers")
        return self


class QueryEvaluation(BaseModel):
    probe_id: str
    valid: bool
    mentioned: bool = False
    recommended: bool = False
    negative_mention: bool = False
    competitor_recommendations: list[str] = []
    evidence_quotes: list[str] = []
    owned_citation: bool = False
    strength: Optional[int] = None  # 0/1/2, None when invalid
    explanation: str
    warnings: list[str] = []
    evaluator: str = "simulated (fixture labels + deterministic validation)"


class TopicEvaluation(BaseModel):
    topic_id: str
    phase: Literal["baseline", "followup"]
    provenance: Provenance
    n: int
    excluded: int
    excluded_reasons: list[str] = []
    mentions: int = 0
    recommendations: int = 0
    owned_citations: int = 0
    competitor_answers: int = 0
    mention_rate: Optional[float] = None
    recommendation_rate: Optional[float] = None
    citation_rate: Optional[float] = None
    visibility_score: Optional[float] = None
    competitor_rate: Optional[float] = None
    gap_priority: Optional[float] = None  # heuristic investigation priority
    status: str
    top_competitors: list[str] = []
    limitations: list[str] = []


class AdaptiveDecision(BaseModel):
    selected_topics: list[str]
    new_probes: list[Probe]
    rationale: str
    evidence_probe_ids: list[str]
    policy: str = "simulated AnA policy (deterministic)"


class GapFinding(BaseModel):
    topic_id: str
    observation: str
    evidence_ids: list[str]
    fit_evidence_ids: list[str] = []
    interpretation: str
    suggested_action: str
    profound_capability: Optional[str]  # None = insufficient evidence
    capability_url: Optional[str]
    limitations: list[str]
    provenance: Provenance
    gap_priority: Optional[float] = None
    exploratory_note: Optional[str] = None


class Run(BaseModel):
    id: str
    schema_version: int = SCHEMA_VERSION
    mode: Literal["demo_replay", "live_api"]
    scenario: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    profile: CompanyProfile
    topics: list[Topic] = []
    baseline_hash: Optional[str] = None
    probes: list[Probe] = []
    answers: list[Answer] = []
    evaluations: list[QueryEvaluation] = []
    topic_evaluations: list[TopicEvaluation] = []
    decisions: list[AdaptiveDecision] = []
    findings: list[GapFinding] = []
    log: list[str] = []
    status: str = "planned"
