import hashlib
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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document = self.fitz.open(path)
        sections: list[ParsedSection] = []
        artifacts: list[ParsedArtifact] = []
        references: list[ParsedReference] = []
        heading = re.compile(r"^(\d+(?:\.\d+)*)\s+(.{2,100})$")
        caption = re.compile(r"^(Figure|Fig\.|Table)\s*(\d+)[:.]?\s*(.*)$", re.I)
        ref_pattern = re.compile(r"\b(?:Figure|Fig\.|Table)\s*\d+\b", re.I)
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            lines = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
            for line in lines:
                heading_match = heading.match(line)
                if heading_match:
                    level = heading_match.group(1).count(".") + 1
                    sections.append(ParsedSection(id=f"sec-{len(sections)+1}", title=heading_match.group(2), level=level, page_start=page_number, page_end=page_number))
                caption_match = caption.match(line)
                if caption_match:
                    kind = "table" if caption_match.group(1).lower().startswith("table") else "figure"
                    label = f"{'Table' if kind == 'table' else 'Figure'} {caption_match.group(2)}"
                    artifacts.append(ParsedArtifact(id=f"art-{len(artifacts)+1}", artifact_type=kind, label=label, caption=caption_match.group(3), page=page_number))
                elif ref_pattern.search(line):
                    match = ref_pattern.search(line)
                    normalized = re.sub(r"^(Fig\.)", "Figure", match.group(0), flags=re.I)
                    artifact = next((item for item in artifacts if item.label.casefold() == normalized.casefold()), None)
                    if artifact:
                        references.append(ParsedReference(id=f"ref-{len(references)+1}", artifact_id=artifact.id, text=line, page=page_number))
        for index, section in enumerate(sections):
            next_start = sections[index + 1].page_start if index + 1 < len(sections) else len(document)
            section.page_end = max(section.page_start, next_start)
        warnings = [] if sections else ["No numbered headings detected; manual review required."]
        return ParsedDocument(parser_name=self.name, parser_version=self.version, file_sha256=digest, sections=sections, artifacts=artifacts, references=references, warnings=warnings)


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

