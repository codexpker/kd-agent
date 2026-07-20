import hashlib
import re
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from app.experiment_plan_models import (
    ArtifactPlan,
    BaselinePlan,
    BoundaryPlan,
    ClaimPlanReference,
    ControlsPlan,
    DatasetPlan,
    DiagnosisBasis,
    ExperimentPlan,
    ExperimentPlanBundle,
    ExperimentPlanEditRequest,
    ExperimentPlanGenerateRequest,
    ExperimentPlanHistory,
    GenerationBasis,
    MetricPlan,
    PlanQualityReport,
    QualityCheck,
    VariablesPlan,
)
from app.project_claim_models import EvidenceRequirementType
from app.services.project_claims import ProjectClaimNotFoundError, ProjectClaimService


class ExperimentPlanNotFoundError(LookupError):
    pass


class ExperimentPlanVersionConflictError(RuntimeError):
    pass


class ExperimentPlanStore(Protocol):
    def latest(self, project_id: str) -> ExperimentPlanBundle | None: ...

    def list_revisions(self, project_id: str) -> list[ExperimentPlanBundle]: ...

    def get(self, project_id: str, revision: int) -> ExperimentPlanBundle | None: ...

    def save(
        self, plan: ExperimentPlanBundle, expected_latest_revision: int
    ) -> None: ...


class InMemoryExperimentPlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, list[ExperimentPlanBundle]] = {}
        self._lock = RLock()

    def latest(self, project_id: str) -> ExperimentPlanBundle | None:
        with self._lock:
            revisions = self._plans.get(project_id, [])
            return revisions[-1].model_copy(deep=True) if revisions else None

    def list_revisions(self, project_id: str) -> list[ExperimentPlanBundle]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._plans.get(project_id, [])]

    def get(self, project_id: str, revision: int) -> ExperimentPlanBundle | None:
        with self._lock:
            result = next(
                (item for item in self._plans.get(project_id, []) if item.revision == revision),
                None,
            )
            return result.model_copy(deep=True) if result else None

    def save(
        self, plan: ExperimentPlanBundle, expected_latest_revision: int
    ) -> None:
        with self._lock:
            revisions = self._plans.setdefault(plan.project_id, [])
            actual = revisions[-1].revision if revisions else 0
            if actual != expected_latest_revision:
                raise ExperimentPlanVersionConflictError(
                    f"Expected latest plan revision {expected_latest_revision}, got {actual}"
                )
            if plan.revision != actual + 1:
                raise ExperimentPlanVersionConflictError(
                    "Plan revision must increment the latest revision by one"
                )
            revisions.append(plan.model_copy(deep=True))


REQUIREMENT_ORDER: tuple[EvidenceRequirementType, ...] = (
    "main_experiment",
    "strong_baseline",
    "fair_comparison",
    "ablation",
    "parameter_sensitivity",
    "robustness",
    "efficiency",
    "failure_cases",
)


