from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.experiment_run_models import ExperimentRunManifest
from app.services.experiment_runs import ExperimentRunVersionConflictError
from app.storage.tables import ExperimentRunManifestVersionRow


class ExperimentRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def latest(self, project_id: str, run_id: str) -> ExperimentRunManifest | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ExperimentRunManifestVersionRow)
                .where(
                    ExperimentRunManifestVersionRow.project_id == project_id,
                    ExperimentRunManifestVersionRow.run_id == run_id,
                )
                .order_by(ExperimentRunManifestVersionRow.revision.desc())
                .limit(1)
            )
            return self._from_row(row) if row is not None else None

    def list_revisions(
        self, project_id: str, run_id: str
    ) -> list[ExperimentRunManifest]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ExperimentRunManifestVersionRow)
                .where(
                    ExperimentRunManifestVersionRow.project_id == project_id,
                    ExperimentRunManifestVersionRow.run_id == run_id,
                )
                .order_by(ExperimentRunManifestVersionRow.revision)
            ).all()
            return [self._from_row(row) for row in rows]

    def save(self, manifest: ExperimentRunManifest, expected_revision: int) -> None:
        with self.session_factory() as session:
            latest = session.scalar(
                select(ExperimentRunManifestVersionRow)
                .where(
                    ExperimentRunManifestVersionRow.project_id
                    == manifest.project_id,
                    ExperimentRunManifestVersionRow.run_id == manifest.run_id,
                )
                .order_by(ExperimentRunManifestVersionRow.revision.desc())
                .limit(1)
                .with_for_update()
            )
            actual = latest.revision if latest is not None else 0
            if actual != expected_revision:
                raise ExperimentRunVersionConflictError(
                    f"Expected run revision {expected_revision}, got {actual}"
                )
            session.add(
                ExperimentRunManifestVersionRow(
                    run_revision_id=manifest.run_revision_id,
                    run_id=manifest.run_id,
                    project_id=manifest.project_id,
                    revision=manifest.revision,
                    supersedes_run_revision_id=manifest.supersedes_run_revision_id,
                    plan_revision_id=manifest.plan_revision_id,
                    experiment_id=manifest.experiment_id,
                    actor_id=manifest.identity.actor_id,
                    run_configuration_sha256=manifest.run_configuration_sha256,
                    result_provenance=manifest.result_provenance,
                    status=manifest.status,
                    data_sha256=(
                        manifest.data_asset.data_sha256
                        if manifest.data_asset is not None
                        else None
                    ),
                    manifest=manifest.model_dump(mode="json"),
                    created_at=manifest.created_at,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ExperimentRunVersionConflictError(
                    "Concurrent experiment-run revision update or invalid plan link"
                ) from exc

    @staticmethod
    def _from_row(
        row: ExperimentRunManifestVersionRow,
    ) -> ExperimentRunManifest:
        return ExperimentRunManifest.model_validate(row.manifest)
