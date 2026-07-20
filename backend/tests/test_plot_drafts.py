import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.experiment_plan_models import ExperimentPlanGenerateRequest
from app.main import app
from app.plot_draft_models import PlotGenerationRequest
from app.project_claim_models import ProjectClaimCreateRequest, ProjectClaimInput
from app.services.experiment_plans import ExperimentPlanService, InMemoryExperimentPlanStore
from app.services.plot_drafts import (
    DatasetUploadError,
    InMemoryPlotDraftStore,
    PlotDraftNotFoundError,
    PlotDraftService,
    PlotExecutionError,
)
from app.services.project_claims import InMemoryProjectClaimStore, ProjectClaimService


FIXTURE = (
    Path(__file__).parents[1]
    / "app"
    / "data"
    / "evaluation"
    / "synthetic_plot_smoke.csv"
)
client = TestClient(app)


def _services(project_id: str = "plot-test"):
    claims = ProjectClaimService(InMemoryProjectClaimStore())
    plans = ExperimentPlanService(InMemoryExperimentPlanStore(), claims)
    claim = claims.create(
        project_id,
        ProjectClaimCreateRequest(
            expected_latest_version=0,
            claim=ProjectClaimInput(
                research_question="How does a user-defined measurement vary by condition?",
                hypothesis="The user will evaluate whether measurements differ by condition.",
                proposed_method="User-provided method under test",
                target_scenario="Synthetic plotting pipeline smoke test",
                existing_results=[],
            ),
        ),
    )
    plan = plans.generate(
        project_id,
        ExperimentPlanGenerateRequest(expected_latest_revision=0, claim_versions=[1]),
    )
    artifact = next(item for item in plan.artifacts if item.artifact_kind == "figure")
    service = PlotDraftService(InMemoryPlotDraftStore(), plans)
    return service, claim, plan, artifact


def _request(upload_id: str, artifact_id: str, **overrides) -> PlotGenerationRequest:
    payload = {
        "upload_id": upload_id,
        "plan_revision": 1,
        "artifact_plan_id": artifact_id,
        "plot_kind": "line",
        "x_column": "condition",
        "y_column": "measurement",
        "hue_column": "variant",
        "title": "Synthetic plotting smoke test",
        "x_label": "Condition",
        "y_label": "Measurement",
        "x_unit": "not_applicable",
        "y_unit": "arbitrary_unit",
        "legend_title": "Variant",
        "aggregation": "mean",
        "error_bar": "standard_deviation",
        "smoothing": "none",
        "export_formats": ["png", "svg"],
        "dpi": 200,
    }
    payload.update(overrides)
    return PlotGenerationRequest.model_validate(payload)


def test_csv_upload_validates_schema_types_missing_values_and_hash() -> None:
    service, _, _, _ = _services()
    payload = FIXTURE.read_bytes()
    report = service.upload("plot-test", FIXTURE.name, payload)

    assert report.source_format == "csv"
    assert report.row_count == 8
    assert report.data_sha256 == hashlib.sha256(payload).hexdigest()
    assert report.authenticity_statement == "user_uploaded_not_independently_verified"
    assert {item.name: item.inferred_type for item in report.columns} == {
        "condition": "string",
        "variant": "string",
        "replicate": "integer",
        "measurement": "number",
    }
    assert all(item.missing_count == 0 for item in report.columns)
    assert report.valid is True


def test_json_upload_and_key_field_validation_never_impute() -> None:
    service, _, _, artifact = _services()
    payload = json.dumps(
        [
            {"condition": "low", "variant": "A", "measurement": 1.0},
            {"condition": "high", "variant": "A", "measurement": None},
        ]
    ).encode()
    report = service.upload("plot-test", "observations.json", payload)

    assert any(issue.code == "missing_values" for issue in report.issues)
    with pytest.raises(DatasetUploadError, match="no automatic imputation"):
        service.generate("plot-test", _request(report.upload_id, artifact.artifact_id))