class ExperimentPlanQualityChecker:
    version = "experiment-plan-quality-rules-v1"

    def evaluate(self, experiments: list[ExperimentPlan]) -> PlanQualityReport:
        checks: list[QualityCheck] = []
        for experiment in experiments:
            checks.extend(
                [
                    self._baseline_check(experiment),
                    self._leakage_check(experiment),
                    self._fairness_check(experiment),
                    self._metric_check(experiment),
                    self._overclaim_check(experiment),
                ]
            )
        return PlanQualityReport(
            checks=checks,
            has_errors=any(item.status == "error" for item in checks),
        )

    @staticmethod
    def _check(
        experiment: ExperimentPlan,
        check_type: str,
        passed: bool,
        message: str,
        remediation: str,
        rule_id: str,
        *,
        error: bool = False,
    ) -> QualityCheck:
        return QualityCheck(
            check_type=check_type,
            status="pass" if passed else ("error" if error else "warning"),
            experiment_id=experiment.experiment_id,
            message=message,
            remediation=remediation,
            rule_id=rule_id,
        )

    def _baseline_check(self, experiment: ExperimentPlan) -> QualityCheck:
        included = [item for item in experiment.baselines if item.status == "included"]
        passed = bool(included) and all(
            item.strength_rationale.strip() and item.implementation_source.strip()
            for item in included
        )
        return self._check(
            experiment,
            "missing_strong_baseline",
            passed,
            (
                "At least one included baseline has a disclosed strength rationale and implementation source."
                if passed
                else "No included strong baseline with a disclosed rationale and implementation source is planned."
            ),
            "Add at least one relevant strong baseline and record why and where its implementation comes from.",
            "plan-check-strong-baseline-v1",
        )

    def _leakage_check(self, experiment: ExperimentPlan) -> QualityCheck:
        passed = all(
            item.preprocessing_fit_scope == "training_only"
            and item.temporal_order in {"preserved", "not_applicable"}
            for item in experiment.datasets
        )
        return self._check(
            experiment,
            "data_leakage",
            passed,
            (
                "Training-only preprocessing and temporal split constraints are planned."
                if passed
                else "A dataset permits full-data preprocessing, violates temporal order, or leaves leakage controls unspecified."
            ),
            "Fit preprocessing only on training data and preserve temporal order where applicable.",
            "plan-check-data-leakage-v1",
            error=any(
                item.preprocessing_fit_scope == "full_dataset"
                or item.temporal_order == "violated"
                for item in experiment.datasets
            ),
        )

    def _fairness_check(self, experiment: ExperimentPlan) -> QualityCheck:
        passed = experiment.controls.applies_equally == "planned"
        return self._check(
            experiment,
            "unfair_setup",
            passed,
            (
                "Shared data, preprocessing, tuning, compute and evaluation controls are explicitly planned."
                if passed
                else "Equal comparison conditions are rejected or unspecified."
            ),
            "Use the same split, preprocessing, tuning/compute budget and evaluation protocol for every method.",
            "plan-check-fair-setting-v1",
            error=experiment.controls.applies_equally == "not_planned",
        )

    def _metric_check(self, experiment: ExperimentPlan) -> QualityCheck:
        names = [item.name.casefold().strip() for item in experiment.metrics]
        passed = len(names) == len(set(names)) and all(
            item.applies_to == "all_methods" for item in experiment.metrics
        )
        return self._check(
            experiment,
            "metric_inconsistency",
            passed,
            (
                "Metric definitions are unique and planned for all compared methods."
                if passed
                else "Metrics are duplicated or are not applied uniformly to all methods."
            ),
            "Predeclare one definition and direction per metric and apply it to every compared method.",
            "plan-check-metric-consistency-v1",
        )

    def _overclaim_check(self, experiment: ExperimentPlan) -> QualityCheck:
        absolute = re.compile(
            r"\b(always|all datasets|guarantee[sd]?|prove[sd]?|universally)\b|"
            r"(必然|所有数据集|保证|证明了|普遍优于)",
            re.IGNORECASE,
        )
        found = any(absolute.search(item) for item in experiment.hypotheses)
        bounded = bool(
            experiment.boundary.applicability_conditions
            and experiment.boundary.cannot_support
            and experiment.boundary.stop_conditions
        )
        passed = bounded and not found
        return self._check(
            experiment,
            "overclaiming",
            passed,
            (
                "The plan has explicit applicability, non-conclusion and stop boundaries."
                if passed
                else "Absolute Claim language or an incomplete interpretation boundary requires review."
            ),
            "Narrow the Claim to tested conditions and list conclusions that the planned evidence cannot support.",
            "plan-check-overclaim-v1",
        )


