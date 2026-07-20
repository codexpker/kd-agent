from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.project_claim_models import (
    EvidenceDiagnosisVersion,
    ProjectClaimEnvelope,
    ProjectClaimVersion,
)
from app.services.project_claims import (
    ProjectClaimNotFoundError,
    ProjectClaimVersionConflictError,
)
from app.storage.tables import (
    EvidenceDiagnosisVersionRow,
    ProjectClaimVersionRow,
)


class ProjectClaimRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def latest_claim(self, project_id: str) -> ProjectClaimVersion | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ProjectClaimVersionRow)
                .where(ProjectClaimVersionRow.project_id == project_id)
                .order_by(ProjectClaimVersionRow.version.desc())
                .limit(1)
            )
            return self._claim_from_row(row) if row is not None else None

    def list_claims(self, project_id: str) -> list[ProjectClaimVersion]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ProjectClaimVersionRow)
                .where(ProjectClaimVersionRow.project_id == project_id)
                .order_by(ProjectClaimVersionRow.version)
            ).all()
            return [self._claim_from_row(row) for row in rows]

    def get_envelope(
        self, project_id: str, version: int
    ) -> ProjectClaimEnvelope | None:
        with self.session_factory() as session:
            claim_row = session.scalar(
                select(ProjectClaimVersionRow).where(
                    ProjectClaimVersionRow.project_id == project_id,
                    ProjectClaimVersionRow.version == version,
                )
            )
            if claim_row is None:
                return None
            diagnosis_row = session.scalar(
                select(EvidenceDiagnosisVersionRow)
                .where(
                    EvidenceDiagnosisVersionRow.claim_version_id
                    == claim_row.claim_version_id
                )
                .order_by(EvidenceDiagnosisVersionRow.revision.desc())
                .limit(1)
            )
            if diagnosis_row is None:
                return None
            return ProjectClaimEnvelope(
                claim=self._claim_from_row(claim_row),
                diagnosis=self._diagnosis_from_row(diagnosis_row),
            )

    def save_envelope(
        self,
        envelope: ProjectClaimEnvelope,
        expected_latest_version: int,
    ) -> None:
        with self.session_factory() as session:
            latest = session.scalar(
                select(ProjectClaimVersionRow)
                .where(ProjectClaimVersionRow.project_id == envelope.claim.project_id)
                .order_by(ProjectClaimVersionRow.version.desc())
                .limit(1)
                .with_for_update()
            )
            actual_latest = latest.version if latest is not None else 0
            if actual_latest != expected_latest_version:
                raise ProjectClaimVersionConflictError(
                    f"Expected latest version {expected_latest_version}, got {actual_latest}"
                )
            session.add(self._claim_row(envelope.claim))
            session.add(self._diagnosis_row(envelope.diagnosis))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ProjectClaimVersionConflictError(
                    "Concurrent Project Claim version update"
                ) from exc

    def save_diagnosis(
        self,
        project_id: str,
        version: int,
        diagnosis: EvidenceDiagnosisVersion,
        expected_revision: int,
    ) -> None:
        with self.session_factory() as session:
            claim = session.scalar(
                select(ProjectClaimVersionRow)
                .where(
                    ProjectClaimVersionRow.project_id == project_id,
                    ProjectClaimVersionRow.version == version,
                )
                .with_for_update()
            )
            if claim is None:
                raise ProjectClaimNotFoundError("Project Claim version was not found")
            latest = session.scalar(
                select(EvidenceDiagnosisVersionRow)
                .where(
                    EvidenceDiagnosisVersionRow.claim_version_id
                    == claim.claim_version_id
                )
                .order_by(EvidenceDiagnosisVersionRow.revision.desc())
                .limit(1)
                .with_for_update()
            )
            actual_revision = latest.revision if latest is not None else 0
            if actual_revision != expected_revision:
                raise ProjectClaimVersionConflictError(
                    f"Expected diagnosis revision {expected_revision}, got {actual_revision}"
                )
            session.add(self._diagnosis_row(diagnosis))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ProjectClaimVersionConflictError(
                    "Concurrent evidence-diagnosis revision update"
                ) from exc

    @staticmethod
    def _claim_row(claim: ProjectClaimVersion) -> ProjectClaimVersionRow:
        return ProjectClaimVersionRow(
            claim_version_id=claim.claim_version_id,
            project_id=claim.project_id,
            claim_id=claim.claim_id,
            version=claim.version,
            supersedes_claim_version_id=claim.supersedes_claim_version_id,
            research_question=claim.research_question,
            hypothesis=claim.hypothesis,
            proposed_method=claim.proposed_method,
            target_scenario=claim.target_scenario,
            existing_results=[item.model_dump(mode="json") for item in claim.existing_results],
            origin=claim.origin,
            content_sha256=claim.content_sha256,
            created_at=claim.created_at,
        )

    @staticmethod
    def _diagnosis_row(
        diagnosis: EvidenceDiagnosisVersion,
    ) -> EvidenceDiagnosisVersionRow:
        return EvidenceDiagnosisVersionRow(
            diagnosis_id=diagnosis.diagnosis_id,
            claim_version_id=diagnosis.claim_version_id,
            revision=diagnosis.revision,
            origin=diagnosis.origin,
            planner_version=diagnosis.planner_version,
            language_organizer=diagnosis.language_organizer,
            diagnosis=diagnosis.model_dump(mode="json"),
            created_at=diagnosis.created_at,
        )

    @staticmethod
    def _claim_from_row(row: ProjectClaimVersionRow) -> ProjectClaimVersion:
        return ProjectClaimVersion(
            project_id=row.project_id,
            claim_id=row.claim_id,
            claim_version_id=row.claim_version_id,
            version=row.version,
            supersedes_claim_version_id=row.supersedes_claim_version_id,
            research_question=row.research_question,
            hypothesis=row.hypothesis,
            proposed_method=row.proposed_method,
            target_scenario=row.target_scenario,
            existing_results=row.existing_results,
            origin=row.origin,
            content_sha256=row.content_sha256,
            created_at=row.created_at,
        )

    @staticmethod
    def _diagnosis_from_row(
        row: EvidenceDiagnosisVersionRow,
    ) -> EvidenceDiagnosisVersion:
        return EvidenceDiagnosisVersion.model_validate(row.diagnosis)
