import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    DocumentArtifact,
    DocumentReference,
    DocumentStructure,
    Section,
)
from app.pdf.contracts import ParsedDocument, PersistenceRight
from app.pdf.persistence import PdfPersistenceResult, require_persistence_right
from app.storage.tables import (
    PaperRow,
    PaperSourceRow,
    PdfArtifactRow,
    PdfBodyReferenceRow,
    PdfParseRunRow,
    PdfSectionRow,
    PdfSourceRow,
)


class PaperNotRegisteredError(LookupError):
    pass


class PaperSourceNotFoundError(LookupError):
    pass


def _content_sha256(parsed: ParsedDocument) -> str:
    payload = json.dumps(
        parsed.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class PdfRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def persist(
        self,
        paper_id: str,
        parsed: ParsedDocument,
        file_size_bytes: int,
        right: PersistenceRight,
        paper_source_key: str | None = None,
    ) -> PdfPersistenceResult:
        confirmed_right = require_persistence_right(right)
        content_sha256 = _content_sha256(parsed)
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            if session.get(PaperRow, paper_id) is None:
                raise PaperNotRegisteredError(
                    f"paper must exist in MySQL before PDF facts can be persisted: {paper_id}"
                )
            paper_source_id = self._resolve_paper_source(
                session, paper_id, paper_source_key
            )
            pdf_source = session.scalar(
                select(PdfSourceRow).where(
                    PdfSourceRow.paper_id == paper_id,
                    PdfSourceRow.file_sha256 == parsed.file_sha256,
                )
            )
            if pdf_source is None:
                pdf_source = PdfSourceRow(
                    paper_id=paper_id,
                    paper_source_id=paper_source_id,
                    file_sha256=parsed.file_sha256,
                    file_size_bytes=file_size_bytes,
                    media_type="application/pdf",
                    rights_basis=confirmed_right.basis,
                    rights_confirmed_by=confirmed_right.confirmed_by,
                    rights_note=confirmed_right.note,
                    rights_confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(pdf_source)
                session.flush()
            elif pdf_source.file_size_bytes != file_size_bytes:
                raise ValueError("stored PDF size conflicts with the matching SHA-256")

            parse_run = session.scalar(
                select(PdfParseRunRow).where(
                    PdfParseRunRow.pdf_source_id == pdf_source.id,
                    PdfParseRunRow.parser_name == parsed.parser_name,
                    PdfParseRunRow.parser_version == parsed.parser_version,
                    PdfParseRunRow.content_sha256 == content_sha256,
                )
            )
            if parse_run is not None:
                return PdfPersistenceResult(
                    paper_id=paper_id,
                    parse_run_id=parse_run.id,
                    action="unchanged",
                )

            parse_run = PdfParseRunRow(
                pdf_source_id=pdf_source.id,
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                content_sha256=content_sha256,
                page_count=parsed.page_count,
                status="succeeded",
                warnings=parsed.warnings,
                created_at=now,
                completed_at=now,
            )
            session.add(parse_run)
            session.flush()
            session.add_all(
                PdfSectionRow(
                    parse_run_id=parse_run.id,
                    local_id=item.id,
                    section_order=index,
                    title=item.title,
                    level=item.level,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_bbox=item.heading_bbox,
                )
                for index, item in enumerate(parsed.sections, start=1)
            )
            artifact_rows = {
                item.id: PdfArtifactRow(
                    parse_run_id=parse_run.id,
                    local_id=item.id,
                    artifact_order=index,
                    artifact_type=item.artifact_type,
                    label=item.label,
                    caption=item.caption,
                    page=item.page,
                    bbox=item.bbox,
                    caption_bbox=item.caption_bbox,
                    table_markdown=item.markdown,
                    table_data=item.table_data,
                )
                for index, item in enumerate(parsed.artifacts, start=1)
            }
            session.add_all(artifact_rows.values())
            session.flush()
            session.add_all(
                PdfBodyReferenceRow(
                    parse_run_id=parse_run.id,
                    artifact_id=artifact_rows[item.artifact_id].id,
                    local_id=item.id,
                    reference_order=index,
                    text=item.text,
                    page=item.page,
                    bbox=item.bbox,
                )
                for index, item in enumerate(parsed.references, start=1)
            )
            return PdfPersistenceResult(
                paper_id=paper_id,
                parse_run_id=parse_run.id,
                action="created",
            )

    def get_document_structure(self, paper_id: str) -> DocumentStructure | None:
        with self._session_factory() as session:
            parse_run = session.scalar(
                select(PdfParseRunRow)
                .join(PdfSourceRow, PdfSourceRow.id == PdfParseRunRow.pdf_source_id)
                .where(
                    PdfSourceRow.paper_id == paper_id,
                    PdfParseRunRow.status == "succeeded",
                )
                .order_by(PdfParseRunRow.completed_at.desc(), PdfParseRunRow.id.desc())
                .limit(1)
            )
            if parse_run is None:
                return None
            pdf_source = session.get(PdfSourceRow, parse_run.pdf_source_id)
            assert pdf_source is not None
            sections = session.scalars(
                select(PdfSectionRow)
                .where(PdfSectionRow.parse_run_id == parse_run.id)
                .order_by(PdfSectionRow.section_order)
            ).all()
            artifacts = session.scalars(
                select(PdfArtifactRow)
                .where(PdfArtifactRow.parse_run_id == parse_run.id)
                .order_by(PdfArtifactRow.artifact_order)
            ).all()
            references = session.scalars(
                select(PdfBodyReferenceRow)
                .where(PdfBodyReferenceRow.parse_run_id == parse_run.id)
                .order_by(PdfBodyReferenceRow.reference_order)
            ).all()
            artifact_local_ids = {item.id: item.local_id for item in artifacts}
            return DocumentStructure(
                paper_id=paper_id,
                source="parsed_pdf",
                parser_name=parse_run.parser_name,
                parser_version=parse_run.parser_version,
                file_sha256=pdf_source.file_sha256,
                page_count=parse_run.page_count,
                sections=[
                    Section(
                        id=item.local_id,
                        title=item.title,
                        level=item.level,
                        page_start=item.page_start,
                        page_end=item.page_end,
                        heading_bbox=item.heading_bbox,
                    )
                    for item in sections
                ],
                artifacts=[
                    DocumentArtifact(
                        id=item.local_id,
                        artifact_type=item.artifact_type,
                        label=item.label,
                        caption=item.caption,
                        page=item.page,
                        bbox=item.bbox,
                        caption_bbox=item.caption_bbox,
                        markdown=item.table_markdown,
                        table_data=item.table_data,
                    )
                    for item in artifacts
                ],
                references=[
                    DocumentReference(
                        id=item.local_id,
                        artifact_id=artifact_local_ids[item.artifact_id],
                        text=item.text,
                        page=item.page,
                        bbox=item.bbox,
                    )
                    for item in references
                ],
                evidence=[],
                warnings=parse_run.warnings,
            )

    @staticmethod
    def _resolve_paper_source(
        session: Session, paper_id: str, source_key: str | None
    ) -> int | None:
        if source_key is None:
            return None
        row = session.scalar(
            select(PaperSourceRow).where(
                PaperSourceRow.paper_id == paper_id,
                PaperSourceRow.source_key == source_key,
            )
        )
        if row is None:
            raise PaperSourceNotFoundError(
                f"PaperSource does not exist for {paper_id}: {source_key}"
            )
        return row.id
