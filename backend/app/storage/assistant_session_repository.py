from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.assistant_models import (
    AssistantMessage,
    AssistantSession,
    AssistantToolRun,
)
from app.services.assistant_sessions import (
    AssistantSessionConflictError,
    AssistantSessionNotFoundError,
)
from app.storage.tables import (
    AssistantMessageEvidenceRow,
    AssistantMessageRow,
    AssistantMessageToolRunRow,
    AssistantSessionRow,
    AssistantToolRunEvidenceRow,
    AssistantToolRunRow,
)


class AssistantSessionRepository:
    """MySQL-authoritative assistant history with optimistic message-count writes."""

    storage = "mysql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, assistant_session: AssistantSession) -> AssistantSession:
        stored = assistant_session.model_copy(update={"storage": "mysql"}, deep=True)
        with self.session_factory() as db:
            db.add(self._session_row(stored))
            self._insert_children(db, stored)
            db.commit()
        return stored

    def get(self, session_id: str) -> AssistantSession | None:
        with self.session_factory() as db:
            row = db.get(AssistantSessionRow, session_id)
            if row is None:
                return None
            return self._load(db, row)

    def save(
        self,
        assistant_session: AssistantSession,
        expected_message_count: int,
    ) -> AssistantSession:
        stored = assistant_session.model_copy(update={"storage": "mysql"}, deep=True)
        with self.session_factory() as db:
            result = db.execute(
                update(AssistantSessionRow)
                .where(
                    AssistantSessionRow.session_id == stored.session_id,
                    AssistantSessionRow.message_count == expected_message_count,
                )
                .values(
                    backend=stored.backend,
                    provider_status=stored.provider_status,
                    provider_name=stored.provider_name,
                    model_label=stored.model_label,
                    prompt_version=stored.prompt_version,
                    storage="mysql",
                    warnings=list(stored.warnings),
                    message_count=len(stored.messages),
                    updated_at=stored.updated_at,
                )
            )
            if result.rowcount != 1:
                exists = db.scalar(
                    select(AssistantSessionRow.session_id).where(
                        AssistantSessionRow.session_id == stored.session_id
                    )
                )
                db.rollback()
                if exists is None:
                    raise AssistantSessionNotFoundError(stored.session_id)
                raise AssistantSessionConflictError(
                    "assistant session changed; reload history before retrying"
                )

            self._delete_children(db, stored.session_id)
            self._insert_children(db, stored)
            db.commit()
        return stored

    @staticmethod
    def _session_row(assistant_session: AssistantSession) -> AssistantSessionRow:
        return AssistantSessionRow(
            session_id=assistant_session.session_id,
            trace_id=assistant_session.trace_id,
            paper_id=assistant_session.paper_id,
            backend=assistant_session.backend,
            provider_status=assistant_session.provider_status,
            provider_name=assistant_session.provider_name,
            model_label=assistant_session.model_label,
            prompt_version=assistant_session.prompt_version,
            storage="mysql",
            warnings=list(assistant_session.warnings),
            message_count=len(assistant_session.messages),
            created_at=assistant_session.created_at,
            updated_at=assistant_session.updated_at,
        )

    @staticmethod
    def _delete_children(db: Session, session_id: str) -> None:
        message_ids = list(
            db.scalars(
                select(AssistantMessageRow.message_id).where(
                    AssistantMessageRow.session_id == session_id
                )
            )
        )
        run_ids = list(
            db.scalars(
                select(AssistantToolRunRow.run_id).where(
                    AssistantToolRunRow.session_id == session_id
                )
            )
        )
        if message_ids:
            db.execute(
                delete(AssistantMessageToolRunRow).where(
                    AssistantMessageToolRunRow.message_id.in_(message_ids)
                )
            )
            db.execute(
                delete(AssistantMessageEvidenceRow).where(
                    AssistantMessageEvidenceRow.message_id.in_(message_ids)
                )
            )
        if run_ids:
            db.execute(
                delete(AssistantMessageToolRunRow).where(
                    AssistantMessageToolRunRow.run_id.in_(run_ids)
                )
            )
            db.execute(
                delete(AssistantToolRunEvidenceRow).where(
                    AssistantToolRunEvidenceRow.run_id.in_(run_ids)
                )
            )
        db.execute(
            delete(AssistantMessageRow).where(
                AssistantMessageRow.session_id == session_id
            )
        )
        db.execute(
            delete(AssistantToolRunRow).where(
                AssistantToolRunRow.session_id == session_id
            )
        )

    @staticmethod
    def _insert_children(db: Session, assistant_session: AssistantSession) -> None:
        for order, message in enumerate(assistant_session.messages):
            db.add(
                AssistantMessageRow(
                    message_id=message.message_id,
                    session_id=assistant_session.session_id,
                    message_order=order,
                    role=message.role,
                    origin=message.origin,
                    content=message.content,
                    provider_request_id=message.provider_request_id,
                    created_at=message.created_at,
                )
            )
        for order, run in enumerate(assistant_session.tool_runs):
            db.add(
                AssistantToolRunRow(
                    run_id=run.run_id,
                    session_id=assistant_session.session_id,
                    run_order=order,
                    tool_name=run.tool_name,
                    status=run.status,
                    source=run.source,
                    input_summary=run.input_summary,
                    result_summary=run.result_summary,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                )
            )
        db.flush()

        for message in assistant_session.messages:
            db.add_all(
                AssistantMessageEvidenceRow(
                    message_id=message.message_id,
                    evidence_id=evidence_id,
                    evidence_order=order,
                )
                for order, evidence_id in enumerate(message.evidence_ids)
            )
            db.add_all(
                AssistantMessageToolRunRow(
                    message_id=message.message_id,
                    run_id=run_id,
                    run_order=order,
                )
                for order, run_id in enumerate(message.tool_run_ids)
            )
        for run in assistant_session.tool_runs:
            db.add_all(
                AssistantToolRunEvidenceRow(
                    run_id=run.run_id,
                    evidence_id=evidence_id,
                    evidence_order=order,
                )
                for order, evidence_id in enumerate(run.evidence_ids)
            )

    def _load(self, db: Session, row: AssistantSessionRow) -> AssistantSession:
        message_rows = list(
            db.scalars(
                select(AssistantMessageRow)
                .where(AssistantMessageRow.session_id == row.session_id)
                .order_by(AssistantMessageRow.message_order)
            )
        )
        run_rows = list(
            db.scalars(
                select(AssistantToolRunRow)
                .where(AssistantToolRunRow.session_id == row.session_id)
                .order_by(AssistantToolRunRow.run_order)
            )
        )
        message_evidence = self._ordered_links(
            db,
            AssistantMessageEvidenceRow.message_id,
            AssistantMessageEvidenceRow.evidence_id,
            AssistantMessageEvidenceRow.evidence_order,
            [item.message_id for item in message_rows],
        )
        run_evidence = self._ordered_links(
            db,
            AssistantToolRunEvidenceRow.run_id,
            AssistantToolRunEvidenceRow.evidence_id,
            AssistantToolRunEvidenceRow.evidence_order,
            [item.run_id for item in run_rows],
        )
        message_runs = self._ordered_links(
            db,
            AssistantMessageToolRunRow.message_id,
            AssistantMessageToolRunRow.run_id,
            AssistantMessageToolRunRow.run_order,
            [item.message_id for item in message_rows],
        )
        tool_runs = [
            AssistantToolRun(
                run_id=item.run_id,
                tool_name=item.tool_name,
                status=item.status,
                source=item.source,
                input_summary=item.input_summary,
                result_summary=item.result_summary,
                evidence_ids=run_evidence.get(item.run_id, []),
                started_at=self._utc(item.started_at),
                completed_at=self._utc(item.completed_at),
            )
            for item in run_rows
        ]
        messages = [
            AssistantMessage(
                message_id=item.message_id,
                role=item.role,
                origin=item.origin,
                content=item.content,
                evidence_ids=message_evidence.get(item.message_id, []),
                tool_run_ids=message_runs.get(item.message_id, []),
                provider_request_id=item.provider_request_id,
                created_at=self._utc(item.created_at),
            )
            for item in message_rows
        ]
        return AssistantSession(
            session_id=row.session_id,
            trace_id=row.trace_id,
            paper_id=row.paper_id,
            backend=row.backend,
            provider_status=row.provider_status,
            provider_name=row.provider_name,
            model_label=row.model_label,
            prompt_version=row.prompt_version,
            storage="mysql",
            created_at=self._utc(row.created_at),
            updated_at=self._utc(row.updated_at),
            messages=messages,
            tool_runs=tool_runs,
            warnings=list(row.warnings),
        )

    @staticmethod
    def _ordered_links(
        db: Session,
        owner_column: object,
        value_column: object,
        order_column: object,
        owner_ids: list[str],
    ) -> dict[str, list[str]]:
        if not owner_ids:
            return {}
        rows = db.execute(
            select(owner_column, value_column)
            .where(owner_column.in_(owner_ids))
            .order_by(owner_column, order_column)
        ).all()
        result: dict[str, list[str]] = {}
        for owner_id, value in rows:
            result.setdefault(owner_id, []).append(value)
        return result

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
