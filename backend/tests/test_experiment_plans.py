from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.experiment_plan_models import (
    BaselinePlan,
    ExperimentPlanEditRequest,
    ExperimentPlanGenerateRequest,
)
from app.main import app
from app.project_claim_models import ProjectClaimCreateRequest, ProjectClaimInput
from app.services.experiment_plans import (
    ExperimentPlanService,
    ExperimentPlanVersionConflictError,
    InMemoryExperimentPlanStore,
)
from app.services.project_claims import InMemoryProjectClaimStore, ProjectClaimService
from app.storage.experiment_plan_repository import ExperimentPlanRepository
from app.storage.project_claim_repository import ProjectClaimRepository
from app.storage.tables import (
    ArtifactPlanClaimLinkRow,
    Base,
    ExperimentPlanClaimLinkRow,
    ExperimentPlanVersionRow,
)


client = TestClient(app)


def _claim_input(*, suffix: str = "", absolute: bool = False) -> ProjectClaimInput:
    hypothesis = (
        "The proposed method always outperforms all baselines on all datasets."
        if absolute
        else "The proposed method degrades more slowly than strong baselines as sensor-noise severity increases."
    )
    return ProjectClaimInput(
        research_question="How does detector reliability change under sensor noise?" + suffix,
        hypothesis=hypothesis + suffix,
        proposed_method="A user-defined association-aware detector" + suffix,
        target_scenario="Multivariate time-series anomaly detection" + suffix,
        existing_results=[],
    )


def _services(store=None):
    claim_service = ProjectClaimService(InMemoryProjectClaimStore())
    plan_service = ExperimentPlanService(
        store or InMemoryExperimentPlanStore(), claim_service
    )
    return claim_service, plan_service


def _create_claim(
    service: ProjectClaimService,
    project_id: str,
    version: int,
    *,
    absolute: bool = False,
):
    return service.create(
        project_id,
        ProjectClaimCreateRequest(
            expected_latest_version=version - 1,
            claim=_claim_input(suffix=f" v{version}", absolute=absolute),
        ),
    )


def test_planner_links_multiple_claims_and_preserves_exact_rq_hypothesis() -> None:
    claims, plans = _services()
    first = _create_claim(claims, "multi-claim-tad", 1)
    second = _create_claim(claims, "multi-claim-tad", 2)

    plan = plans.generate(
        "multi-claim-tad",
        ExperimentPlanGenerateRequest(
            expected_latest_revision=0,
            claim_versions=[1, 2],
        ),
    )

    assert plan.revision == 1
    assert plan.origin == "rule_generated"
    assert plan.generation_basis.result_policy == "plan_only_no_results_or_expected_values"
    assert len(plan.experiments) == 8
    assert len(plan.artifacts) == 8
    expected_claim_ids = {
        first.claim.claim_version_id,
        second.claim.claim_version_id,
    }
    for experiment in plan.experiments:
        assert set(experiment.claim_version_ids) == expected_claim_ids
        assert set(experiment.research_questions) == {
            first.claim.research_question,
            second.claim.research_question,
        }
        assert set(experiment.hypotheses) == {
            first.claim.hypothesis,
            second.claim.hypothesis,
        }
        assert experiment.datasets
        assert experiment.variables.independent
        assert experiment.controls.data_split
        assert experiment.metrics
        assert experiment.expected_artifact_ids
        assert experiment.boundary.cannot_support
    for artifact in plan.artifacts:
        assert artifact.artifact_kind in {"figure", "table"}
        assert artifact.form_reason
        assert artifact.data_fields
        assert set(artifact.supports_claim_version_ids) == expected_claim_ids
        assert artifact.common_misreadings
        if artifact.artifact_kind == "figure":
            assert artifact.x_axis and artifact.y_axis
        else:
            assert artifact.rows and artifact.columns


