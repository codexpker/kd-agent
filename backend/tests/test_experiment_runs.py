import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.experiment_plan_models import ExperimentPlanGenerateRequest
from app.experiment_run_models import (
    DataLifecyclePolicy,
    ExperimentRunCreateRequest,
    ExternalVerificationEvidence,
    ReportedExecutionEnvironment,
    RunConfiguration,
    RunIdentity,
)
from app.main import app
from app.project_claim_models import ProjectClaimCreateRequest, ProjectClaimInput
from app.services.experiment_plans import ExperimentPlanService, InMemoryExperimentPlanStore
from app.services.experiment_runs import (
    ExperimentRunIdentityError,
    ExperimentRunService,
    InMemoryExperimentRunStore,
    canonical_sha256,
)
from app.services.project_claims import InMemoryProjectClaimStore, ProjectClaimService
from app.services.plot_drafts import DatasetValidator
from app.storage.experiment_plan_repository import ExperimentPlanRepository
from app.storage.experiment_run_repository import ExperimentRunRepository
from app.storage.project_claim_repository import ProjectClaimRepository
from app.storage.tables import Base, ExperimentRunManifestVersionRow


FIXTURE = (
    Path(__file__).parents[1]
    / "app"
    / "data"
    / "evaluation"
    / "synthetic_plot_smoke.csv"
)
client = TestClient(app)


def _claim() -> ProjectClaimInput:
    return ProjectClaimInput(
        research_question="How does a user-provided measurement vary by condition?",
        hypothesis="The user will test whether measurements change by condition.",
        proposed_method="User-defined experimental method",
        target_scenario="Generic experiment-run manifest smoke test",
        existing_results=[],
    )


def _request(
    experiment_id: str,
    *,
    provenance: str = "user_declared",
    external=None,
    lifecycle: DataLifecyclePolicy | None = None,
) -> ExperimentRunCreateRequest:
    return ExperimentRunCreateRequest(
        plan_revision=1,
        experiment_id=experiment_id,
        identity=RunIdentity(actor_id="local-researcher", display_name="Local Researcher"),
        run_configuration=RunConfiguration(
            entrypoint="python train.py --config configs/smoke.yaml",
            code_revision="git:abc1234",
            dataset_versions=["synthetic-smoke-v1"],
            random_seeds=[1, 2],
            command_arguments=["--deterministic"],
            parameters={"learning_rate": 0.001, "epochs": 2},
        ),
        execution_environment=ReportedExecutionEnvironment(
            operating_system="Windows test environment",
            python_version="3.12",
            hardware_summary="CI CPU only",
            framework_versions={"python": "3.12", "matplotlib": "3.11"},
        ),
        result_provenance=provenance,
        external_verification=external,
        lifecycle_policy=lifecycle or DataLifecyclePolicy(),
    )


