import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from app.project_claim_models import (
    EvidenceDiagnosisEditRequest,
    EvidenceDiagnosisVersion,
    EvidenceRequirement,
    EvidenceRequirementType,
    ProjectClaimCreateRequest,
    ProjectClaimEnvelope,
    ProjectClaimHistory,
    ProjectClaimInput,
    ProjectClaimVersion,
    RecommendedArtifact,
    TadProjectClaimExample,
)


class ProjectClaimNotFoundError(LookupError):
    pass


class ProjectClaimVersionConflictError(RuntimeError):
    pass


class InvalidProjectIdError(ValueError):
    pass


class ProjectClaimStore(Protocol):
    def latest_claim(self, project_id: str) -> ProjectClaimVersion | None: ...

    def list_claims(self, project_id: str) -> list[ProjectClaimVersion]: ...

    def get_envelope(
        self, project_id: str, version: int
    ) -> ProjectClaimEnvelope | None: ...

    def save_envelope(
        self,
        envelope: ProjectClaimEnvelope,
        expected_latest_version: int,
    ) -> None: ...

    def save_diagnosis(
        self,
        project_id: str,
        version: int,
        diagnosis: EvidenceDiagnosisVersion,
        expected_revision: int,
    ) -> None: ...


class InMemoryProjectClaimStore:
    def __init__(self) -> None:
        self._claims: dict[str, list[ProjectClaimVersion]] = {}
        self._diagnoses: dict[str, list[EvidenceDiagnosisVersion]] = {}
        self._lock = RLock()

    def latest_claim(self, project_id: str) -> ProjectClaimVersion | None:
        with self._lock:
            versions = self._claims.get(project_id, [])
            return versions[-1].model_copy(deep=True) if versions else None

    def list_claims(self, project_id: str) -> list[ProjectClaimVersion]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._claims.get(project_id, [])]

    def get_envelope(
        self, project_id: str, version: int
    ) -> ProjectClaimEnvelope | None:
        with self._lock:
            claim = next(
                (
                    item
                    for item in self._claims.get(project_id, [])
                    if item.version == version
                ),
                None,
            )
            if claim is None:
                return None
            diagnoses = self._diagnoses.get(claim.claim_version_id, [])
            if not diagnoses:
                return None
            return ProjectClaimEnvelope(
                claim=claim.model_copy(deep=True),
                diagnosis=diagnoses[-1].model_copy(deep=True),
            )

    def save_envelope(
        self,
        envelope: ProjectClaimEnvelope,
        expected_latest_version: int,
    ) -> None:
        with self._lock:
            versions = self._claims.setdefault(envelope.claim.project_id, [])
            actual_latest = versions[-1].version if versions else 0
            if actual_latest != expected_latest_version:
                raise ProjectClaimVersionConflictError(
                    f"Expected latest version {expected_latest_version}, got {actual_latest}"
                )
            if envelope.claim.version != actual_latest + 1:
                raise ProjectClaimVersionConflictError(
                    "Claim version must increment the latest version by one"
                )
            versions.append(envelope.claim.model_copy(deep=True))
            self._diagnoses[envelope.claim.claim_version_id] = [
                envelope.diagnosis.model_copy(deep=True)
            ]

    def save_diagnosis(
        self,
        project_id: str,
        version: int,
        diagnosis: EvidenceDiagnosisVersion,
        expected_revision: int,
    ) -> None:
        with self._lock:
            claim = next(
                (
                    item
                    for item in self._claims.get(project_id, [])
                    if item.version == version
                ),
                None,
            )
            if claim is None:
                raise ProjectClaimNotFoundError("Project Claim version was not found")
            revisions = self._diagnoses.get(claim.claim_version_id, [])
            actual_revision = revisions[-1].revision if revisions else 0
            if actual_revision != expected_revision:
                raise ProjectClaimVersionConflictError(
                    f"Expected diagnosis revision {expected_revision}, got {actual_revision}"
                )
            if diagnosis.revision != actual_revision + 1:
                raise ProjectClaimVersionConflictError(
                    "Diagnosis revision must increment by one"
                )
            revisions.append(diagnosis.model_copy(deep=True))