class ExperimentArtifactPlanner:
    version = "project-experiment-artifact-rules-v1"

    def __init__(self, checker: ExperimentPlanQualityChecker | None = None) -> None:
        self.checker = checker or ExperimentPlanQualityChecker()

    def generate(
        self,
        project_id: str,
        envelopes: list,
        *,
        revision: int,
        parent_id: str | None,
        now: datetime | None = None,
    ) -> ExperimentPlanBundle:
        created_at = now or datetime.now(UTC)
        plan_id = f"experiment-plan-{hashlib.sha256(project_id.encode()).hexdigest()[:20]}"
        references = [
            ClaimPlanReference(
                claim_version_id=item.claim.claim_version_id,
                claim_id=item.claim.claim_id,
                version=item.claim.version,
                research_question=item.claim.research_question,
                hypothesis=item.claim.hypothesis,
            )
            for item in envelopes
        ]
        by_type = {
            requirement_type: [
                requirement
                for envelope in envelopes
                for requirement in envelope.diagnosis.requirements
                if requirement.requirement_type == requirement_type
            ]
            for requirement_type in REQUIREMENT_ORDER
        }
        all_claim_ids = [item.claim_version_id for item in references]
        experiments: list[ExperimentPlan] = []
        artifacts: list[ArtifactPlan] = []
        is_temporal = any(
            re.search(r"time[- ]?series|temporal|sensor|时间序列|时序", item.claim.target_scenario, re.I)
            for item in envelopes
        )
        for requirement_type in REQUIREMENT_ORDER:
            requirements = by_type[requirement_type]
            primary = requirements[0]
            experiment_id = f"{plan_id}:experiment:{requirement_type}"
            artifact_id = f"{plan_id}:artifact:{requirement_type}"
            artifact_kind = (
                "table" if primary.recommended_artifact.artifact_type == "table" else "figure"
            )
            output_fields = list(dict.fromkeys(
                field for item in requirements for field in item.output_fields
            ))
            independent = list(dict.fromkeys(
                field for item in requirements for field in item.independent_variables
            ))
            controls = list(dict.fromkeys(
                field for item in requirements for field in item.controlled_variables
            ))
            experiments.append(
                ExperimentPlan(
                    experiment_id=experiment_id,
                    claim_version_ids=all_claim_ids,
                    research_questions=[item.research_question for item in references],
                    hypotheses=[item.hypothesis for item in references],
                    datasets=[
                        DatasetPlan(
                            dataset_id="dataset_pending_user_selection",
                            role="primary",
                            split_protocol="Predeclare train/validation/test units before execution.",
                            preprocessing_fit_scope="training_only",
                            temporal_order="preserved" if is_temporal else "not_applicable",
                        )
                    ],
                    baselines=[
                        BaselinePlan(
                            baseline_id="strong_baseline_pending_user_selection",
                            label="Strong baseline to be confirmed by the user",
                            strength_rationale="A relevant competitive method must be selected before confirmation.",
                            implementation_source="Implementation source must be recorded before confirmation.",
                            status="excluded",
                        )
                    ],
                    variables=VariablesPlan(
                        independent=independent,
                        dependent=output_fields,
                        nuisance=controls,
                    ),
                    controls=ControlsPlan(
                        data_split="Use the same predeclared split for all compared methods.",
                        preprocessing="Fit preprocessing on training data and reuse it unchanged.",
                        tuning_budget="Use the same disclosed search budget and stopping rule.",
                        compute_budget="Use the same disclosed hardware and resource ceiling.",
                        evaluation_protocol="Use one predeclared metric implementation and threshold policy.",
                        applies_equally="planned",
                    ),
                    metrics=[
                        MetricPlan(
                            name="primary_metric_to_predeclare",
                            direction="descriptive",
                            applies_to="all_methods",
                        )
                    ],
                    expected_artifact_ids=[artifact_id],
                    boundary=BoundaryPlan(
                        applicability_conditions=[
                            envelope.claim.target_scenario for envelope in envelopes
                        ],
                        can_support=list(dict.fromkeys(
                            conclusion for item in requirements for conclusion in item.can_support
                        )),
                        cannot_support=list(dict.fromkeys(
                            conclusion for item in requirements for conclusion in item.cannot_support
                        )),
                        stop_conditions=[
                            "Stop interpretation if a disclosed control differs across methods.",
                            "Stop interpretation if required runs or fields are missing.",
                        ],
                    ),
                    generated_by_requirement_ids=[item.requirement_id for item in requirements],
                )
            )
            artifacts.append(
                ArtifactPlan(
                    artifact_id=artifact_id,
                    source_experiment_ids=[experiment_id],
                    artifact_kind=artifact_kind,
                    form_reason=primary.recommended_artifact.rationale,
                    x_axis=(independent[0] if artifact_kind == "figure" else None),
                    y_axis=("predeclared metric (no value generated)" if artifact_kind == "figure" else None),
                    rows=(["method or configuration", "dataset or scenario"] if artifact_kind == "table" else []),
                    columns=(output_fields if artifact_kind == "table" else []),
                    data_fields=output_fields,
                    supports_claim_version_ids=all_claim_ids,
                    common_misreadings=list(dict.fromkeys(
                        conclusion for item in requirements for conclusion in item.cannot_support
                    )),
                )
            )

        quality = self.checker.evaluate(experiments)
        return ExperimentPlanBundle(
            plan_id=plan_id,
            plan_revision_id=f"{plan_id}:r{revision}",
            project_id=project_id,
            revision=revision,
            supersedes_plan_revision_id=parent_id,
            origin="rule_generated",
            claim_references=references,
            generation_basis=GenerationBasis(
                diagnosis_versions=[
                    DiagnosisBasis(
                        claim_version_id=item.claim.claim_version_id,
                        diagnosis_id=item.diagnosis.diagnosis_id,
                        diagnosis_revision=item.diagnosis.revision,
                    )
                    for item in envelopes
                ],
                source_requirement_ids=[
                    requirement.requirement_id
                    for envelope in envelopes
                    for requirement in envelope.diagnosis.requirements
                ],
                rule_ids=[
                    requirement.generated_by_rule
                    for envelope in envelopes
                    for requirement in envelope.diagnosis.requirements
                ],
            ),
            experiments=experiments,
            artifacts=artifacts,
            quality_report=quality,
            created_at=created_at,
        )