def test_integrity_checks_block_truncation_smoothing_and_overlapping_bars() -> None:
    service, _, _, artifact = _services()
    report = service.upload("plot-test", FIXTURE.name, FIXTURE.read_bytes())
    draft = service.generate(
        "plot-test",
        _request(
            report.upload_id,
            artifact.artifact_id,
            plot_kind="bar",
            aggregation="none",
            error_bar="none",
            smoothing="moving_average",
            y_axis_min=1.5,
        ),
    )

    statuses = {item.check_type: item.status for item in draft.quality_report.checks}
    assert statuses["truncated_axis"] == "error"
    assert statuses["unreasonable_smoothing"] == "error"
    assert statuses["visual_misleading"] == "error"
    with pytest.raises(PlotExecutionError, match="integrity errors"):
        service.execute("plot-test", draft.draft_id)


def test_generated_code_executes_and_every_point_has_source_rows_and_rule() -> None:
    service, _, _, artifact = _services()
    report = service.upload("plot-test", FIXTURE.name, FIXTURE.read_bytes())
    draft = service.generate(
        "plot-test", _request(report.upload_id, artifact.artifact_id)
    )

    assert draft.execution.status == "not_run"
    assert draft.quality_report.has_errors is False
    assert "matplotlib.use(\"Agg\")" in draft.generated_code
    assert "data.normalized.json" in draft.generated_code
    assert "expected_value" not in json.dumps(draft.model_dump(mode="json"))

    response = service.execute("plot-test", draft.draft_id)
    assert response.draft.execution.status == "succeeded"
    assert response.draft.execution.library_versions is not None
    directory = service.store.get_directory(draft.draft_id)
    trace = json.loads((directory / "traceability.json").read_text(encoding="utf-8"))
    assert trace["data_sha256"] == report.data_sha256
    assert len(trace["points"]) == 4
    assert all(point["source_rows"] for point in trace["points"])
    assert all(
        point["aggregation_rule"]
        == "arithmetic_mean_plus_minus_sample_standard_deviation"
        for point in trace["points"]
    )
    manifest = json.loads(
        (directory / "execution_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["code_sha256"] == draft.code_sha256
    assert manifest["normalized_data_sha256"] == draft.normalized_data_sha256
    assert manifest["code_generator_version"] == "matplotlib-traceable-v1"
    assert manifest["generation_parameters"]["dpi"] == 200
    assert manifest["result_policy"] == (
        "user_uploaded_data_only_no_imputation_no_synthetic_results"
    )
    bundle = service.file("plot-test", draft.draft_id, "plot-draft-bundle.zip")
    with zipfile.ZipFile(bundle) as archive:
        assert {
            "plot.py",
            "plot_config.json",
            "data.normalized.json",
            "traceability.json",
            "execution_manifest.json",
            "figure.png",
            "figure.svg",
        } <= set(archive.namelist())


def test_code_hash_tampering_returns_explicit_error_and_no_image() -> None:
    service, _, _, artifact = _services()
    report = service.upload("plot-test", FIXTURE.name, FIXTURE.read_bytes())
    draft = service.generate(
        "plot-test", _request(report.upload_id, artifact.artifact_id)
    )
    directory = service.store.get_directory(draft.draft_id)
    (directory / "plot.py").write_text("raise RuntimeError('tampered')", encoding="utf-8")

    with pytest.raises(PlotExecutionError, match="hash mismatch"):
        service.execute("plot-test", draft.draft_id)
    assert not list(directory.glob("figure.*"))


def test_plot_process_failure_is_explicit_and_exposes_no_image(monkeypatch) -> None:
    service, _, _, artifact = _services()
    report = service.upload("plot-test", FIXTURE.name, FIXTURE.read_bytes())
    draft = service.generate(
        "plot-test", _request(report.upload_id, artifact.artifact_id)
    )
    directory = service.store.get_directory(draft.draft_id)
    monkeypatch.setattr(
        "app.services.plot_drafts.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout="",
            stderr="synthetic executor failure for error-path testing",
        ),
    )

    response = service.execute("plot-test", draft.draft_id)

    assert response.draft.execution.status == "failed"
    assert response.draft.execution.error_code == "plot_process_failed"
    assert response.draft.execution.error_message
    assert response.draft.execution.generated_files == []
    assert not list(directory.glob("figure.*"))
    with pytest.raises(PlotDraftNotFoundError, match="not found"):
        service.file("plot-test", draft.draft_id, "figure.png")


def test_api_upload_generate_execute_preview_and_download() -> None:
    project_id = f"plot-e2e-{uuid4().hex[:10]}"
    example = client.get("/api/v1/research/project-claims/examples/tad").json()
    assert client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={"expected_latest_version": 0, "claim": example["claim"]},
    ).status_code == 200
    plan_response = client.post(
        f"/api/v1/research/projects/{project_id}/experiment-plans",
        json={"expected_latest_revision": 0, "claim_versions": [1]},
    )
    assert plan_response.status_code == 200
    artifact = next(
        item for item in plan_response.json()["artifacts"] if item["artifact_kind"] == "figure"
    )
    upload = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts/uploads",
        files={"file": (FIXTURE.name, FIXTURE.read_bytes(), "text/csv")},
    )
    assert upload.status_code == 200
    request = _request(upload.json()["upload_id"], artifact["artifact_id"])
    generated = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts",
        json=request.model_dump(mode="json"),
    )
    assert generated.status_code == 200
    assert generated.json()["execution"]["status"] == "not_run"
    draft_id = generated.json()["draft_id"]
    executed = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts/{draft_id}/execute"
    )
    assert executed.status_code == 200
    assert executed.json()["draft"]["execution"]["status"] == "succeeded"
    image = client.get(
        f"/api/v1/research/projects/{project_id}/plot-drafts/{draft_id}/files/figure.png"
    )
    bundle = client.get(
        f"/api/v1/research/projects/{project_id}/plot-drafts/{draft_id}/files/plot-draft-bundle.zip"
    )
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")
    assert bundle.status_code == 200
    assert bundle.content.startswith(b"PK")


