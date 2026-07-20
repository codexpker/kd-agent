import hashlib
from dataclasses import dataclass

from app.research_models import OpportunityType, ResearchOpportunityCandidate
from app.research_planning_models import (
    PlannedArtifact,
    PlannedExperiment,
    PlanningEvidenceReference,
    PlanningRationale,
    ResearchPlanClaimInput,
    ResearchCoachResponse,
    ResearchExperimentPlan,
    ResearchPlanRequest,
)
from app.services.research_opportunities import (
    ResearchCorpus,
    ResearchOpportunityService,
)


class CandidateNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PlanningContext:
    comparison_axis: str
    robustness_axis: str
    boundary: str


CONTEXTS: dict[OpportunityType, PlanningContext] = {
    "shared_unresolved_limitation": PlanningContext(
        comparison_axis="training domain versus held-out deployment domain",
        robustness_axis="domain shift severity and unseen domain",
        boundary="Results apply only to the predeclared source and target domains.",
    ),
    "conflicting_findings": PlanningContext(
        comparison_axis="alternative evaluation protocols on identical raw predictions",
        robustness_axis="label granularity and thresholding protocol",
        boundary="Protocol effects cannot be interpreted as model effects.",
    ),
    "limited_dataset_validation": PlanningContext(
        comparison_axis="dataset family and deployment context",
        robustness_axis="dataset diversity and leave-one-dataset-out transfer",
        boundary="Coverage is limited to the explicitly selected datasets.",
    ),
    "missing_robustness_evaluation": PlanningContext(
        comparison_axis="clean inputs versus controlled stress conditions",
        robustness_axis="candidate-specific corruption level or distribution shift",
        boundary="Synthetic stress tests do not establish real deployment robustness.",
    ),
    "high_compute_cost": PlanningContext(
        comparison_axis="accuracy under fixed training and inference budgets",
        robustness_axis="hardware, batch size, sequence length and resource budget",
        boundary="Runtime comparisons apply only to disclosed hardware and software.",
    ),
    "benchmark_saturation": PlanningContext(
        comparison_axis="common benchmarks versus predeclared realistic scenarios",
        robustness_axis="scenario realism, prevalence and label quality",
        boundary="A selected real scenario cannot represent all deployments.",
    ),
    "insufficient_ablation": PlanningContext(
        comparison_axis="full method versus controlled component combinations",
        robustness_axis="component interactions across datasets and seeds",
        boundary="Ablation association alone does not establish causal mechanism.",
    ),
    "inconsistent_evaluation_protocol": PlanningContext(
        comparison_axis="models rescored under one predeclared common protocol",
        robustness_axis="preprocessing, thresholding and metric definitions",
        boundary="Re-scoring does not reproduce unreported training choices.",
    ),
}