def _services(run_store=None):
    claims = ProjectClaimService(InMemoryProjectClaimStore())
    plans = ExperimentPlanService(InMemoryExperimentPlanStore(), claims)
    claims.create(
        "run-test",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=_claim()),
    )
    plan = plans.generate(
        "run-test",
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    runs = ExperimentRunService(run_store or InMemoryExperimentRunStore(), plans)
    return claims, plans, runs, plan


def test_run_configuration_hash_is_canonical_and_secret_keys_are_rejected() -> None:
    first = {
        "entrypoint": "python train.py",
        "code_revision": "abc",
        "dataset_versions": ["v1"],
        "random_seeds": [1],
        "command_arguments": [],
        "parameters": {"b": 2, "a": 1},
    }
    second = {**first, "parameters": {"a": 1, "b": 2}}
    assert canonical_sha256(first) == canonical_sha256(second)

    with pytest.raises(ValidationError, match="secret-like"):
        RunConfiguration.model_validate(
            {**first, "parameters": {"api_token": "must-not-be-stored"}}
        )


def test_external_results_stay_pending_and_cannot_be_self_marked_verified() -> None:
    _, _, _, plan = _services()
    experiment_id = plan.experiments[0].experiment_id
    evidence = ExternalVerificationEvidence(
        issuer="Independent lab",
        evidence_reference="lab-record:2026-001",
        evidence_sha256="a" * 64,
    )
    request = _request(
        experiment_id,
        provenance="externally_verifiable",
        external=evidence,
    )
    assert request.external_verification is not None
    assert request.external_verification.status == "pending_external_verification"

    payload = evidence.model_dump(mode="json")
    payload["status"] = "verified"
    with pytest.raises(ValidationError):
        ExternalVerificationEvidence.model_validate(payload)
    with pytest.raises(ValidationError, match="require pending evidence"):
        _request(experiment_id, provenance="externally_verifiable", external=None)


def test_run_manifest_links_plan_identity_config_and_immutable_revisions() -> None:
    _, _, runs, plan = _services()
    experiment_id = plan.experiments[0].experiment_id
    created = runs.create("run-test", _request(experiment_id))

    assert created.status == "registered"
    assert created.plan_revision_id == plan.plan_revision_id
    assert created.experiment_id == experiment_id
    assert created.identity.assurance == "self_asserted_local_identity"
    expected_hash = canonical_sha256(
        created.run_configuration.model_dump(mode="json")
    )
    assert created.run_configuration_sha256 == expected_hash
    assert created.result_provenance == "user_declared"
    assert created.external_verification is None
    assert runs.history("run-test", created.run_id).revisions == [created]

    with pytest.raises(ExperimentRunIdentityError):
        runs.assert_actor("run-test", created.run_id, "different-user")


def test_due_process_data_appends_expired_audit_revision() -> None:
    _, plans, _, plan = _services()
    current_time = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    runs = ExperimentRunService(
        InMemoryExperimentRunStore(),
        plans,
        clock=lambda: current_time[0],
    )
    created = runs.create("run-test", _request(plan.experiments[0].experiment_id))
    report, _ = DatasetValidator().validate(
        "run-test", FIXTURE.name, FIXTURE.read_bytes()
    )
    attached = runs.attach_data(
        "run-test", created.run_id, "local-researcher", report
    )
    assert attached.data_asset is not None
    assert attached.data_asset.lifecycle_state == "normalized_process_local"

    current_time[0] += timedelta(hours=25)
    expired = runs.get("run-test", created.run_id)

    assert expired.revision == 3
    assert expired.status == "data_expired"
    assert expired.data_asset is not None
    assert expired.data_asset.lifecycle_state == "expired"


def test_sqlalchemy_repository_persists_run_manifest_revisions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    claims = ProjectClaimService(ProjectClaimRepository(factory))
    plans = ExperimentPlanService(ExperimentPlanRepository(factory), claims)
    claims.create(
        "sql-run",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=_claim()),
    )
    plan = plans.generate(
        "sql-run",
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    runs = ExperimentRunService(ExperimentRunRepository(factory), plans)
    created = runs.create("sql-run", _request(plan.experiments[0].experiment_id))

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(ExperimentRunManifestVersionRow)
        ) == 1
        row = session.scalar(select(ExperimentRunManifestVersionRow))
        assert row is not None
        assert row.run_configuration_sha256 == created.run_configuration_sha256
        assert row.actor_id == "local-researcher"
        assert row.result_provenance == "user_declared"


