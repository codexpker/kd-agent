from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


EvidenceRequirementType = Literal[
    "main_experiment",
    "strong_baseline",
    "fair_comparison",
    "ablation",
    "parameter_sensitivity",
    "robustness",
    "efficiency",
    "failure_cases",
]

RequirementStatus = Literal[
    "planned",
    "in_progress",
    "user_reports_evidence_available",
    "not_applicable",
]


class ExistingResult(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=3000)
    result_type: Literal[
        "observation", "quantitative", "partial", "negative", "other"
    ]
    source: Literal["user_reported"] = "user_reported"
    verified: Literal[False] = False


class ProjectClaimInput(BaseModel):
    research_question: str = Field(min_length=10, max_length=1500)
    hypothesis: str = Field(min_length=10, max_length=2000)
    proposed_method: str = Field(min_length=2, max_length=2000)
    target_scenario: str = Field(min_length=2, max_length=1500)
    existing_results: list[ExistingResult] = Field(default_factory=list, max_length=50)


class ProjectClaimCreateRequest(BaseModel):
    expected_latest_version: int = Field(ge=0)
    claim: ProjectClaimInput


class ProjectClaimVersion(ProjectClaimInput):
    project_id: str
    claim_id: str
    claim_version_id: str
    version: int = Field(ge=1)
    supersedes_claim_version_id: str | None
    origin: Literal["user_supplied"] = "user_supplied"
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_version_chain(self) -> "ProjectClaimVersion":
        if self.version == 1 and self.supersedes_claim_version_id is not None:
            raise ValueError("version 1 cannot supersede another claim version")
        if self.version > 1 and self.supersedes_claim_version_id is None:
            raise ValueError("later versions must identify the superseded version")
        return self


class RecommendedArtifact(BaseModel):
    artifact_type: Literal[
        "table",
        "line_chart",
        "bar_chart",
        "heatmap",
        "scatter_plot",
        "case_panel",
    ]
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)


class EvidenceRequirement(BaseModel):
    requirement_id: str
    requirement_type: EvidenceRequirementType
    validates_claim_version_id: str
    validates_claim: str
    why_needed: str = Field(min_length=1, max_length=3000)
    independent_variables: list[str] = Field(min_length=1)
    controlled_variables: list[str] = Field(min_length=1)
    output_fields: list[str] = Field(min_length=1)
    recommended_artifact: RecommendedArtifact
    can_support: list[str] = Field(min_length=1)
    cannot_support: list[str] = Field(min_length=1)
    status: RequirementStatus = "planned"
    user_notes: str = Field(default="", max_length=5000)
    generated_by_rule: str


class EvidenceRequirementEdit(BaseModel):
    requirement_type: EvidenceRequirementType
    why_needed: str = Field(min_length=1, max_length=3000)
    independent_variables: list[str] = Field(min_length=1)
    controlled_variables: list[str] = Field(min_length=1)
    output_fields: list[str] = Field(min_length=1)
    recommended_artifact: RecommendedArtifact
    can_support: list[str] = Field(min_length=1)
    cannot_support: list[str] = Field(min_length=1)
    status: RequirementStatus
    user_notes: str = Field(default="", max_length=5000)


class EvidenceDiagnosisVersion(BaseModel):
    diagnosis_id: str
    claim_version_id: str
    revision: int = Field(ge=1)
    origin: Literal["rule_generated", "user_edited"]
    planner_version: Literal["project-claim-evidence-rules-v1"] = (
        "project-claim-evidence-rules-v1"
    )
    language_organizer: Literal["deterministic_templates"] = (
        "deterministic_templates"
    )
    requirements: list[EvidenceRequirement]
    feasibility_assessment: Literal["not_assessed"] = "not_assessed"
    innovation_assessment: Literal["not_assessed"] = "not_assessed"
    created_at: datetime

    @model_validator(mode="after")
    def validate_minimum_evidence_set(self) -> "EvidenceDiagnosisVersion":
        expected = {
            "main_experiment",
            "strong_baseline",
            "fair_comparison",
            "ablation",
            "parameter_sensitivity",
            "robustness",
            "efficiency",
            "failure_cases",
        }
        actual = {item.requirement_type for item in self.requirements}
        if actual != expected or len(self.requirements) != len(expected):
            raise ValueError("diagnosis must contain each minimum evidence type exactly once")
        if any(
            item.validates_claim_version_id != self.claim_version_id
            for item in self.requirements
        ):
            raise ValueError("all requirements must reference the diagnosed claim version")
        return self


class EvidenceDiagnosisEditRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    requirements: list[EvidenceRequirementEdit]


class ProjectClaimEnvelope(BaseModel):
    claim: ProjectClaimVersion
    diagnosis: EvidenceDiagnosisVersion

    @model_validator(mode="after")
    def validate_claim_link(self) -> "ProjectClaimEnvelope":
        if self.diagnosis.claim_version_id != self.claim.claim_version_id:
            raise ValueError("diagnosis must reference the returned claim version")
        return self


class ProjectClaimHistory(BaseModel):
    project_id: str
    versions: list[ProjectClaimVersion]


class TadProjectClaimExample(BaseModel):
    example_kind: Literal["synthetic_tad_project_claim_example"] = (
        "synthetic_tad_project_claim_example"
    )
    disclaimer: str
    claim: ProjectClaimInput