@dataclass(frozen=True)
class EvidenceRule:
    requirement_type: EvidenceRequirementType
    rule_id: str
    why_needed: str
    independent_variables: tuple[str, ...]
    controlled_variables: tuple[str, ...]
    output_fields: tuple[str, ...]
    artifact_type: str
    artifact_title: str
    artifact_rationale: str
    can_support: tuple[str, ...]
    cannot_support: tuple[str, ...]


RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        "main_experiment",
        "claim-evidence-main-v1",
        "A central comparison is required to test the direction of the user-supplied hypothesis.",
        ("method identity", "target scenario condition"),
        ("data split", "preprocessing", "evaluation protocol", "compute budget"),
        ("dataset_id", "method_id", "seed", "metric_name", "metric_value", "uncertainty"),
        "table",
        "Predeclared main comparison",
        "A table keeps methods, scenarios, metrics and uncertainty auditable.",
        ("Whether the claimed effect appears under the predeclared test conditions.",),
        ("It cannot establish novelty, causality or performance outside tested conditions.",),
    ),
    EvidenceRule(
        "strong_baseline",
        "claim-evidence-baseline-v1",
        (
            "Relevant strong baselines are needed to avoid attributing gains to a "
            "selectively weak comparison set."
        ),
        ("baseline family", "implementation source"),
        ("data split", "tuning budget", "stopping rule", "metric implementation"),
        ("baseline_id", "family", "version", "inclusion_reason", "metric_value", "budget"),
        "table",
        "Strong-baseline coverage register",
        "A register exposes baseline selection, versions and comparison budgets.",
        ("Whether the claimed gain survives comparison with the selected strong baselines.",),
        ("It cannot prove superiority over omitted or future methods.",),
    ),
    EvidenceRule(
        "fair_comparison",
        "claim-evidence-fairness-v1",
        (
            "A fair protocol is necessary to separate method effects from data, "
            "tuning and scoring differences."
        ),
        ("method identity",),
        ("split", "preprocessing", "search space", "hardware", "thresholding", "metric definition"),
        ("method_id", "protocol_id", "budget", "hardware", "metric_name", "metric_value"),
        "table",
        "Comparison-condition checklist",
        "A condition matrix makes unequal settings visible before interpreting scores.",
        ("Whether compared methods were evaluated under disclosed equivalent conditions.",),
        ("It cannot remove differences caused by unavailable or irreproducible implementations.",),
    ),
    EvidenceRule(
        "ablation",
        "claim-evidence-ablation-v1",
        (
            "Component ablation is needed to test whether the proposed method's "
            "named parts contribute to the effect."
        ),
        ("enabled component set",),
        ("data", "seed set", "training budget", "unrelated hyperparameters"),
        ("configuration_id", "enabled_components", "seed", "metric_value", "runtime", "memory"),
        "table",
        "Component and interaction ablation",
        "Rows for predeclared component combinations reveal performance and cost changes.",
        ("Whether removing a component is associated with a change under tested settings.",),
        ("It cannot by itself prove the proposed causal mechanism.",),
    ),
    EvidenceRule(
        "parameter_sensitivity",
        "claim-evidence-sensitivity-v1",
        (
            "Sensitivity analysis is needed to detect conclusions that depend on "
            "narrow parameter or seed choices."
        ),
        ("parameter value", "random seed"),
        ("data split", "method version", "other parameters", "evaluation protocol"),
        ("parameter_name", "parameter_value", "seed", "metric_value", "run_status"),
        "line_chart",
        "Parameter sensitivity with uncertainty",
        "Curves show stability across a predeclared parameter range and seeds.",
        ("Whether the observed direction is stable across the tested range.",),
        ("It cannot establish stability outside the tested range.",),
    ),
    EvidenceRule(
        "robustness",
        "claim-evidence-robustness-v1",
        (
            "Robustness evidence is needed to define how the claim behaves under "
            "plausible disturbance or shift."
        ),
        ("stress type", "stress level", "method identity"),
        ("clean control", "split", "preprocessing", "budget", "metric"),
        ("stress_type", "stress_level", "method_id", "metric_value", "degradation_from_clean"),
        "line_chart",
        "Robustness degradation curve",
        "A clean control and ordered stress levels expose the operating boundary.",
        ("How quickly performance changes under the selected stress process.",),
        ("It cannot establish safety or robustness for untested real deployments.",),
    ),
    EvidenceRule(
        "efficiency",
        "claim-evidence-efficiency-v1",
        (
            "Efficiency measurements are needed to determine whether an effect "
            "remains useful under realistic resource limits."
        ),
        ("method identity", "sequence length", "batch size"),
        ("hardware", "software version", "precision", "warm-up", "measurement window"),
        (
            "method_id",
            "hardware",
            "runtime_seconds",
            "throughput",
            "peak_memory_mb",
            "energy_if_available",
        ),
        "scatter_plot",
        "Effect versus resource trade-off",
        "A trade-off plot keeps quality and disclosed resource cost visible together.",
        ("Whether the measured effect is accompanied by acceptable cost on disclosed hardware.",),
        ("It cannot establish cost on different hardware or production workloads.",),
    ),
    EvidenceRule(
        "failure_cases",
        "claim-evidence-failure-v1",
        (
            "Failure-case analysis is needed to narrow the Claim and prevent "
            "aggregate metrics from hiding systematic errors."
        ),
        ("failure category", "method identity", "scenario condition"),
        ("sampling rule", "taxonomy", "evaluation subset", "review procedure"),
        ("example_id", "failure_category", "prediction", "target", "severity", "review_note"),
        "case_panel",
        "Failure cases with category counts",
        "A case panel paired with complete counts avoids relying on hand-picked examples alone.",
        ("Which repeatable conditions contradict or narrow the user-supplied Claim.",),
        ("Selected examples cannot estimate prevalence without the complete audit table.",),
    ),
)


