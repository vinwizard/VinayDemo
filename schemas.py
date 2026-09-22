"""Pydantic state contracts (.claude/skills/product-workflow)."""
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
    logo_url: Optional[str] = None  # the site's own icon, from the homepage fetch; display only
    # What a buyer would call the market it competes in ("AI search visibility tracking"). Buyer
    # questions go to it first, so a company is always asked about its own category. None: saved
    # before categories existed, and buyer questions then follow its claims alone.
    core_category: Optional[str] = None
    category_questions: list[str] = []  # blind buyer questions for the core category; vetted like any

    def all_domains(self) -> list[str]:
        return sorted({self.domain, *self.owned_domains})

    def names(self) -> list[str]:
        """Every name that counts as a mention. The name itself always does: onboarding asks for
        *other* names, so aliases like ["Notion Labs"] used to replace "Notion" rather than add to it."""
        return list(dict.fromkeys([self.name, *self.aliases]))


class Attribute(BaseModel):
    """One thing a brand can be known for. The unit of positioning drift.

    `intended` — the customer says they want to own it (aspirational; never counts as product fit).
    `claimed`  — their own public copy states it (evidence-backed).
    `emergent` — neither; AI assigned it. Discovered from answers, never declared up front.
    """
    id: str
    label: str
    # What the claim actually MEANS for this company, in one concrete sentence. A bare label like
    # "Enterprise ready" asserts a category and explains nothing; the description carries the
    # substance ("SSO, audit logs and SCIM for org-wide rollout").
    description: Optional[str] = None
    aliases: list[str] = []  # phrasings that count as an echo of this attribute
    intended_weight: Optional[float] = None  # set only when the customer named it
    claim_evidence_ids: list[str] = []       # set only when their own copy states it
    added_by_user: bool = False              # typed in by the customer, not extracted from a page
    # found by the discovery pass over the answers — neither the company nor the crawler supplied it
    discovered: bool = False
    claim_quotes: list[str] = []             # verbatim site copy stating it, per page
    claim_pages: int = 0                     # DERIVED: pages whose text contains a validated quote
    claim_pages_total: int = 0               # DERIVED: pages actually fetched
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
    # perception holds named probes; control holds the one category-knowledge question. Neither is a
    # buyer use case, so neither gets a topic score.
    kind: Literal["buyer", "perception", "control"] = "buyer"
    buyer_need: str
    positioning_point_ids: list[str]
    fit: Literal["strong", "partial", "unsupported"]
    fit_evidence_ids: list[str] = []


class Probe(BaseModel):
    id: str
    topic_id: str
    text: str
    kind: Literal["blind", "named"] = "blind"  # blind: never names the brand. named: may, but never names an attribute.
    # control: asked once beside the baseline, never scored as visibility (ana.control_probe)
    phase: Literal["baseline", "followup", "control"]
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
    try_no: int = 1  # which ask of the same question this is; buyer questions are asked several times

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
    try_no: int = 1


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


Zone = Literal["landed", "lost_claim", "contested", "imposed", "unstated_intent", "unprioritised"]
Owner = Literal["authority_gap", "messaging_gap", "contested_identity", "imposed_identity",
                "unprioritised_claim", "none"]


class AttributeScore(BaseModel):
    """One row of the drift map: intended vs claimed vs perceived, and whose problem the gap is.

    zone/owner are assigned by deterministic rules in drift.py, never by a model.
    """
    attribute_id: str
    label: str
    discovered: bool = False                # emergent: found in the answers, not declared up front
    intended_weight: Optional[float] = None
    claim_strength: Optional[float] = None  # fraction of known pages stating it
    claim_pages: int = 0                    # carried through so a percentage can show its counts
    claim_pages_total: int = 0
    n: int = 0                              # eligible named-probe answers
    echoes: int = 0                         # answers where AI associated it with the target
    echo_rate: Optional[float] = None       # positive echoes only: a neutral mention is not conviction
    negative_echoes: int = 0
    mention_rate: Optional[float] = None    # any mention, whatever its polarity
    negative_rate: Optional[float] = None
    zone: Zone
    owner: Owner
    quotes: list[str] = []      # verbatim, from answers
    probe_ids: list[str] = []
    limitations: list[str] = []
    na_reasons: dict[str, str] = {}  # field name -> why that number is null


