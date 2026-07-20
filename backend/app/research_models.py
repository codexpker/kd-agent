from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models import EvidenceAnchor


OpportunityType = Literal[
    "shared_unresolved_limitation",
    "conflicting_findings",
    "limited_dataset_validation",
    "missing_robustness_evaluation",
    "high_compute_cost",
    "benchmark_saturation",
    "insufficient_ablation",
    "inconsistent_evaluation_protocol",
]


class ResearchOpportunityRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    minimum_evidence_papers: int = Field(default=2, ge=2, le=20)

    @model_validator(mode="after")
    def validate_year_range(self) -> "ResearchOpportunityRequest":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not exceed year_to")
        return self


class PaperSelection(BaseModel):
    paper_id: str
    title: str
    year: int
    status: str
    decision: Literal["included", "excluded"]
    reason: str


class CorpusCoverage(BaseModel):
    corpus_id: str
    retrieved_paper_count: int = Field(ge=0)
    included_evidence_paper_count: int = Field(ge=0)
    year_from: int | None
    year_to: int | None
    venues: list[str]
    paper_ids: list[str]


class QueryPlan(BaseModel):
    query: str
    steps: list[str]
    inclusion_rules: list[str]
    exclusion_rules: list[str]
    selections: list[PaperSelection]
    coverage: CorpusCoverage
    possible_omissions: list[str]


class OpportunityEvidence(BaseModel):
    paper_id: str
    paper_title: str
    year: int
    source_statement: str
    relation: Literal["supporting", "conflicting"]
    evidence_anchor: EvidenceAnchor
    matched_rule_terms: list[str]

    @model_validator(mode="after")
    def require_verified_anchor(self) -> "OpportunityEvidence":
        if not self.evidence_anchor.verified:
            raise ValueError("research opportunity evidence must be verified")
        return self


class ConfidenceAssessment(BaseModel):
    score: float = Field(ge=0, le=0.85)
    level: Literal["low", "medium"]
    calculation: str
    basis: list[str]


class ResearchOpportunityCandidate(BaseModel):
    output_type: Literal["research_opportunity_candidate"] = (
        "research_opportunity_candidate"
    )
    candidate_id: str
    candidate_type: OpportunityType
    topic_key: str
    problem_description: str
    evidence_paper_count: int = Field(ge=2)
    supporting_evidence: list[OpportunityEvidence] = Field(min_length=1)
    conflicting_evidence: list[OpportunityEvidence]
    conflict_evidence_note: str
    corpus_coverage: CorpusCoverage
    confidence: ConfidenceAssessment
    human_confirmation_required: list[str] = Field(min_length=1)
    applicable_conditions: list[str] = Field(min_length=1)
    prohibited_conclusions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_count(self) -> "ResearchOpportunityCandidate":
        paper_ids = {
            item.paper_id
            for item in [*self.supporting_evidence, *self.conflicting_evidence]
        }
        if self.evidence_paper_count != len(paper_ids):
            raise ValueError(
                "evidence_paper_count must equal distinct cited evidence papers"
            )
        if self.candidate_type == "conflicting_findings" and not (
            self.supporting_evidence and self.conflicting_evidence
        ):
            raise ValueError(
                "conflicting_findings requires supporting and conflicting evidence"
            )
        return self


class ResearchProgressMilestone(BaseModel):
    milestone_id: str
    year: int
    title: str
    paper_id: str
    venue: str
    summary: str
    evidence_anchors: list[EvidenceAnchor] = Field(min_length=1)


class ResearchOpportunityResponse(BaseModel):
    status: Literal["ok", "insufficient_evidence"]
    result_label: Literal["research_opportunity_candidate_analysis"] = (
        "research_opportunity_candidate_analysis"
    )
    disclaimer: str
    message: str
    query_plan: QueryPlan
    progress_map: list[ResearchProgressMilestone]
    candidates: list[ResearchOpportunityCandidate]

    @model_validator(mode="after")
    def validate_result_state(self) -> "ResearchOpportunityResponse":
        if self.status == "insufficient_evidence" and self.candidates:
            raise ValueError("insufficient_evidence response cannot contain candidates")
        if self.status == "ok" and not self.candidates:
            raise ValueError("ok response requires at least one candidate")
        return self