class ProjectClaimEvidencePlanner:
    version = "project-claim-evidence-rules-v1"

    def diagnose(
        self, claim: ProjectClaimVersion, *, now: datetime | None = None
    ) -> EvidenceDiagnosisVersion:
        created_at = now or datetime.now(UTC)
        requirements = [
            EvidenceRequirement(
                requirement_id=f"{claim.claim_version_id}:{rule.requirement_type}",
                requirement_type=rule.requirement_type,
                validates_claim_version_id=claim.claim_version_id,
                validates_claim=claim.hypothesis,
                why_needed=rule.why_needed,
                independent_variables=list(rule.independent_variables),
                controlled_variables=list(rule.controlled_variables),
                output_fields=list(rule.output_fields),
                recommended_artifact=RecommendedArtifact(
                    artifact_type=rule.artifact_type,
                    title=rule.artifact_title,
                    rationale=rule.artifact_rationale,
                ),
                can_support=list(rule.can_support),
                cannot_support=list(rule.cannot_support),
                generated_by_rule=rule.rule_id,
            )
            for rule in RULES
        ]
        return EvidenceDiagnosisVersion(
            diagnosis_id=f"diag-{claim.claim_version_id}-r1",
            claim_version_id=claim.claim_version_id,
            revision=1,
            origin="rule_generated",
            requirements=requirements,
            created_at=created_at,
        )