class ExperimentPlanService:
    def __init__(
        self,
        store: ExperimentPlanStore,
        claim_service: ProjectClaimService,
        planner: ExperimentArtifactPlanner | None = None,
    ) -> None:
        self.store = store
        self.claim_service = claim_service
        self.planner = planner or ExperimentArtifactPlanner()

    def generate(
        self, project_id: str, request: ExperimentPlanGenerateRequest
    ) -> ExperimentPlanBundle:
        latest = self.store.latest(project_id)
        actual = latest.revision if latest else 0
        if actual != request.expected_latest_revision:
            raise ExperimentPlanVersionConflictError(
                f"Expected latest plan revision {request.expected_latest_revision}, got {actual}"
            )
        envelopes = []
        for version in request.claim_versions:
            try:
                envelopes.append(self.claim_service.get(project_id, version))
            except ProjectClaimNotFoundError as exc:
                raise ProjectClaimNotFoundError(
                    f"Project Claim version {version} was not found"
                ) from exc
        plan = self.planner.generate(
            project_id,
            envelopes,
            revision=actual + 1,
            parent_id=latest.plan_revision_id if latest else None,
        )
        self.store.save(plan, request.expected_latest_revision)
        return plan

    def history(self, project_id: str) -> ExperimentPlanHistory:
        self.claim_service.history(project_id)
        return ExperimentPlanHistory(
            project_id=project_id,
            revisions=self.store.list_revisions(project_id),
        )

    def get(self, project_id: str, revision: int) -> ExperimentPlanBundle:
        self.claim_service.history(project_id)
        result = self.store.get(project_id, revision)
        if result is None:
            raise ExperimentPlanNotFoundError("Experiment plan revision was not found")
        return result

    def edit(
        self,
        project_id: str,
        revision: int,
        request: ExperimentPlanEditRequest,
    ) -> ExperimentPlanBundle:
        current = self.get(project_id, revision)
        latest = self.store.latest(project_id)
        actual = latest.revision if latest else 0
        if request.expected_revision != actual or revision != actual:
            raise ExperimentPlanVersionConflictError(
                f"Expected editable plan revision {request.expected_revision}, got {actual}"
            )
        if {item.experiment_id for item in request.experiments} != {
            item.experiment_id for item in current.experiments
        }:
            raise ValueError("Experiment IDs cannot be added or removed during an edit")
        if {item.artifact_id for item in request.artifacts} != {
            item.artifact_id for item in current.artifacts
        }:
            raise ValueError("Artifact IDs cannot be added or removed during an edit")
        generated_by = {
            item.experiment_id: item.generated_by_requirement_ids
            for item in current.experiments
        }
        experiments = [
            item.model_copy(
                update={"generated_by_requirement_ids": generated_by[item.experiment_id]}
            )
            for item in request.experiments
        ]
        updated = ExperimentPlanBundle(
            plan_id=current.plan_id,
            plan_revision_id=f"{current.plan_id}:r{actual + 1}",
            project_id=project_id,
            revision=actual + 1,
            supersedes_plan_revision_id=current.plan_revision_id,
            origin="user_edited",
            claim_references=current.claim_references,
            generation_basis=current.generation_basis,
            experiments=experiments,
            artifacts=request.artifacts,
            quality_report=self.planner.checker.evaluate(experiments),
            created_at=datetime.now(UTC),
        )
        self.store.save(updated, actual)
        return updated
