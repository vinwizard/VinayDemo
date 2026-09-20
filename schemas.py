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


class Attribute(BaseModel):
    """One thing a brand can be known for. The unit of positioning drift.

    `intended` — the customer says they want to own it (aspirational; never counts as product fit).
    `claimed`  — their own public copy states it (evidence-backed).
    `emergent` — neither; AI assigned it. Discovered from answers, never declared up front.
    """
    id: str
    label: str
    aliases: list[str] = []  # phrasings that count as an echo of this attribute
    intended_weight: Optional[float] = None  # set only when the customer named it
    claim_evidence_ids: list[str] = []       # set only when their own copy states it
    claim_pages: int = 0                     # how many crawled/known pages state it
    claim_pages_total: int = 0               # denominator for claim strength
    # The buyer questions this claim implies, with no brand name anywhere. If the positioning were
    # landing, the company should surface for these. This is the placebo test.
    buyer_questions: list[str] = []
    note: Optional[str] = None

    @property
    def intended(self) -> bool:
        return self.intended_weight is not None

    @property
    def claimed(self) -> bool:
        return bool(self.claim_evidence_ids)


class AttributeObservation(BaseModel):
    """One attribute AI associated with the target in one answer, with the quote that proves it."""
    attribute_id: str
    quote: str  # must appear verbatim in the answer or the observation is dropped
    polarity: Literal["positive", "neutral", "negative"] = "neutral"


class Topic(BaseModel):
    id: str
    label: str
    kind: Literal["buyer", "perception"] = "buyer"  # perception holds named probes; not a buyer use case
    buyer_need: str
    positioning_point_ids: list[str]
    fit: Literal["strong", "partial", "unsupported"]
    fit_evidence_ids: list[str] = []


class Probe(BaseModel):
    id: str
    topic_id: str
    text: str
    kind: Literal["blind", "named"] = "blind"  # blind: never names the brand. named: may, but never names an attribute.
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
    fixture_labels: Optional[dict] = None    # authored labels; synthetic only
    evaluator_labels: Optional[dict] = None  # model-produced labels; live only
    evaluator_model: Optional[str] = None

    @property
    def labels(self) -> Optional[dict]:
        """Whoever proposed the judgment. Downstream code validates it the same way either way."""
        return self.evaluator_labels if self.evaluator_labels is not None else self.fixture_labels

    @model_validator(mode="after")
    def _honest_provenance(self):
        if self.provenance == "synthetic":
            if self.provider not in SYNTHETIC_PROVIDERS or self.model or self.collected_at:
                raise ValueError("synthetic answers may not carry a real provider, model or live timestamp")
            if self.search_executed:
                raise ValueError("synthetic answers may not claim search_executed=true")
            if self.evaluator_labels is not None:
                raise ValueError("evaluator labels are only allowed on live answers")
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


Zone = Literal["landed", "lost_claim", "imposed", "unstated_intent"]
Owner = Literal["authority_gap", "messaging_gap", "imposed_identity", "none"]


class AttributeScore(BaseModel):
    """One row of the drift map: intended vs claimed vs perceived, and whose problem the gap is.

    zone/owner are assigned by deterministic rules in drift.py, never by a model.
    """
    attribute_id: str
    label: str
    intended_weight: Optional[float] = None
    claim_strength: Optional[float] = None  # fraction of known pages stating it
    n: int = 0                              # eligible named-probe answers
    echoes: int = 0                         # answers where AI associated it with the target
    echo_rate: Optional[float] = None
    negative_echoes: int = 0
    zone: Zone
    owner: Owner
    quotes: list[str] = []      # verbatim, from answers
    probe_ids: list[str] = []
    limitations: list[str] = []


class DriftReport(BaseModel):
    """The single-screen result. Alignment is over intended attributes only."""
    provenance: Provenance
    n_named: int = 0           # eligible named-probe answers behind the perception layer
    n_blind: int = 0           # eligible blind-probe answers behind the visibility layer
    named_asked: int = 0       # how many were attempted, so a reader can see what was lost
    excluded_named: int = 0
    excluded_reasons: list[str] = []
    alignment: Optional[float] = None       # 0-100, weighted echo of intended attributes
    visibility: Optional[float] = None      # 0-100, reuses the existing blind-probe score
    landed: list[str] = []
    lost_claims: list[str] = []
    imposed: list[str] = []
    unstated_intent: list[str] = []
    scores: list[AttributeScore] = []
    limitations: list[str] = []


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
    attributes: list[Attribute] = []
    attribute_scores: list[AttributeScore] = []
    drift: Optional[DriftReport] = None
    log: list[str] = []
    status: str = "planned"