def test_quality_checker_reports_all_five_risks_without_fabricating_results() -> None:
    claims, plans = _services()
    _create_claim(claims, "quality-tad", 1, absolute=True)
    generated = plans.generate(
        "quality-tad",
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    first = generated.experiments[0]
    first.status = "modified"
    first.datasets[0].preprocessing_fit_scope = "full_dataset"
    first.controls.applies_equally = "not_planned"
    first.metrics[0].applies_to = "proposed_method_only"
    second = generated.experiments[1]
    second.status = "confirmed"
    second.baselines.append(
        BaselinePlan(
            baseline_id="tranad-reviewed-config",
            label="TranAD",
            strength_rationale="User selected it as a relevant competitive TAD baseline.",
            implementation_source="User must pin the reviewed repository and commit before execution.",
            status="included",
        )
    )
    generated.experiments[2].status = "rejected"

    edited = plans.edit(
        "quality-tad",
        1,
        ExperimentPlanEditRequest(
            expected_revision=1,
            experiments=generated.experiments,
            artifacts=generated.artifacts,
        ),
    )

    first_checks = {
        item.check_type: item
        for item in edited.quality_report.checks
        if item.experiment_id == first.experiment_id
    }
    assert set(first_checks) == {
        "missing_strong_baseline",
        "data_leakage",
        "unfair_setup",
        "metric_inconsistency",
        "overclaiming",
    }
    assert first_checks["missing_strong_baseline"].status == "warning"
    assert first_checks["data_leakage"].status == "error"
    assert first_checks["unfair_setup"].status == "error"
    assert first_checks["metric_inconsistency"].status == "warning"
    assert first_checks["overclaiming"].status == "warning"
    assert edited.quality_report.has_errors is True
    assert edited.origin == "user_edited"
    assert edited.revision == 2
    assert {item.status for item in edited.experiments[:3]} == {
        "modified",
        "confirmed",
        "rejected",
    }
    payload = edited.model_dump(mode="json")
    assert "result" not in payload
    assert "expected_value" not in payload


def test_plan_edits_are_versioned_and_optimistically_locked() -> None:
    claims, plans = _services()
    _create_claim(claims, "revision-tad", 1)
    created = plans.generate(
        "revision-tad",
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    created.experiments[0].status = "confirmed"
    updated = plans.edit(
        "revision-tad",
        1,
        ExperimentPlanEditRequest(
            expected_revision=1,
            experiments=created.experiments,
            artifacts=created.artifacts,
        ),
    )

    assert updated.supersedes_plan_revision_id == created.plan_revision_id
    assert [item.revision for item in plans.history("revision-tad").revisions] == [1, 2]
    with pytest.raises(ExperimentPlanVersionConflictError, match="Expected editable"):
        plans.edit(
            "revision-tad",
            1,
            ExperimentPlanEditRequest(
                expected_revision=1,
                experiments=created.experiments,
                artifacts=created.artifacts,
            ),
        )


def test_sqlalchemy_repository_persists_plan_history_and_claim_links() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    claims = ProjectClaimService(ProjectClaimRepository(factory))
    plans = ExperimentPlanService(ExperimentPlanRepository(factory), claims)
    _create_claim(claims, "sql-plan-tad", 1)
    generated = plans.generate(
        "sql-plan-tad",
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    generated.artifacts[0].status = "rejected"
    plans.edit(
        "sql-plan-tad",
        1,
        ExperimentPlanEditRequest(
            expected_revision=1,
            experiments=generated.experiments,
            artifacts=generated.artifacts,
        ),
    )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ExperimentPlanVersionRow)) == 2
        assert session.scalar(select(func.count()).select_from(ExperimentPlanClaimLinkRow)) == 16
        assert session.scalar(select(func.count()).select_from(ArtifactPlanClaimLinkRow)) == 16


def test_tad_api_end_to_end_create_generate_edit_and_history() -> None:
    project_id = f"e2e-tad-{uuid4().hex[:12]}"
    example = client.get("/api/v1/research/project-claims/examples/tad").json()
    claim_response = client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={"expected_latest_version": 0, "claim": example["claim"]},
    )
    assert claim_response.status_code == 200

    generate_response = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 0, "claim_versions": [1]},
    )
    assert generate_response.status_code == 200
    generated = generate_response.json()
    assert generated["revision"] == 1
    assert len(generated["experiments"]) == 8
    assert len(generated["quality_report"]["checks"]) == 40

    generated["experiments"][0]["status"] = "confirmed"
    generated["experiments"][1]["status"] = "modified"
    generated["experiments"][2]["status"] = "rejected"
    edit_response = client.put(
        f"/api/v1/research/projects/{project_id}/experiment-plans/1",
        json={
            "expected_revision": 1,
            "experiments": generated["experiments"],
            "artifacts": generated["artifacts"],
        },
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["revision"] == 2
    assert edit_response.json()["origin"] == "user_edited"

    history = client.get(
        f"/api/v1/research/projects/{project_id}/experiment-plans"
    )
    assert history.status_code == 200
    assert [item["revision"] for item in history.json()["revisions"]] == [1, 2]


def test_api_rejects_result_fields_and_unknown_claim_versions() -> None:
    project_id = f"negative-tad-{uuid4().hex[:12]}"
    client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={
            "expected_latest_version": 0,
            "claim": _claim_input().model_dump(mode="json"),
        },
    )
    generated = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 0, "claim_versions": [1]},
    ).json()
    generated["experiments"][0]["expected_metric_value"] = 0.99
    rejected = client.put(
        f"/api/v1/research/projects/{project_id}/experiment-plans/1",
        json={
            "expected_revision": 1,
            "experiments": generated["experiments"],
            "artifacts": generated["artifacts"],
        },
    )
    missing = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 1, "claim_versions": [99]},
    )
    assert rejected.status_code == 422
    assert missing.status_code == 404
