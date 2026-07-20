from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PlanItemStatus = Literal["suggested", "confirmed", "modified", "rejected"]
QualityCheckType = Literal[
    "missing_strong_baseline",
    "data_leakage",
    "unfair_setup",
    "metric_inconsistency",
    "overclaiming",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimPlanReference(StrictModel):
    claim_version_id: str
    claim_id: str
    version: int = Field(ge=1)
    research_question: str
    hypothesis: str


class DatasetPlan(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=255)
    role: Literal["primary", "robustness", "external_validation"]
    split_protocol: str = Field(min_length=1, max_length=2000)
    preprocessing_fit_scope: Literal["training_only", "full_dataset", "unspecified"]
    temporal_order: Literal["preserved", "not_applicable", "violated", "unspecified"]


class BaselinePlan(StrictModel):
    baseline_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=500)
    strength_rationale: str = Field(min_length=1, max_length=2000)
    implementation_source: str = Field(min_length=1, max_length=1000)
    status: Literal["included", "excluded"] = "included"


class VariablesPlan(StrictModel):
    independent: list[str] = Field(min_length=1)
    dependent: list[str] = Field(min_length=1)
    nuisance: list[str] = Field(min_length=1)


class ControlsPlan(StrictModel):
    data_split: str = Field(min_length=1, max_length=2000)
    preprocessing: str = Field(min_length=1, max_length=2000)
    tuning_budget: str = Field(min_length=1, max_length=2000)
    compute_budget: str = Field(min_length=1, max_length=2000)
    evaluation_protocol: str = Field(min_length=1, max_length=2000)
    applies_equally: Literal["planned", "not_planned", "unspecified"]


class MetricPlan(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    direction: Literal["higher_is_better", "lower_is_better", "descriptive"]
    applies_to: Literal["all_methods", "proposed_method_only", "baselines_only"]


class BoundaryPlan(StrictModel):
    applicability_conditions: list[str] = Field(min_length=1)
    can_support: list[str] = Field(min_length=1)
    cannot_support: list[str] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)


class ExperimentPlan(StrictModel):
    experiment_id: str
    claim_version_ids: list[str] = Field(min_length=1)
    research_questions: list[str] = Field(min_length=1)
    hypotheses: list[str] = Field(min_length=1)
    datasets: list[DatasetPlan] = Field(min_length=1)
    baselines: list[BaselinePlan]
    variables: VariablesPlan
    controls: ControlsPlan
    metrics: list[MetricPlan] = Field(min_length=1)
    expected_artifact_ids: list[str] = Field(min_length=1)
    boundary: BoundaryPlan
    status: PlanItemStatus = "suggested"
    generated_by_requirement_ids: list[str] = Field(min_length=1)


class ArtifactPlan(StrictModel):
    artifact_id: str
    source_experiment_ids: list[str] = Field(min_length=1)
    artifact_kind: Literal["figure", "table"]
    form_reason: str = Field(min_length=1, max_length=3000)
    x_axis: str | None = Field(default=None, max_length=1000)
    y_axis: str | None = Field(default=None, max_length=1000)
    rows: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    data_fields: list[str] = Field(min_length=1)
    supports_claim_version_ids: list[str] = Field(min_length=1)
    common_misreadings: list[str] = Field(min_length=1)
    status: PlanItemStatus = "suggested"

    @model_validator(mode="after")
    def validate_layout(self) -> "ArtifactPlan":
        if self.artifact_kind == "figure" and (not self.x_axis or not self.y_axis):
            raise ValueError("figure artifacts require x_axis and y_axis")
        if self.artifact_kind == "table" and (not self.rows or not self.columns):
            raise ValueError("table artifacts require rows and columns")
        return self


class DiagnosisBasis(StrictModel):
    claim_version_id: str
    diagnosis_id: str
    diagnosis_revision: int = Field(ge=1)


class GenerationBasis(StrictModel):
    planner_version: Literal["project-experiment-artifact-rules-v1"] = (
        "project-experiment-artifact-rules-v1"
    )
    diagnosis_versions: list[DiagnosisBasis] = Field(min_length=1)
    source_requirement_ids: list[str] = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    result_policy: Literal["plan_only_no_results_or_expected_values"] = (
        "plan_only_no_results_or_expected_values"
    )


