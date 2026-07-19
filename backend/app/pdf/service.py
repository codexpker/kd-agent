import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import (
    DocumentArtifact,
    DocumentReference,
    DocumentStructure,
    Section,
)
from app.pdf.adapters import PdfParser
from app.pdf.contracts import ParsedDocument, PersistenceRight
from app.pdf.persistence import PdfPersistenceResult, require_persistence_right


class PdfLayoutRepository(Protocol):
    def persist(
        self,
        paper_id: str,
        parsed: ParsedDocument,
        file_size_bytes: int,
        right: PersistenceRight,
        paper_source_key: str | None = None,
    ) -> PdfPersistenceResult: ...


@dataclass(frozen=True)
class PdfPreview:
    paper_id: str
    file_sha256: str
    file_size_bytes: int
    parsed: ParsedDocument
    structure: DocumentStructure


class PdfLayoutService:
    def preview(self, paper_id: str, path: Path, parser: PdfParser) -> PdfPreview:
        if not path.is_file():
            raise FileNotFoundError(path)
        file_sha256, file_size_bytes = self._hash_file(path)
        parsed = parser.parse(path)
        if parsed.file_sha256 != file_sha256:
            raise ValueError("parser file_sha256 does not match the input PDF")
        if parsed.parser_name != parser.name or parsed.parser_version != parser.version:
            raise ValueError("parser identity does not match ParsedDocument provenance")
        structure = self._to_document_structure(paper_id, parsed)
        return PdfPreview(
            paper_id=paper_id,
            file_sha256=file_sha256,
            file_size_bytes=file_size_bytes,
            parsed=parsed,
            structure=structure,
        )

    def persist(
        self,
        preview: PdfPreview,
        right: PersistenceRight | None,
        repository: PdfLayoutRepository,
        paper_source_key: str | None = None,
    ) -> PdfPersistenceResult:
        confirmed_right = require_persistence_right(right)
        return repository.persist(
            preview.paper_id,
            preview.parsed,
            preview.file_size_bytes,
            confirmed_right,
            paper_source_key,
        )

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def _to_document_structure(
        paper_id: str, parsed: ParsedDocument
    ) -> DocumentStructure:
        return DocumentStructure(
            paper_id=paper_id,
            source="parsed_pdf",
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            file_sha256=parsed.file_sha256,
            page_count=parsed.page_count,
            sections=[
                Section(
                    id=item.id,
                    title=item.title,
                    level=item.level,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_bbox=item.heading_bbox,
                )
                for item in parsed.sections
            ],
            artifacts=[
                DocumentArtifact(
                    id=item.id,
                    artifact_type=item.artifact_type,
                    label=item.label,
                    caption=item.caption,
                    page=item.page,
                    bbox=item.bbox,
                    caption_bbox=item.caption_bbox,
                    markdown=item.markdown,
                    table_data=item.table_data,
                )
                for item in parsed.artifacts
            ],
            references=[
                DocumentReference(
                    id=item.id,
                    artifact_id=item.artifact_id,
                    text=item.text,
                    page=item.page,
                    bbox=item.bbox,
                )
                for item in parsed.references
            ],
            evidence=[],
            warnings=parsed.warnings,
        )
