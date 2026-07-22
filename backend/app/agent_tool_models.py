from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


EvidenceStatus = Literal["verified", "partial", "insufficient_evidence"]


class AgentToolSource(BaseModel):
    source_id: str
    title: str
    source_type: Literal["paper", "user_claim"]
    verification_status: str
    evidence_ids: list[str] = Field(default_factory=list)


class AgentToolResponse(BaseModel):
    schema_version: Literal["agent-tool-response-v1"] = "agent-tool-response-v1"
    result: dict[str, Any]
    sources: list[AgentToolSource]
    warnings: list[str]
    evidence_status: EvidenceStatus
    trace_id: str
    tool_version: str
    data_version: str


class SearchPapersToolRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class DeconstructPaperToolRequest(BaseModel):
    paper_id: str = Field(min_length=2, max_length=191)
    focus: Literal[
        "full_chain", "claims", "experiments", "artifacts", "boundaries"
    ] = "full_chain"


class ComparePapersToolRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=2, max_length=5)
    comparison_focus: list[
        Literal["problem", "gap", "method", "experiment", "artifact", "boundary"]
    ] = Field(
        default_factory=lambda: [
            "problem",
            "gap",
            "method",
            "experiment",
            "boundary",
        ]
    )

    @model_validator(mode="after")
    def require_distinct_papers(self) -> "ComparePapersToolRequest":
        if len(set(self.paper_ids)) != len(self.paper_ids):
            raise ValueError("paper_ids must be distinct")
        return self


class DiagnoseClaimToolRequest(BaseModel):
    research_question: str = Field(min_length=10, max_length=1500)
    hypothesis: str = Field(min_length=10, max_length=2000)
    proposed_method: str = Field(min_length=2, max_length=2000)
    target_scenario: str = Field(min_length=2, max_length=1500)