def test_successful_execution_is_immutable() -> None:
    service, _, _, artifact = _services()
    report = service.upload("plot-test", FIXTURE.name, FIXTURE.read_bytes())
    draft = service.generate(
        "plot-test", _request(report.upload_id, artifact.artifact_id)
    )
    first = service.execute("plot-test", draft.draft_id)
    assert first.draft.execution.status == "succeeded"

    with pytest.raises(PlotExecutionError, match="immutable"):
        service.execute("plot-test", draft.draft_id)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("results.txt", b"a,b\n1,2\n"),
        ("results.json", b'{"not": "an array"}'),
        ("results.csv", b"x,y\n1,\n"),
    ],
)
def test_invalid_upload_or_key_schema_returns_clear_error(filename: str, content: bytes) -> None:
    project_id = f"plot-negative-{uuid4().hex[:10]}"
    response = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts/uploads",
        files={"file": (filename, content, "application/octet-stream")},
    )
    if filename == "results.csv":
        assert response.status_code == 200
        assert any(item["code"] == "missing_values" for item in response.json()["issues"])
    else:
        assert response.status_code == 422


def test_api_rejects_client_python_and_duplicate_json_keys() -> None:
    project_id = f"plot-contract-{uuid4().hex[:10]}"
    duplicate = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts/uploads",
        files={
            "file": (
                "duplicate.json",
                b'[{"measurement": 1, "measurement": 2}]',
                "application/json",
            )
        },
    )
    arbitrary_code = client.post(
        f"/api/v1/research/projects/{project_id}/plot-drafts",
        json={"python_code": "import os; os.system('echo forbidden')"},
    )

    assert duplicate.status_code == 422
    assert "duplicate JSON object key" in duplicate.json()["detail"]
    assert arbitrary_code.status_code == 422
