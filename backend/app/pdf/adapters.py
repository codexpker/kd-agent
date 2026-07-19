import contextlib
import hashlib
import io
import re
from pathlib import Path
from typing import Protocol

from app.pdf.contracts import ParsedArtifact, ParsedDocument, ParsedReference, ParsedSection


class PdfParser(Protocol):
    name: str
    version: str

    def parse(self, path: Path) -> ParsedDocument: ...


class PyMuPdfAdapter:
    name = "pymupdf"

    def __init__(self) -> None:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("Install backend[pdf] to use PyMuPDF parsing") from exc
        self.fitz = fitz
        self.version = getattr(fitz, "VersionBind", "unknown")

    def parse(self, path: Path) -> ParsedDocument:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        document = self.fitz.open(path)
        sections: list[ParsedSection] = []
        artifacts: list[ParsedArtifact] = []
        references: list[ParsedReference] = []
        heading = re.compile(r"^(\d+(?:\.\d+)*)\s+(.{2,100})$")
        caption = re.compile(r"^(Figure|Fig\.|Table)\s*(\d+)[:.]?\s*(.*)$", re.I)
        ref_pattern = re.compile(r"\b(?:Figure|Fig\.|Table)\s*\d+\b", re.I)
        try:
            page_lines = [self._page_lines(page) for page in document]
            for page_index, lines in enumerate(page_lines):
                page_number = page_index + 1
                for line, line_bbox in lines:
                    heading_match = heading.match(line)
                    if heading_match:
                        level = heading_match.group(1).count(".") + 1
                        sections.append(
                            ParsedSection(
                                id=f"sec-{len(sections) + 1}",
                                title=heading_match.group(2),
                                level=level,
                                page_start=page_number,
                                page_end=page_number,
                                heading_bbox=line_bbox,
                            )
                        )
                    caption_match = caption.match(line)
                    if caption_match:
                        kind = (
                            "table"
                            if caption_match.group(1).lower().startswith("table")
                            else "figure"
                        )
                        label = (
                            f"{'Table' if kind == 'table' else 'Figure'} "
                            f"{caption_match.group(2)}"
                        )
                        artifacts.append(
                            ParsedArtifact(
                                id=f"art-{len(artifacts) + 1}",
                                artifact_type=kind,
                                label=label,
                                caption=caption_match.group(3),
                                page=page_number,
                                caption_bbox=line_bbox,
                            )
                        )

            self._attach_tables(document, artifacts)
            artifacts_by_label = {item.label.casefold(): item for item in artifacts}
            for page_index, lines in enumerate(page_lines):
                page_number = page_index + 1
                for line, line_bbox in lines:
                    if caption.match(line):
                        continue
                    for match in ref_pattern.finditer(line):
                        normalized = re.sub(
                            r"^(Fig\.)", "Figure", match.group(0), flags=re.I
                        )
                        artifact = artifacts_by_label.get(normalized.casefold())
                        if artifact is not None:
                            references.append(
                                ParsedReference(
                                    id=f"ref-{len(references) + 1}",
                                    artifact_id=artifact.id,
                                    text=line,
                                    page=page_number,
                                    bbox=line_bbox,
                                )
                            )

            for index, section in enumerate(sections):
                next_start = (
                    sections[index + 1].page_start
                    if index + 1 < len(sections)
                    else document.page_count + 1
                )
                section.page_end = max(section.page_start, next_start - 1)
            warnings: list[str] = []
            if not sections:
                warnings.append(
                    "No numbered headings detected; manual review required."
                )
            missing_artifact_bbox = [item.label for item in artifacts if item.bbox is None]
            if missing_artifact_bbox:
                warnings.append(
                    "Artifact bbox was not detected for: "
                    + ", ".join(missing_artifact_bbox)
                )
            missing_table_data = [
                item.label
                for item in artifacts
                if item.artifact_type == "table" and item.table_data is None
            ]
            if missing_table_data:
                warnings.append(
                    "Structured table cells were not detected for: "
                    + ", ".join(missing_table_data)
                )
            return ParsedDocument(
                parser_name=self.name,
                parser_version=self.version,
                file_sha256=digest.hexdigest(),
                page_count=document.page_count,
                sections=sections,
                artifacts=artifacts,
                references=references,
                warnings=warnings,
            )
        finally:
            document.close()

    @staticmethod
    def _page_lines(page: object) -> list[tuple[str, list[float]]]:
        payload = page.get_text("dict")  # type: ignore[attr-defined]
        result: list[tuple[str, list[float]]] = []
        for block in payload.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(
                    str(span.get("text", "")) for span in line.get("spans", [])
                ).strip()
                bbox = line.get("bbox")
                if text and bbox is not None:
                    result.append((text, [float(value) for value in bbox]))
        return result

    @classmethod
    def _attach_tables(
        cls, document: object, artifacts: list[ParsedArtifact]
    ) -> None:
        for page_index, page in enumerate(document):  # type: ignore[arg-type]
            page_number = page_index + 1
            page_artifacts = [
                item
                for item in artifacts
                if item.artifact_type == "table" and item.page == page_number
            ]
            find_tables = getattr(page, "find_tables", None)
            if not page_artifacts or find_tables is None:
                continue
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    tables = list(getattr(find_tables(), "tables", []))
            except Exception:
                continue
            for artifact, table in zip(page_artifacts, tables, strict=False):
                rows = [
                    ["" if cell is None else str(cell) for cell in row]
                    for row in table.extract()
                ]
                artifact.bbox = [float(value) for value in table.bbox]
                artifact.table_data = rows
                artifact.markdown = cls._table_markdown(rows)

    @staticmethod
    def _table_markdown(rows: list[list[str]]) -> str | None:
        if not rows:
            return None
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]

        def render(row: list[str]) -> str:
            return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"

        return "\n".join(
            [render(normalized[0]), render(["---"] * width), *map(render, normalized[1:])]
        )


class GrobidTeiAdapter:
    name = "grobid"
    version = "contract-v1"

    def parse(self, path: Path) -> ParsedDocument:
        raise NotImplementedError("Connect this adapter to a GROBID TEI service in R2 evaluation.")


class MinerUJsonAdapter:
    name = "mineru"
    version = "contract-v1"

    def parse(self, path: Path) -> ParsedDocument:
        raise NotImplementedError("Map MinerU JSON output to ParsedDocument in R2 evaluation.")


def create_pdf_parser(name: str) -> PdfParser:
    if name == "pymupdf":
        return PyMuPdfAdapter()
    raise ValueError(f"unsupported PDF parser: {name}")