def test_api_run_data_plot_and_delete_lifecycle_end_to_end() -> None:
    project_id = f"run-e2e-{uuid4().hex[:10]}"
    example = client.get("/api/v1/research/project-claims/examples/tad").json()
    assert client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={"expected_latest_version": 0, "claim": example["claim"]},
    ).status_code == 200
    plan_response = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 0, "claim_versions": [1]},
    )
    plan = plan_response.json()
    artifact = next(
        item for item in plan["artifacts"] if item["artifact_kind"] == "figure"
    )
    experiment_id = artifact["source_experiment_ids"][0]
    create = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-runs",
        json=_request(experiment_id).model_dump(mode="json"),
    )
    assert create.status_code == 200
    run = create.json()
    assert run["revision"] == 1
    assert run["status"] == "registered"

    wrong_actor = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-runs/{run['run_id']}/data",
        data={"actor_id": "wrong-researcher"},
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/csv")},
    )
    assert wrong_actor.status_code == 403

    attached = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-runs/{run['run_id']}/data",
        data={"actor_id": "local-researcher"},
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/csv")},
    )
    assert attached.status_code == 200
    attachment = attached.json()
    assert attachment["run"]["status"] == "data_attached"
    assert attachment["run"]["revision"] == 2
    assert attachment["run"]["data_asset"]["data_sha256"] == hashlib.sha256(
        FIXTURE.read_bytes()
    ).hexdigest()

    plot_request = {
        "upload_id": attachment["upload"]["upload_id"],
        "run_id": run["run_id"],
        "actor_id": "local-researcher",
        "plan_revision": 1,
        "artifact_plan_id": artifact["artifact_id"],
        "plot_kind": "line",
        "x_column": "condition",
        "y_column": "measurement",
        "hue_column": "variant",
        "title": "Synthetic experiment-run smoke test",
        "x_label": "Condition",
        "y_label": "Measurement",
        "x_unit": "not_applicable",
        "y_unit": "arbitrary_unit",
        "legend_title": "Variant",
        "aggregation": "mean",
        "error_bar": "standard_deviation",
        "smoothing": "none",
        "export_formats": ["png"],
        "dpi": 200,
    }
    generated = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts",
        json=plot_request,
    )
    assert generated.status_code == 200
    assert generated.json()["run_id"] == run["run_id"]
    executed = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts/{generated.json()['draft_id']}/execute"
    )
    assert executed.status_code == 200
    assert executed.json()["draft"]["execution"]["status"] == "succeeded"

    history = client.get(
        f"/api/v1/research/projects/{project_id}/experiment-runs/{run['run_id']}/history"
    )
    assert history.status_code == 200
    revisions = history.json()["revisions"]
    assert [item["status"] for item in revisions] == [
        "registered",
        "data_attached",
        "plot_succeeded",
    ]
    assert revisions[-1]["plot_execution"]["code_sha256"] == generated.json()[
        "code_sha256"
    ]

    deleted = client.request(
        "DELETE",
        f"/api/v1/research/projects/{project_id}/experiment-runs/{run['run_id']}/data",
        json={"actor_id": "local-researcher"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "data_deleted"
    assert deleted.json()["data_asset"]["lifecycle_state"] == "deleted"
    image_after_delete = client.get(
        f"/api/v1/research/projects/{project_id}/plot-drafts/{generated.json()['draft_id']}/files/figure.png"
    )
    assert image_after_delete.status_code == 404


def test_metadata_only_run_keeps_hash_but_cannot_generate_plot() -> None:
    project_id = f"metadata-run-{uuid4().hex[:10]}"
    example = client.get("/api/v1/research/project-claims/examples/tad").json()
    client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={"expected_latest_version": 0, "claim": example["claim"]},
    )
    plan = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 0, "claim_versions": [1]},
    ).json()
    artifact = next(
        item for item in plan["artifacts"] if item["artifact_kind"] == "figure"
    )
    request = _request(
        artifact["source_experiment_ids"][0],
        lifecycle=DataLifecyclePolicy(
            mode="metadata_only", normalized_retention_hours=0
        ),
    )
    run = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-runs",
        json=request.model_dump(mode="json"),
    ).json()
    attached = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-runs/{run['run_id']}/data",
        data={"actor_id": "local-researcher"},
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/csv")},
    ).json()
    assert attached["run"]["data_asset"]["lifecycle_state"] == "metadata_only"
    assert attached["run"]["data_asset"]["data_sha256"]

    rejected = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts",
        json={
            "upload_id": attached["upload"]["upload_id"],
            "run_id": run["run_id"],
            "actor_id": "local-researcher",
            "plan_revision": 1,
            "artifact_plan_id": artifact["artifact_id"],
            "plot_kind": "line",
            "x_column": "condition",
            "y_column": "measurement",
            "title": "Must not render",
            "x_label": "Condition",
            "y_label": "Measurement",
            "x_unit": "not_applicable",
            "y_unit": "unitless",
            "aggregation": "none",
            "error_bar": "none",
            "smoothing": "none",
            "export_formats": ["png"],
        },
    )
    assert rejected.status_code == 422
    assert "not available for plotting" in rejected.json()["detail"]
