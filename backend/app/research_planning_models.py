from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.research_models import (
    OpportunityEvidence,
    ResearchOpportunityCandidate,
    ResearchOpportunityRequest,
)


ExperimentType = Literal[
    "main_comparison",
    "baseline_coverage",
    "ablation",
    "sensitivity",
    "robustness",
    "failure_case_analysis",
]

ArtifactType = Literal[
    "result_table",
    "ablation_table",
    "sensitivity_curve",
    "robustness_plot",
    "failure_case_panel",
    "tradeoff_plot",
]


class ProjectClaim(BaseModel):
    research_question: str = Field(min_length=10, max_length=1000)
    hypothesis: str = Field(min_length=10, max_length=1500)
    proposed_method: str = Field(min_length=2, max_length=1000)
    origin: Literal["user_supplied"] = "user_supplied"


class ResearchPlanRequest(BaseModel):
    opportunity: ResearchOpportunityRequest
    candidate_id: str = Field(min_length=5, max_length=100)
    project_claim: ProjectClaim


class PlanningEvidenceReference(BaseModel):
    paper_id: str
    evidence_anchor_id: str
    relation: Literal["supporting", "conflicting"]


class PlanningRationale(BaseModel):
    source_candidate_id: str
    inference_type: Literal["system_planning_inference"] = (
        "system_planning_inference"
    )
    evidence_references: list[PlanningEvidenceReference] = Field(min_length=1)
    explanation: str


class PlannedExperiment(BaseModel):
    experiment_id: str
    experiment_type: ExperimentType
    title: str
    validation_goal: str
    design: str
    independent_variables: list[str] = Field(min_length=1)
    dependent_variables: list[str] = Field(min_length=1)
    controlled_variables: list[str] = Field(min_length=1)
    required_inputs: list[str] = Field(min_length=1)
    output_fields: list[str] = Field(min_length=1)
    falsification_criteria: list[str] = Field(min_length=1)
    interpretation_boundary: list[str] = Field(min_length=1)
    rationale: PlanningRationale


class PlannedArtifact(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    validation_goal: str
    source_experiment_ids: list[str] = Field(min_length=1)
    variables: list[str] = Field(min_length=1)
    output_fields: list[str] = Field(min_length=1)
    recommended_encoding: str
    evidence_boundary: list[str] = Field(min_length=1)


class ResearchExperimentPlan(BaseModel):
    output_type: Literal["research_experiment_plan"] = "research_experiment_plan"
    plan_id: str
    source_candidate_id: str
    project_claim: ProjectClaim
    evidence_snapshot: list[OpportunityEvidence] = Field(min_length=1)
    experiments: list[PlannedExperiment] = Field(min_length=1)
    artifacts: list[PlannedArtifact] = Field(min_length=1)
    open_decisions: list[str] = Field(min_length=1)
    global_boundaries: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relationships(self) -> "ResearchExperimentPlan":
        experiment_ids = [item.experiment_id for item in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("experiment IDs must be unique")
        artifact_ids = [item.artifact_id for item in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact IDs must be unique")
        known_experiments = set(experiment_ids)
        for artifact in self.artifacts:
            unknown = set(artifact.source_experiment_ids) - known_experiments
            if unknown:
                raise ValueError(
                    f"artifact {artifact.artifact_id} references unknown experiments: "
                    f"{sorted(unknown)}"
                )
        evidence_keys = {
            (item.paper_id, item.evidence_anchor.id, item.relation)
            for item in self.evidence_snapshot
        }
        for experiment in self.experiments:
            if experiment.rationale.source_candidate_id != self.source_candidate_id:
                raise ValueError("experiment rationale must reference source candidate")
            for reference in experiment.rationale.evidence_references:
                if (
                    reference.paper_id,
                    reference.evidence_anchor_id,
                    reference.relation,
                ) not in evidence_keys:
                    raise ValueError(
                        "experiment rationale references evidence outside snapshot"
                    )
        return self


class ResearchCoachResponse(BaseModel):
    status: Literal["ready_for_review", "insufficient_evidence"]
    result_label: Literal["evidence_grounded_experiment_plan"] = (
        "evidence_grounded_experiment_plan"
    )
    message: str
    project_claim: ProjectClaim
    candidate: ResearchOpportunityCandidate | None
    plan: ResearchExperimentPlan | None

    @model_validator(mode="after")
    def validate_status(self) -> "ResearchCoachResponse":
        if self.status == "insufficient_evidence" and (
            self.candidate is not None or self.plan is not None
        ):
            raise ValueError("insufficient_evidence cannot include a candidate or plan")
        if self.status == "ready_for_review" and (
            self.candidate is None or self.plan is None
        ):
            raise ValueError("ready_for_review requires a candidate and plan")
        if self.candidate is not None and self.plan is not None:
            if self.plan.source_candidate_id != self.candidate.candidate_id:
                raise ValueError("plan must reference the returned candidate")
            if self.plan.project_claim != self.project_claim:
                raise ValueError("plan must preserve the submitted project claim")
            candidate_evidence = {
                (item.paper_id, item.evidence_anchor.id, item.relation)
                for item in [
                    *self.candidate.supporting_evidence,
                    *self.candidate.conflicting_evidence,
                ]
            }
            plan_evidence = {
                (item.paper_id, item.evidence_anchor.id, item.relation)
                for item in self.plan.evidence_snapshot
            }
            if plan_evidence != candidate_evidence:
                raise ValueError("plan evidence snapshot must equal candidate evidence")
        return self
