import hashlib
from pathlib import Path

from app.models import DocumentArtifact, DocumentStructure, Section


class PrivatePdfPreviewError(RuntimeError):
    pass


class PrivatePdfNotFoundError(PrivatePdfPreviewError):
    pass


def _find_pdf_by_sha256(root_value: str, expected_sha256: str) -> Path:
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise PrivatePdfNotFoundError("configured private PDF preview root is unavailable")
    for candidate in sorted(root.rglob("*.pdf")):
        if not candidate.is_file():
            continue
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(root):
            continue
        digest = hashlib.sha256()
        with resolved_candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() == expected_sha256:
            return resolved_candidate
    raise PrivatePdfNotFoundError("no local private PDF matches the persisted SHA-256")


class PrivatePdfPreviewService:
    """Render a hash-matched private PDF without exposing its path or raw bytes."""

    def __init__(self, preview_root: str) -> None:
        self.preview_root = preview_root

    def render_page(
        self,
        structure: DocumentStructure,
        page_number: int,
        artifact: DocumentArtifact | None = None,
        section: Section | None = None,
    ) -> bytes:
        if structure.source != "parsed_pdf" or not structure.file_sha256:
            raise PrivatePdfPreviewError("a persisted parsed_pdf structure is required")
        if page_number < 1 or (
            structure.page_count is not None and page_number > structure.page_count
        ):
            raise PrivatePdfPreviewError("page number is outside the parsed document")

        path = _find_pdf_by_sha256(self.preview_root, structure.file_sha256)
        source_bytes = path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != structure.file_sha256:
            raise PrivatePdfNotFoundError(
                "local private PDF changed after SHA-256 matching"
            )
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise PrivatePdfPreviewError("PyMuPDF is unavailable for local preview") from exc

        try:
            with fitz.open(stream=source_bytes, filetype="pdf") as document:
                if page_number > document.page_count:
                    raise PrivatePdfPreviewError(
                        "page number is outside the hash-matched private PDF"
                    )
                page = document[page_number - 1]
                if artifact is not None:
                    self._draw_artifact_highlight(page, artifact)
                if section is not None and section.heading_bbox:
                    self._draw_highlights(page, [section.heading_bbox])
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                return pixmap.tobytes("png")
        except PrivatePdfPreviewError:
            raise
        except Exception as exc:
            raise PrivatePdfPreviewError("failed to render the private PDF preview") from exc

    @staticmethod
    def _draw_artifact_highlight(page: object, artifact: DocumentArtifact) -> None:
        boxes = [item for item in (artifact.bbox, artifact.caption_bbox) if item]
        PrivatePdfPreviewService._draw_highlights(page, boxes)

    @staticmethod
    def _draw_highlights(page: object, boxes: list[list[float]]) -> None:
        import fitz

        for coordinates in boxes:
            if len(coordinates) != 4:
                continue
            rectangle = fitz.Rect(*coordinates)
            if rectangle.is_empty or rectangle.is_infinite:
                continue
            page.draw_rect(
                rectangle,
                color=(0.94, 0.31, 0.13),
                width=1.8,
                overlay=True,
            )
