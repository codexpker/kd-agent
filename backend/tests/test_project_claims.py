from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.project_claim_models import (
    EvidenceDiagnosisEditRequest,
    EvidenceRequirementEdit,
    ExistingResult,
    ProjectClaimCreateRequest,
    ProjectClaimInput,
)
from app.services.project_claims import (
    InMemoryProjectClaimStore,
    ProjectClaimService,
    ProjectClaimVersionConflictError,
    tad_project_claim_example,
)
from app.storage.project_claim_repository import ProjectClaimRepository
from app.storage.tables import (
    Base,
    EvidenceDiagnosisVersionRow,
    ProjectClaimVersionRow,
)


client = TestClient(app)


def _claim_input(*, suffix: str = "") -> ProjectClaimInput:
    return ProjectClaimInput(
        research_question=(
            "Does an association-aware detector remain reliable under sensor noise?"
            + suffix
        ),
        hypothesis=(
            "The proposed method degrades more slowly than strong baselines as "
            "predeclared sensor-noise severity increases."
            + suffix
        ),
        proposed_method="A user-defined association-aware detector" + suffix,
        target_scenario="Offline multivariate sensor anomaly detection" + suffix,
        existing_results=[
            ExistingResult(
                label="Prototype observation",
                description="The user reports that a prototype runs; no comparison exists.",
                result_type="partial",
            )
        ],
    )


def _edits(envelope) -> list[EvidenceRequirementEdit]:
    return [
        EvidenceRequirementEdit(
            requirement_type=item.requirement_type,
            why_needed=item.why_needed,
            independent_variables=item.independent_variables,
            controlled_variables=item.controlled_variables,
            output_fields=item.output_fields,
            recommended_artifact=item.recommended_artifact,
            can_support=item.can_support,
            cannot_support=item.cannot_support,
            status=item.status,
            user_notes=item.user_notes,
        )
        for item in envelope.diagnosis.requirements
    ]


def test_rule_planner_preserves_user_claim_and_generates_eight_requirements() -> None:
    service = ProjectClaimService(InMemoryProjectClaimStore())
    source = _claim_input()
    envelope = service.create(
        "tad-noise-study",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=source),
    )

    assert envelope.claim.research_question == source.research_question
    assert envelope.claim.hypothesis == source.hypothesis
    assert envelope.claim.proposed_method == source.proposed_method
    assert envelope.claim.target_scenario == source.target_scenario
    assert envelope.claim.origin == "user_supplied"
    assert envelope.claim.existing_results[0].source == "user_reported"
    assert envelope.claim.existing_results[0].verified is False
    assert envelope.diagnosis.planner_version == "project-claim-evidence-rules-v1"
    assert envelope.diagnosis.language_organizer == "deterministic_templates"
    assert envelope.diagnosis.feasibility_assessment == "not_assessed"
    assert envelope.diagnosis.innovation_assessment == "not_assessed"
    assert {item.requirement_type for item in envelope.diagnosis.requirements} == {
        "main_experiment",
        "strong_baseline",
        "fair_comparison",
        "ablation",
        "parameter_sensitivity",
        "robustness",
        "efficiency",
        "failure_cases",
    }
    for requirement in envelope.diagnosis.requirements:
        assert requirement.validates_claim == source.hypothesis
        assert requirement.independent_variables
        assert requirement.controlled_variables
        assert requirement.output_fields
        assert requirement.recommended_artifact.title
        assert requirement.can_support
        assert requirement.cannot_support


def test_claim_versions_are_immutable_and_optimistically_locked() -> None:
    service = ProjectClaimService(InMemoryProjectClaimStore())
    first = service.create(
        "tad-version-study",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=_claim_input()),
    )
    second = service.create(
        "tad-version-study",
        ProjectClaimCreateRequest(
            expected_latest_version=1,
            claim=_claim_input(suffix=" Revised"),
        ),
    )

    assert first.claim.version == 1
    assert second.claim.version == 2
    assert second.claim.supersedes_claim_version_id == first.claim.claim_version_id
    assert first.claim.content_sha256 != second.claim.content_sha256
    assert [item.version for item in service.history("tad-version-study").versions] == [
        1,
        2,
    ]
    with pytest.raises(ProjectClaimVersionConflictError, match="Expected latest"):
        service.create(
            "tad-version-study",
            ProjectClaimCreateRequest(
                expected_latest_version=1,
                claim=_claim_input(suffix=" Stale"),
            ),
        )