class ProjectClaimService:
    def __init__(
        self,
        store: ProjectClaimStore,
        planner: ProjectClaimEvidencePlanner | None = None,
    ) -> None:
        self.store = store
        self.planner = planner or ProjectClaimEvidencePlanner()

    def create(
        self, project_id: str, request: ProjectClaimCreateRequest
    ) -> ProjectClaimEnvelope:
        project_id = self._validate_project_id(project_id)
        latest = self.store.latest_claim(project_id)
        actual_latest = latest.version if latest else 0
        if actual_latest != request.expected_latest_version:
            raise ProjectClaimVersionConflictError(
                f"Expected latest version {request.expected_latest_version}, got {actual_latest}"
            )
        claim_id = f"pc-{hashlib.sha256(project_id.encode()).hexdigest()[:16]}"
        version = actual_latest + 1
        claim_version_id = f"{claim_id}-v{version}"
        content_json = json.dumps(
            request.claim.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = datetime.now(UTC)
        claim = ProjectClaimVersion(
            **request.claim.model_dump(),
            project_id=project_id,
            claim_id=claim_id,
            claim_version_id=claim_version_id,
            version=version,
            supersedes_claim_version_id=(
                latest.claim_version_id if latest is not None else None
            ),
            content_sha256=hashlib.sha256(content_json.encode()).hexdigest(),
            created_at=now,
        )
        envelope = ProjectClaimEnvelope(
            claim=claim,
            diagnosis=self.planner.diagnose(claim, now=now),
        )
        self.store.save_envelope(envelope, request.expected_latest_version)
        return envelope

    def history(self, project_id: str) -> ProjectClaimHistory:
        project_id = self._validate_project_id(project_id)
        return ProjectClaimHistory(
            project_id=project_id,
            versions=self.store.list_claims(project_id),
        )

    def get(self, project_id: str, version: int) -> ProjectClaimEnvelope:
        project_id = self._validate_project_id(project_id)
        envelope = self.store.get_envelope(project_id, version)
        if envelope is None:
            raise ProjectClaimNotFoundError("Project Claim version was not found")
        return envelope

    def edit_diagnosis(
        self,
        project_id: str,
        version: int,
        request: EvidenceDiagnosisEditRequest,
    ) -> ProjectClaimEnvelope:
        envelope = self.get(project_id, version)
        previous = envelope.diagnosis
        previous_rules = {
            item.requirement_type: item.generated_by_rule
            for item in previous.requirements
        }
        revision = previous.revision + 1
        requirements = [
            EvidenceRequirement(
                requirement_id=(
                    f"{envelope.claim.claim_version_id}:{item.requirement_type}"
                ),
                validates_claim_version_id=envelope.claim.claim_version_id,
                validates_claim=envelope.claim.hypothesis,
                generated_by_rule=previous_rules.get(
                    item.requirement_type, "user-added-requirement"
                ),
                **item.model_dump(),
            )
            for item in request.requirements
        ]
        diagnosis = EvidenceDiagnosisVersion(
            diagnosis_id=(
                f"diag-{envelope.claim.claim_version_id}-r{revision}"
            ),
            claim_version_id=envelope.claim.claim_version_id,
            revision=revision,
            origin="user_edited",
            requirements=requirements,
            created_at=datetime.now(UTC),
        )
        self.store.save_diagnosis(
            envelope.claim.project_id,
            version,
            diagnosis,
            request.expected_revision,
        )
        return ProjectClaimEnvelope(claim=envelope.claim, diagnosis=diagnosis)

    @staticmethod
    def _validate_project_id(project_id: str) -> str:
        normalized = project_id.strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", normalized):
            raise InvalidProjectIdError(
                "project_id must be 3-64 lowercase letters, digits or hyphens"
            )
        return normalized


def tad_project_claim_example() -> TadProjectClaimExample:
    return TadProjectClaimExample(
        disclaimer=(
            "Synthetic TAD form example only. It contains no experimental result "
            "and makes no feasibility or innovation assessment."
        ),
        claim=ProjectClaimInput(
            research_question=(
                "Does an association-aware detector retain anomaly-detection quality "
                "under increasing sensor noise in multivariate time series?"
            ),
            hypothesis=(
                "Under the same data split and evaluation protocol, the proposed "
                "association-aware method degrades more slowly than selected strong "
                "baselines as predeclared sensor-noise severity increases."
            ),
            proposed_method=(
                "A user-defined detector that combines temporal association features "
                "with a reconstruction objective."
            ),
            target_scenario=(
                "Offline multivariate sensor anomaly detection with controlled additive "
                "noise and fixed anomaly labels."
            ),
            existing_results=[],
        ),
    )
