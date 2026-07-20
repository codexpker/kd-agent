from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.experiment_plan_models import ExperimentPlanBundle
from app.services.experiment_plans import ExperimentPlanVersionConflictError
from app.storage.tables import (
    ArtifactPlanClaimLinkRow,
    ExperimentPlanClaimLinkRow,
    ExperimentPlanVersionRow,
)


class ExperimentPlanRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def latest(self, project_id: str) -> ExperimentPlanBundle | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ExperimentPlanVersionRow)
                .where(ExperimentPlanVersionRow.project_id == project_id)
                .order_by(ExperimentPlanVersionRow.revision.desc())
                .limit(1)
            )
            return self._from_row(row) if row is not None else None

    def list_revisions(self, project_id: str) -> list[ExperimentPlanBundle]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ExperimentPlanVersionRow)
                .where(ExperimentPlanVersionRow.project_id == project_id)
                .order_by(ExperimentPlanVersionRow.revision)
            ).all()
            return [self._from_row(row) for row in rows]

    def get(self, project_id: str, revision: int) -> ExperimentPlanBundle | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ExperimentPlanVersionRow).where(
                    ExperimentPlanVersionRow.project_id == project_id,
                    ExperimentPlanVersionRow.revision == revision,
                )
            )
            return self._from_row(row) if row is not None else None

    def save(
        self, plan: ExperimentPlanBundle, expected_latest_revision: int
    ) -> None:
        with self.session_factory() as session:
            latest = session.scalar(
                select(ExperimentPlanVersionRow)
                .where(ExperimentPlanVersionRow.project_id == plan.project_id)
                .order_by(ExperimentPlanVersionRow.revision.desc())
                .limit(1)
                .with_for_update()
            )
            actual = latest.revision if latest is not None else 0
            if actual != expected_latest_revision:
                raise ExperimentPlanVersionConflictError(
                    f"Expected latest plan revision {expected_latest_revision}, got {actual}"
                )
            session.add(
                ExperimentPlanVersionRow(
                    plan_revision_id=plan.plan_revision_id,
                    plan_id=plan.plan_id,
                    project_id=plan.project_id,
                    revision=plan.revision,
                    supersedes_plan_revision_id=plan.supersedes_plan_revision_id,
                    origin=plan.origin,
                    planner_version=plan.generation_basis.planner_version,
                    plan=plan.model_dump(mode="json"),
                    created_at=plan.created_at,
                )
            )
            session.add_all(
                ExperimentPlanClaimLinkRow(
                    plan_revision_id=plan.plan_revision_id,
                    experiment_id=experiment.experiment_id,
                    claim_version_id=claim_version_id,
                )
                for experiment in plan.experiments
                for claim_version_id in experiment.claim_version_ids
            )
            session.add_all(
                ArtifactPlanClaimLinkRow(
                    plan_revision_id=plan.plan_revision_id,
                    artifact_id=artifact.artifact_id,
                    claim_version_id=claim_version_id,
                )
                for artifact in plan.artifacts
                for claim_version_id in artifact.supports_claim_version_ids
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ExperimentPlanVersionConflictError(
                    "Concurrent experiment-plan revision update or invalid Claim link"
                ) from exc

    @staticmethod
    def _from_row(row: ExperimentPlanVersionRow) -> ExperimentPlanBundle:
        return ExperimentPlanBundle.model_validate(row.plan)
