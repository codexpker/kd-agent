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
        *,
        artifact_excerpt: bool = False,
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
                clip = (
                    self._artifact_excerpt_clip(page, artifact)
                    if artifact_excerpt and artifact is not None
                    else None
                )
                scale = 2.0 if clip is not None else 1.6
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    alpha=False,
                    clip=clip,
                )
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

    @staticmethod
    def _artifact_excerpt_clip(page: object, artifact: DocumentArtifact) -> object:
        """Build a disposable reading excerpt without asserting a persisted bbox.

        Figure captions conventionally follow a figure, while table captions usually
        precede a table.  The window is deliberately generous and is never returned as
        parsed layout truth.  Persisted object/caption boxes are included only as visual
        hints for this private, request-time rendering.
        """
        import fitz

        page_rect = fitz.Rect(page.rect)

        def valid_rect(value: list[float] | None) -> object | None:
            if value is None or len(value) != 4:
                return None
            candidate = fitz.Rect(*value) & page_rect
            if candidate.is_empty or candidate.is_infinite:
                return None
            return candidate

        object_rect = valid_rect(artifact.bbox)
        caption_rect = valid_rect(artifact.caption_bbox)
        horizontal = fitz.Rect(
            max(page_rect.x0, 64.0),
            page_rect.y0,
            min(page_rect.x1, page_rect.x1 - 64.0),
            page_rect.y1,
        )

        if caption_rect is not None and artifact.artifact_type == "figure":
            clip = fitz.Rect(
                horizontal.x0,
                max(page_rect.y0, caption_rect.y0 - 300.0),
                horizontal.x1,
                min(page_rect.y1, caption_rect.y1 + 16.0),
            )
        elif caption_rect is not None:
            clip = fitz.Rect(
                horizontal.x0,
                max(page_rect.y0, caption_rect.y0 - 16.0),
                horizontal.x1,
                min(page_rect.y1, caption_rect.y1 + 230.0),
            )
        elif object_rect is not None:
            clip = fitz.Rect(object_rect)
        else:
            return page_rect

        if object_rect is not None:
            nearby = (
                abs(object_rect.y0 - clip.y0) <= 260.0
                or abs(object_rect.y1 - clip.y1) <= 260.0
            )
            if nearby:
                clip |= object_rect
        clip.x0 = max(page_rect.x0, clip.x0 - 14.0)
        clip.x1 = min(page_rect.x1, clip.x1 + 14.0)
        clip.y0 = max(page_rect.y0, clip.y0 - 12.0)
        clip.y1 = min(page_rect.y1, clip.y1 + 12.0)
        return clip & page_rect