class DriftReport(BaseModel):
    """The single-screen result. Claim echo needs no input; alignment is over intended attributes only."""
    provenance: Provenance
    # claim: nothing weighted, the site's own claims are the reference. intent: weights exist.
    lens: Literal["claim", "intent"] = "intent"
    claim_echo: Optional[float] = None      # 0-100, prominence-weighted supportive echo of claims
    n_named: int = 0           # eligible named-probe answers behind the perception layer
    n_blind: int = 0           # eligible blind-probe answers behind the visibility layer
    named_asked: int = 0       # how many were attempted, so a reader can see what was lost
    excluded_named: int = 0
    excluded_reasons: list[str] = []
    alignment: Optional[float] = None       # 0-100, weighted echo of intended attributes
    visibility: Optional[float] = None      # 0-100, mean of the per-try blind-probe scores
    tries: int = 1                          # how many times each buyer question was asked
    visibility_range: Optional[list[float]] = None  # [lowest, highest] per-try visibility
    # Why a buyer visibility with no brand mention is not trusted (scoring.low_confidence), or None.
    low_confidence: Optional[str] = None
    landed: list[str] = []
    lost_claims: list[str] = []
    contested: list[str] = []
    imposed: list[str] = []
    unstated_intent: list[str] = []
    unprioritised: list[str] = []
    scores: list[AttributeScore] = []
    limitations: list[str] = []
    na_reasons: dict[str, str] = {}  # field name -> why that number is null


class ClaimCheck(BaseModel):
    """How one extracted claim fared against the fetched pages, for the "how we checked" panel.

    Structured so the page never parses warning strings. Companies saved before this field existed
    have an empty list and their quote problems as plain strings in `Company.warnings`.
    """
    id: str
    label: str
    kept: bool
    quotes_matched: int = 0
    quotes_removed: int = 0  # too short, or not verbatim on any fetched page
    not_found: bool = False  # left out because no quote was on any fetched page
    notes: list[str] = []    # plain sentences: why quotes were removed or the claim left out


class WinBackAction(BaseModel):
    """One fix for a claim to win back or amplify: a page the run read, and buyer questions it asked.

    Proposed by a model (or authored, in replay) and kept only after agents/win_back.py checked
    every reference. A suggestion for the company's copy, never a measurement: it moves no number.
    """
    attribute_id: str
    label: str
    zone: Zone
    page_url: str                       # one of the pages actually read
    current_copy: Optional[str] = None  # verbatim on that page; None = add new copy
    rewrite: str
    question_ids: list[str] = []        # baseline buyer questions that did not recommend the company
    why: str = ""
    provenance: Provenance


class Company(BaseModel):
    """One onboarded company: what its own pages claim, plus what the customer says they intend.

    A company used to BE a fixture filename, so only the two bundled demos could be measured. This
    is the saved form of an onboarding crawl, and it is the other thing `build_provider` can start
    from. It holds no answers: a company onboarded from a URL has none, which is exactly why
    measuring one needs a live provider.
    """
    id: str
    schema_version: int = SCHEMA_VERSION
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    profile: CompanyProfile
    attributes: list[Attribute] = []
    pages: list[str] = []      # the URLs actually fetched; claim_pages_total counts these
    warnings: list[str] = []
    checks: list[ClaimCheck] = []


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
    # Buyer questions asked again (try 2 onward). Kept apart so every consumer of `answers` still
    # sees one answer per question; only buyer visibility and its range read these.
    repeat_answers: list[Answer] = []
    repeat_evaluations: list[QueryEvaluation] = []
    topic_evaluations: list[TopicEvaluation] = []
    decisions: list[AdaptiveDecision] = []
    findings: list[GapFinding] = []
    attributes: list[Attribute] = []
    attribute_scores: list[AttributeScore] = []
    # validated observations per named probe id, kept so a re-score never needs the model again
    observations: Optional[dict[str, list[AttributeObservation]]] = None  # None: saved before re-scoring
    drift_notes: list[str] = []  # limitations measure_drift adds beyond the report's own
    drift: Optional[DriftReport] = None
    win_back: list[WinBackAction] = []  # how to win it back; additive, never feeds a score
    win_back_notes: list[str] = []      # why a proposed action was dropped, or none was proposed
    log: list[str] = []
    status: str = "planned"