def test_diagnosis_edit_creates_revision_without_changing_claim() -> None:
    service = ProjectClaimService(InMemoryProjectClaimStore())
    created = service.create(
        "tad-edit-study",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=_claim_input()),
    )
    edits = _edits(created)
    edits[0].why_needed = "User-edited rationale for the main experiment."
    edits[0].status = "in_progress"
    edits[0].user_notes = "Dataset split is being prepared."

    updated = service.edit_diagnosis(
        "tad-edit-study",
        1,
        EvidenceDiagnosisEditRequest(expected_revision=1, requirements=edits),
    )

    assert updated.claim == created.claim
    assert updated.diagnosis.revision == 2
    assert updated.diagnosis.origin == "user_edited"
    assert updated.diagnosis.requirements[0].why_needed.startswith("User-edited")
    assert updated.diagnosis.requirements[0].validates_claim == created.claim.hypothesis
    with pytest.raises(ProjectClaimVersionConflictError, match="Expected diagnosis"):
        service.edit_diagnosis(
            "tad-edit-study",
            1,
            EvidenceDiagnosisEditRequest(expected_revision=1, requirements=edits),
        )
    with pytest.raises(ValidationError, match="minimum evidence type"):
        service.edit_diagnosis(
            "tad-edit-study",
            1,
            EvidenceDiagnosisEditRequest(
                expected_revision=2,
                requirements=edits[:-1],
            ),
        )


def test_sqlalchemy_repository_persists_claim_and_diagnosis_versions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = ProjectClaimService(ProjectClaimRepository(factory))

    first = service.create(
        "tad-sql-study",
        ProjectClaimCreateRequest(expected_latest_version=0, claim=_claim_input()),
    )
    second = service.create(
        "tad-sql-study",
        ProjectClaimCreateRequest(
            expected_latest_version=1,
            claim=_claim_input(suffix=" SQL v2"),
        ),
    )
    edits = _edits(second)
    edits[-1].user_notes = "Review failure taxonomy before execution."
    updated = service.edit_diagnosis(
        "tad-sql-study",
        2,
        EvidenceDiagnosisEditRequest(expected_revision=1, requirements=edits),
    )

    assert first.claim.version == 1
    assert service.get("tad-sql-study", 2).diagnosis.revision == 2
    assert updated.diagnosis.requirements[-1].user_notes.startswith("Review")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ProjectClaimVersionRow)) == 2
        assert session.scalar(select(func.count()).select_from(EvidenceDiagnosisVersionRow)) == 3


def test_tad_example_is_explicitly_synthetic_and_contains_no_results() -> None:
    example = tad_project_claim_example()

    assert example.example_kind == "synthetic_tad_project_claim_example"
    assert example.claim.existing_results == []
    assert "no experimental result" in example.disclaimer


def test_project_claim_api_create_history_edit_and_conflicts() -> None:
    project_id = f"api-tad-{uuid4().hex[:12]}"
    example_response = client.get("/api/v1/research/project-claims/examples/tad")
    assert example_response.status_code == 200
    assert example_response.json()["example_kind"] == "synthetic_tad_project_claim_example"

    create_response = client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={
            "expected_latest_version": 0,
            "claim": _claim_input().model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["claim"]["version"] == 1
    assert len(payload["diagnosis"]["requirements"]) == 8

    history_response = client.get(
        f"/api/v1/research/projects/{project_id}/claims"
    )
    assert history_response.status_code == 200
    assert [item["version"] for item in history_response.json()["versions"]] == [1]

    edit_payload = [
        EvidenceRequirementEdit.model_validate(item).model_dump(mode="json")
        for item in payload["diagnosis"]["requirements"]
    ]
    edit_payload[0]["user_notes"] = "Edited through the API."
    edit_response = client.put(
        f"/api/v1/research/projects/{project_id}/claims/1/diagnosis",
        json={"expected_revision": 1, "requirements": edit_payload},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["diagnosis"]["revision"] == 2
    assert edit_response.json()["diagnosis"]["origin"] == "user_edited"

    conflict_response = client.post(
        f"/api/v1/research/projects/{project_id}/claims",
        json={
            "expected_latest_version": 0,
            "claim": _claim_input(suffix=" stale").model_dump(mode="json"),
        },
    )
    assert conflict_response.status_code == 409


def test_project_claim_api_validation_and_not_found_errors() -> None:
    invalid_project = client.post(
        "/api/v1/research/projects/Bad_ID/claims",
        json={
            "expected_latest_version": 0,
            "claim": _claim_input().model_dump(mode="json"),
        },
    )
    missing = client.get("/api/v1/research/projects/missing-project/claims/1")

    assert invalid_project.status_code == 422
    assert missing.status_code == 404