class QualityCheck(StrictModel):
    check_type: QualityCheckType
    status: Literal["pass", "warning", "error"]
    experiment_id: str
    message: str
    remediation: str
    rule_id: str


class PlanQualityReport(StrictModel):
    checker_version: Literal["experiment-plan-quality-rules-v1"] = (
        "experiment-plan-quality-rules-v1"
    )
    checks: list[QualityCheck]
    has_errors: bool


class ExperimentPlanBundle(StrictModel):
    plan_id: str
    plan_revision_id: str
    project_id: str
    revision: int = Field(ge=1)
    supersedes_plan_revision_id: str | None
    origin: Literal["rule_generated", "user_edited"]
    claim_references: list[ClaimPlanReference] = Field(min_length=1)
    generation_basis: GenerationBasis
    experiments: list[ExperimentPlan] = Field(min_length=1)
    artifacts: list[ArtifactPlan] = Field(min_length=1)
    quality_report: PlanQualityReport
    created_at: datetime

    @model_validator(mode="after")
    def validate_relationship_closure(self) -> "ExperimentPlanBundle":
        if self.revision == 1 and self.supersedes_plan_revision_id is not None:
            raise ValueError("revision 1 cannot supersede another plan revision")
        if self.revision > 1 and self.supersedes_plan_revision_id is None:
            raise ValueError("later plan revisions must identify their parent")

        references = {item.claim_version_id: item for item in self.claim_references}
        if len(references) != len(self.claim_references):
            raise ValueError("claim references must be unique")
        experiment_ids = {item.experiment_id for item in self.experiments}
        artifact_ids = {item.artifact_id for item in self.artifacts}
        if len(experiment_ids) != len(self.experiments):
            raise ValueError("experiment IDs must be unique")
        if len(artifact_ids) != len(self.artifacts):
            raise ValueError("artifact IDs must be unique")

        experiment_by_id = {item.experiment_id: item for item in self.experiments}
        artifact_by_id = {item.artifact_id: item for item in self.artifacts}
        for experiment in self.experiments:
            if not set(experiment.claim_version_ids) <= references.keys():
                raise ValueError("experiment references an unknown Claim version")
            expected_rqs = {
                references[item].research_question for item in experiment.claim_version_ids
            }
            expected_hypotheses = {
                references[item].hypothesis for item in experiment.claim_version_ids
            }
            if set(experiment.research_questions) != expected_rqs:
                raise ValueError("experiment RQ must preserve linked Claim text")
            if set(experiment.hypotheses) != expected_hypotheses:
                raise ValueError("experiment Hypothesis must preserve linked Claim text")
            if not set(experiment.expected_artifact_ids) <= artifact_ids:
                raise ValueError("experiment references an unknown ArtifactPlan")
            for artifact_id in experiment.expected_artifact_ids:
                if experiment.experiment_id not in artifact_by_id[artifact_id].source_experiment_ids:
                    raise ValueError("ExperimentPlan and ArtifactPlan links must be reciprocal")
                if not set(experiment.claim_version_ids) <= set(
                    artifact_by_id[artifact_id].supports_claim_version_ids
                ):
                    raise ValueError("expected ArtifactPlan must support the ExperimentPlan Claims")

        for artifact in self.artifacts:
            if not set(artifact.source_experiment_ids) <= experiment_ids:
                raise ValueError("artifact references an unknown ExperimentPlan")
            if not set(artifact.supports_claim_version_ids) <= references.keys():
                raise ValueError("artifact references an unknown Claim version")
            source_claims = {
                claim_version_id
                for experiment_id in artifact.source_experiment_ids
                for claim_version_id in experiment_by_id[experiment_id].claim_version_ids
            }
            if not set(artifact.supports_claim_version_ids) <= source_claims:
                raise ValueError("ArtifactPlan Claims must come from source ExperimentPlans")
        return self


class ExperimentPlanGenerateRequest(StrictModel):
    expected_latest_revision: int = Field(ge=0)
    claim_versions: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_versions(self) -> "ExperimentPlanGenerateRequest":
        if len(set(self.claim_versions)) != len(self.claim_versions):
            raise ValueError("claim_versions must be unique")
        return self


class ExperimentPlanEditRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    experiments: list[ExperimentPlan] = Field(min_length=1)
    artifacts: list[ArtifactPlan] = Field(min_length=1)


class ExperimentPlanHistory(StrictModel):
    project_id: str
    revisions: list[ExperimentPlanBundle]