class ResearchPlanningService:
    def __init__(self, corpus: ResearchCorpus) -> None:
        self.corpus = corpus

    def create(self, request: ResearchPlanRequest) -> ResearchCoachResponse:
        opportunity_result = ResearchOpportunityService(self.corpus).analyze(
            request.opportunity
        )
        if opportunity_result.status == "insufficient_evidence":
            return ResearchCoachResponse(
                status="insufficient_evidence",
                message=(
                    "No evidence-qualified opportunity candidate is available; "
                    "no experiment or figure plan was generated."
                ),
                project_claim=request.project_claim,
                candidate=None,
                plan=None,
            )
        candidate = next(
            (
                item
                for item in opportunity_result.candidates
                if item.candidate_id == request.candidate_id
            ),
            None,
        )
        if candidate is None:
            raise CandidateNotFoundError(
                "Candidate is not available under the submitted query and filters"
            )
        plan = self._build_plan(candidate, request)
        return ResearchCoachResponse(
            status="ready_for_review",
            message=(
                "The plan is a system planning inference grounded in the selected "
                "candidate; it contains no experimental results."
            ),
            project_claim=request.project_claim,
            candidate=candidate,
            plan=plan,
        )

    def _build_plan(
        self,
        candidate: ResearchOpportunityCandidate,
        request: ResearchPlanRequest,
    ) -> ResearchExperimentPlan:
        context = CONTEXTS[candidate.candidate_type]
        evidence_snapshot = [
            *candidate.supporting_evidence,
            *candidate.conflicting_evidence,
        ]
        evidence_references = [
            PlanningEvidenceReference(
                paper_id=item.paper_id,
                evidence_anchor_id=item.evidence_anchor.id,
                relation=item.relation,
            )
            for item in evidence_snapshot
        ]
        plan_key = "|".join(
            [
                candidate.candidate_id,
                request.project_claim.research_question,
                request.project_claim.hypothesis,
                request.project_claim.proposed_method,
            ]
        )
        plan_id = f"rep-{hashlib.sha256(plan_key.encode()).hexdigest()[:16]}"
        experiments = self._experiments(
            candidate,
            context,
            evidence_references,
            request.project_claim,
        )
        artifacts = self._artifacts(context)
        return ResearchExperimentPlan(
            plan_id=plan_id,
            source_candidate_id=candidate.candidate_id,
            project_claim=request.project_claim,
            evidence_snapshot=evidence_snapshot,
            experiments=experiments,
            artifacts=artifacts,
            open_decisions=[
                "Name and justify the datasets, splits and legal access basis.",
                "Name representative baselines and freeze their implementations.",
                "Predeclare primary and secondary metrics before viewing results.",
                "Set seeds, compute budgets and stopping rules.",
                "Define the smallest practically meaningful effect and uncertainty method.",
            ],
            global_boundaries=[
                *candidate.applicable_conditions,
                *candidate.prohibited_conclusions,
                context.boundary,
                "The project claim is user-supplied and has not been validated.",
                "Planned outputs are schemas only; no values or outcomes were generated.",
            ],
        )

    @staticmethod
    def _rationale(
        candidate: ResearchOpportunityCandidate,
        references: list[PlanningEvidenceReference],
        purpose: str,
    ) -> PlanningRationale:
        return PlanningRationale(
            source_candidate_id=candidate.candidate_id,
            evidence_references=references,
            explanation=(
                f"{purpose} This is a planning inference from candidate type "
                f"{candidate.candidate_type}, not a statement made by the cited papers."
            ),
        )

    def _experiments(
        self,
        candidate: ResearchOpportunityCandidate,
        context: PlanningContext,
        references: list[PlanningEvidenceReference],
        project_claim: ResearchPlanClaimInput,
    ) -> list[PlannedExperiment]:
        shared_inputs = [
            "Versioned datasets and immutable train/validation/test splits",
            "Pinned proposed-method and baseline implementations",
            "Predeclared metrics, seeds, compute budget and stopping rules",
        ]
        shared_controls = [
            "Data splits and preprocessing",
            "Hyperparameter-search and compute budget",
            "Threshold selection and evaluation protocol",
        ]
        return [
            PlannedExperiment(
                experiment_id="exp-main-comparison",
                experiment_type="main_comparison",
                title="Predeclared main comparison",
                validation_goal=(
                    "Test the user-supplied hypothesis under the candidate's applicable "
                    f"conditions: {project_claim.hypothesis}"
                ),
                design=(
                    "Compare the proposed method with user-selected representative "
                    f"baselines while varying {context.comparison_axis}."
                ),
                independent_variables=[
                    "Method identity",
                    context.comparison_axis,
                ],
                dependent_variables=[
                    "Predeclared primary task metric",
                    "Uncertainty interval across seeds",
                    "Training and inference resource measurements",
                ],
                controlled_variables=shared_controls,
                required_inputs=shared_inputs,
                output_fields=[
                    "dataset_id",
                    "split_id",
                    "method_id",
                    "seed",
                    "metric_name",
                    "metric_value",
                    "runtime_seconds",
                    "peak_memory_mb",
                ],
                falsification_criteria=[
                    "The proposed method does not improve the predeclared primary metric.",
                    "The effect direction is unstable across seeds or selected conditions.",
                ],
                interpretation_boundary=[
                    context.boundary,
                    "A positive comparison does not establish global novelty or causality.",
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "A controlled main comparison tests the central project claim.",
                ),
            ),
            PlannedExperiment(
                experiment_id="exp-baseline-coverage",
                experiment_type="baseline_coverage",
                title="Baseline coverage audit",
                validation_goal=(
                    "Determine whether the claimed gain survives comparison with relevant "
                    "method families rather than a selectively weak baseline set."
                ),
                design=(
                    "Predeclare baseline families, inclusion reasons, implementation "
                    "sources and tuning budgets before execution."
                ),
                independent_variables=["Baseline family", "Implementation source"],
                dependent_variables=["Primary metric", "Resource-normalized metric"],
                controlled_variables=shared_controls,
                required_inputs=[
                    *shared_inputs,
                    "Baseline inclusion and exclusion register",
                ],
                output_fields=[
                    "baseline_id",
                    "family",
                    "implementation_version",
                    "inclusion_reason",
                    "metric_name",
                    "metric_value",
                    "budget",
                ],
                falsification_criteria=[
                    "A stronger relevant baseline removes the claimed advantage.",
                    "The result depends on unequal tuning or resource budgets.",
                ],
                interpretation_boundary=[
                    "An incomplete baseline register cannot support a state-of-the-art claim."
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "A baseline audit reduces comparison-selection bias.",
                ),
            ),
            PlannedExperiment(
                experiment_id="exp-ablation",
                experiment_type="ablation",
                title="Component and interaction ablation",
                validation_goal=(
                    "Test whether named components and their interactions are necessary "
                    "for the observed effect."
                ),
                design=(
                    "Run the full method, removals and predeclared component combinations "
                    "without retuning unrelated settings."
                ),
                independent_variables=["Enabled component set"],
                dependent_variables=["Primary metric", "Runtime", "Memory"],
                controlled_variables=shared_controls,
                required_inputs=[
                    *shared_inputs,
                    "User-authored component register and expected mechanism",
                ],
                output_fields=[
                    "component_configuration",
                    "dataset_id",
                    "seed",
                    "metric_value",
                    "runtime_seconds",
                    "peak_memory_mb",
                ],
                falsification_criteria=[
                    "Removing the claimed key component does not reduce the target effect.",
                    "A simpler component combination matches the full method.",
                ],
                interpretation_boundary=[
                    "Ablation differences do not by themselves prove the proposed mechanism."
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "Ablation links method complexity to observable contribution.",
                ),
            ),
            PlannedExperiment(
                experiment_id="exp-sensitivity",
                experiment_type="sensitivity",
                title="Sensitivity and stability analysis",
                validation_goal=(
                    "Measure whether conclusions depend on narrow hyperparameter or seed choices."
                ),
                design=(
                    "Vary preselected influential hyperparameters across justified ranges "
                    "and repeat all settings with fixed seeds."
                ),
                independent_variables=["Hyperparameter setting", "Random seed"],
                dependent_variables=["Primary metric", "Variance", "Failure rate"],
                controlled_variables=shared_controls,
                required_inputs=[
                    *shared_inputs,
                    "Hyperparameter ranges justified without viewing test results",
                ],
                output_fields=[
                    "parameter_name",
                    "parameter_value",
                    "seed",
                    "metric_value",
                    "run_status",
                ],
                falsification_criteria=[
                    "The claimed effect appears only in a narrow post-hoc setting.",
                    "Ordinary seed variation changes the conclusion direction.",
                ],
                interpretation_boundary=[
                    "Tested ranges do not establish stability outside those ranges."
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "Sensitivity analysis tests conclusion stability.",
                ),
            ),
            PlannedExperiment(
                experiment_id="exp-robustness",
                experiment_type="robustness",
                title="Candidate-specific robustness test",
                validation_goal=(
                    "Measure the operating boundary under the evidence-derived gap."
                ),
                design=(
                    "Apply predeclared stress levels while varying "
                    f"{context.robustness_axis}; retain an unchanged clean control."
                ),
                independent_variables=[context.robustness_axis, "Stress level"],
                dependent_variables=["Metric degradation", "Calibration", "Failure rate"],
                controlled_variables=shared_controls,
                required_inputs=[
                    *shared_inputs,
                    "Stress-generation procedure and clean-control checksum",
                ],
                output_fields=[
                    "stress_type",
                    "stress_level",
                    "dataset_id",
                    "method_id",
                    "metric_value",
                    "degradation_from_clean",
                ],
                falsification_criteria=[
                    "Performance degrades beyond the predeclared acceptable boundary.",
                    "The proposed method degrades faster than a relevant baseline.",
                ],
                interpretation_boundary=[
                    context.boundary,
                    "Artificial stress results require separate real-scenario validation.",
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "The candidate gap determines the robustness axis to test.",
                ),
            ),
            PlannedExperiment(
                experiment_id="exp-failure-cases",
                experiment_type="failure_case_analysis",
                title="Failure-case and boundary analysis",
                validation_goal=(
                    "Identify repeatable conditions where the project claim does not hold "
                    f"for the question: {project_claim.research_question}"
                ),
                design=(
                    "Predefine failure categories, sample errors without hiding unfavorable "
                    "cases and compare category frequencies across methods."
                ),
                independent_variables=["Failure category", "Method identity"],
                dependent_variables=["Error count", "Error severity", "Confidence"],
                controlled_variables=[
                    "Sampling rule",
                    "Category definitions",
                    "Evaluation subset",
                ],
                required_inputs=[
                    "Per-example predictions and ground truth",
                    "Versioned failure taxonomy",
                    "Blinded case-selection procedure",
                ],
                output_fields=[
                    "example_id",
                    "method_id",
                    "failure_category",
                    "severity",
                    "prediction",
                    "target",
                    "review_note",
                ],
                falsification_criteria=[
                    "A systematic failure category contradicts the hypothesized benefit.",
                    "Apparent aggregate gains conceal materially worse severe failures.",
                ],
                interpretation_boundary=[
                    "Selected examples cannot estimate prevalence without the full audit table."
                ],
                rationale=self._rationale(
                    candidate,
                    references,
                    "Failure cases define where the claim must be narrowed.",
                ),
            ),
        ]

    @staticmethod
    def _artifacts(context: PlanningContext) -> list[PlannedArtifact]:
        return [
            PlannedArtifact(
                artifact_id="artifact-main-results",
                artifact_type="result_table",
                title="Main comparison with uncertainty and resource cost",
                validation_goal="Show whether the main claim survives fair comparison.",
                source_experiment_ids=[
                    "exp-main-comparison",
                    "exp-baseline-coverage",
                ],
                variables=["Method", "Dataset", "Metric", "Resource budget"],
                output_fields=[
                    "dataset_id",
                    "method_id",
                    "metric_value",
                    "uncertainty",
                    "runtime_seconds",
                    "peak_memory_mb",
                ],
                recommended_encoding=(
                    "Rows are methods, grouped columns are datasets and metrics; show "
                    "uncertainty and resource columns without invented highlights."
                ),
                evidence_boundary=[
                    "Do not label a best value until the metric and uncertainty rules are frozen."
                ],
            ),
            PlannedArtifact(
                artifact_id="artifact-ablation",
                artifact_type="ablation_table",
                title="Component contribution and interaction table",
                validation_goal="Show which component combinations are empirically necessary.",
                source_experiment_ids=["exp-ablation"],
                variables=["Enabled component set", "Dataset", "Seed"],
                output_fields=[
                    "component_configuration",
                    "metric_value",
                    "runtime_seconds",
                    "peak_memory_mb",
                ],
                recommended_encoding=(
                    "One row per predeclared configuration with explicit enabled-component marks."
                ),
                evidence_boundary=[
                    "Do not describe an ablation association as a proven causal mechanism."
                ],
            ),
            PlannedArtifact(
                artifact_id="artifact-sensitivity",
                artifact_type="sensitivity_curve",
                title="Sensitivity curve with seed uncertainty",
                validation_goal="Show whether performance is stable across selected settings.",
                source_experiment_ids=["exp-sensitivity"],
                variables=["Hyperparameter value", "Method", "Seed"],
                output_fields=[
                    "parameter_name",
                    "parameter_value",
                    "metric_value",
                    "seed",
                ],
                recommended_encoding=(
                    "Parameter value on x, metric on y, one line per method with uncertainty."
                ),
                evidence_boundary=[
                    "Do not extrapolate stability outside the tested range."
                ],
            ),
            PlannedArtifact(
                artifact_id="artifact-robustness",
                artifact_type="robustness_plot",
                title="Performance degradation across stress levels",
                validation_goal=f"Show robustness under {context.robustness_axis}.",
                source_experiment_ids=["exp-robustness"],
                variables=[context.robustness_axis, "Stress level", "Method"],
                output_fields=[
                    "stress_type",
                    "stress_level",
                    "method_id",
                    "metric_value",
                    "degradation_from_clean",
                ],
                recommended_encoding=(
                    "Stress level on x and degradation on y; retain the clean control."
                ),
                evidence_boundary=[
                    "Do not equate synthetic stress tolerance with deployment safety."
                ],
            ),
            PlannedArtifact(
                artifact_id="artifact-failure-cases",
                artifact_type="failure_case_panel",
                title="Auditable failure cases plus category counts",
                validation_goal="Show where and how the project claim fails.",
                source_experiment_ids=["exp-failure-cases"],
                variables=["Failure category", "Method", "Severity"],
                output_fields=[
                    "example_id",
                    "failure_category",
                    "prediction",
                    "target",
                    "severity",
                ],
                recommended_encoding=(
                    "Pair representative cases with the full category-frequency table."
                ),
                evidence_boundary=[
                    "Do not use hand-picked examples as prevalence estimates."
                ],
            ),
            PlannedArtifact(
                artifact_id="artifact-tradeoff",
                artifact_type="tradeoff_plot",
                title="Effect versus resource trade-off",
                validation_goal="Show whether gains remain useful under a fixed budget.",
                source_experiment_ids=["exp-main-comparison", "exp-ablation"],
                variables=["Method", "Task metric", "Resource cost"],
                output_fields=[
                    "method_id",
                    "metric_value",
                    "runtime_seconds",
                    "peak_memory_mb",
                ],
                recommended_encoding=(
                    "Resource cost on x and task metric on y with disclosed hardware context."
                ),
                evidence_boundary=[
                    "Do not compare runtime measured on different undisclosed hardware."
                ],
            ),
        ]
