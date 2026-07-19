from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PaperSource(BaseModel):
    source_key: str = Field(min_length=1, max_length=191)
    source_type: Literal[
        "official_publication",
        "curated_registry",
        "openreview",
        "crossref",
        "arxiv",
        "openalex",
        "model_extracted",
    ]
    source_uri: str | None = None
    external_id: str | None = None
    license_name: str | None = None
    access_policy: Literal[
        "metadata_only",
        "open_full_text",
        "user_private_copy",
        "institution_authorized",
        "unknown",
    ]
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value.astimezone(UTC)


class EvidenceAnchor(BaseModel):
    id: str
    kind: Literal["section", "sentence", "figure", "table", "caption", "reference"]
    label: str
    excerpt: str
    page: int | None = None
    verified: bool = False


class NarrativeMove(BaseModel):
    id: str
    order: int = Field(ge=1)
    move: str
    purpose: str
    evidence_ids: list[str]


class Claim(BaseModel):
    id: str
    claim_type: Literal["problem", "gap", "method", "result", "boundary"]
    statement: str
    evidence_ids: list[str]


class ExperimentIntent(BaseModel):
    id: str
    title: str
    question: str
    design_reason: str
    variables: list[str]
    supports_claim_ids: list[str]
    evidence_ids: list[str]


class ArtifactRole(BaseModel):
    id: str
    artifact_type: Literal["figure", "table"]
    label: str
    role: str
    why_here: str
    supports_claim_ids: list[str]
    evidence_ids: list[str]


class PaperDeconstruction(BaseModel):
    dataset_version: str
    paper_id: str
    title: str
    venue: str
    year: int
    status: Literal["development_seed", "double_annotated", "frozen"]
    narrative_moves: list[NarrativeMove]
    claims: list[Claim]
    experiment_intents: list[ExperimentIntent]
    artifacts: list[ArtifactRole]
    evidence: list[EvidenceAnchor]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_graph(self) -> "PaperDeconstruction":
        evidence_ids = {item.id for item in self.evidence}
        claim_ids = {item.id for item in self.claims}
        if len(evidence_ids) != len(self.evidence) or len(claim_ids) != len(self.claims):
            raise ValueError("duplicate evidence or claim id")
        expected_orders = list(range(1, len(self.narrative_moves) + 1))
        if [item.order for item in self.narrative_moves] != expected_orders:
            raise ValueError("narrative move order must be contiguous")
        for item in [*self.narrative_moves, *self.claims, *self.experiment_intents, *self.artifacts]:
            unknown = set(item.evidence_ids) - evidence_ids
            if unknown:
                raise ValueError(f"unknown evidence ids: {sorted(unknown)}")
        for item in [*self.experiment_intents, *self.artifacts]:
            unknown = set(item.supports_claim_ids) - claim_ids
            if unknown:
                raise ValueError(f"unknown claim ids: {sorted(unknown)}")
        return self


class Section(BaseModel):
    id: str
    title: str
    level: int = Field(ge=1)
    page_start: int | None = None
    page_end: int | None = None


class DocumentArtifact(BaseModel):
    id: str
    artifact_type: Literal["figure", "table"]
    label: str
    caption: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    markdown: str | None = None


class DocumentReference(BaseModel):
    id: str
    artifact_id: str
    text: str
    page: int | None = None


class DocumentStructure(BaseModel):
    paper_id: str
    source: Literal["parsed_pdf", "gold_snapshot"]
    parser_name: str | None = None
    parser_version: str | None = None
    file_sha256: str | None = None
    sections: list[Section]
    artifacts: list[DocumentArtifact]
    references: list[DocumentReference]
    evidence: list[EvidenceAnchor]
    warnings: list[str] = []


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    paper_id: str
    title: str
    year: int
    venue: str
    snippet: str
    has_gold: bool


class SearchResponse(BaseModel):
    query: str
    backend: str
    hits: list[SearchHit]
