import contextlib
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

from app.pdf.contracts import ParsedArtifact, ParsedDocument, ParsedReference, ParsedSection


class PdfParser(Protocol):
    name: str
    version: str

    def parse(self, path: Path) -> ParsedDocument: ...


class ExternalParserUnavailableError(RuntimeError):
    """Raised when an optional external parser has not been configured."""


class ParserOutputError(ValueError):
    """Raised when an external parser returns an unsupported or invalid payload."""


class GrobidClient(Protocol):
    version: str

    def process_pdf(self, path: Path) -> str | bytes: ...


class MinerUClient(Protocol):
    version: str

    def analyze_pdf(
        self, path: Path
    ) -> Mapping[str, Any] | Sequence[Mapping[str, Any]]: ...


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _first_child(element: ET.Element, *names: str) -> ET.Element | None:
    expected = set(names)
    return next(
        (child for child in element if _local_name(child.tag) in expected), None
    )


def _tei_coordinates(element: ET.Element | None) -> tuple[int, list[float] | None]:
    if element is None:
        return 0, None
    raw = element.attrib.get("coords")
    if not raw:
        return 0, None
    coordinates: list[tuple[int, float, float, float, float]] = []
    for raw_bbox in raw.split(";"):
        parts = raw_bbox.split(",")
        if len(parts) != 5:
            continue
        try:
            page = int(float(parts[0]))
            x, y, width, height = (float(value) for value in parts[1:])
        except ValueError:
            continue
        if page > 0 and width >= 0 and height >= 0:
            coordinates.append((page, x, y, width, height))
    if not coordinates:
        return 0, None
    page = coordinates[0][0]
    same_page = [item for item in coordinates if item[0] == page]
    x0 = min(item[1] for item in same_page)
    y0 = min(item[2] for item in same_page)
    x1 = max(item[1] + item[3] for item in same_page)
    y1 = max(item[2] + item[4] for item in same_page)
    return page, [x0, y0, x1, y1]


def _bbox(value: object) -> list[float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _normalized_table_data(value: object) -> list[list[str]] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    rows: list[list[str]] = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            return None
        rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag.casefold() == "tr":
            self._row = []
        elif tag.casefold() in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag.casefold() == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"td", "th"} and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
        elif tag.casefold() == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _table_data_from_html(value: str) -> list[list[str]] | None:
    if "<table" not in value.casefold():
        return None
    parser = _TableHTMLParser()
    parser.feed(value)
    parser.close()
    return parser.rows or None


def _unique_id(candidate: str, prefix: str, used: set[str]) -> str:
    base = candidate.strip() or f"{prefix}-{len(used) + 1}"
    result = base
    suffix = 2
    while result in used:
        result = f"{base}-{suffix}"
        suffix += 1
    used.add(result)
    return result


def _set_section_page_ends(
    sections: list[ParsedSection], page_count: int
) -> None:
    for index, section in enumerate(sections):
        next_peer_page = next(
            (
                item.page_start
                for item in sections[index + 1 :]
                if item.level <= section.level
            ),
            page_count + 1,
        )
        section.page_end = max(section.page_start, next_peer_page - 1)


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
        file_sha256 = _hash_path(path)
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

            _set_section_page_ends(sections, document.page_count)
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
                file_sha256=file_sha256,
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

    def __init__(self, client: GrobidClient | None = None) -> None:
        self.client = client
        self.version = client.version if client is not None else "unconfigured"

    def parse(self, path: Path) -> ParsedDocument:
        if self.client is None:
            raise ExternalParserUnavailableError(
                "GROBID is unavailable: configure a GrobidClient; "
                "no synthetic result was substituted"
            )
        payload = self.client.process_pdf(path)
        return self.map_tei(
            payload,
            file_sha256=_hash_path(path),
            parser_version=self.client.version,
        )

    @classmethod
    def map_tei(
        cls,
        payload: str | bytes,
        *,
        file_sha256: str,
        parser_version: str,
    ) -> ParsedDocument:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ParserOutputError(f"invalid GROBID TEI XML: {exc}") from exc

        page_by_element: dict[int, int | None] = {}
        page_numbers: list[int] = []

        def index_pages(
            element: ET.Element,
            current_pb_page: int | None,
            ancestor_coordinate_page: int | None,
        ) -> int | None:
            element_name = _local_name(element.tag)
            if element_name == "surface":
                try:
                    surface_page = int(element.attrib.get("n", ""))
                except ValueError:
                    pass
                else:
                    if surface_page > 0:
                        page_numbers.append(surface_page)
            elif element_name == "pb":
                try:
                    current_pb_page = int(
                        element.attrib.get("n", current_pb_page or 1)
                    )
                except ValueError:
                    pass
                if current_pb_page is not None and current_pb_page > 0:
                    page_numbers.append(current_pb_page)
            coordinate_page, _ = _tei_coordinates(element)
            if coordinate_page:
                page_numbers.append(coordinate_page)
            page_by_element[id(element)] = (
                coordinate_page
                or ancestor_coordinate_page
                or current_pb_page
            )
            for child in element:
                current_pb_page = index_pages(
                    child,
                    current_pb_page,
                    coordinate_page or ancestor_coordinate_page,
                )
            return current_pb_page

        index_pages(root, None, None)
        warnings: list[str] = []
        sections: list[ParsedSection] = []
        used_sections: set[str] = set()

        def collect_sections(element: ET.Element, div_depth: int) -> None:
            is_div = _local_name(element.tag) == "div"
            level = div_depth + 1 if is_div else div_depth
            if is_div:
                heading = _first_child(element, "head")
                title = _text(heading)
                if title:
                    coordinate_page, heading_bbox = _tei_coordinates(heading)
                    page = coordinate_page or page_by_element.get(id(heading))
                    if page is None:
                        warnings.append(
                            f"GROBID section {title!r} was skipped because it has "
                            "no page coordinates"
                        )
                    else:
                        xml_id = element.attrib.get(
                            "{http://www.w3.org/XML/1998/namespace}id", ""
                        )
                        sections.append(
                            ParsedSection(
                                id=_unique_id(xml_id, "sec", used_sections),
                                title=title,
                                level=max(level, 1),
                                page_start=page,
                                page_end=page,
                                heading_bbox=heading_bbox,
                            )
                        )
            for child in element:
                collect_sections(child, level)

        collect_sections(root, 0)

        artifacts: list[ParsedArtifact] = []
        used_artifacts: set[str] = set()
        raw_artifact_ids: dict[str, str] = {}
        for element in root.iter():
            if _local_name(element.tag) != "figure":
                continue
            artifact_type = (
                "table" if element.attrib.get("type", "").casefold() == "table" else "figure"
            )
            xml_id = element.attrib.get(
                "{http://www.w3.org/XML/1998/namespace}id", ""
            )
            artifact_id = _unique_id(xml_id, "art", used_artifacts)
            heading = _first_child(element, "head", "label")
            description = _first_child(element, "figDesc")
            label = _text(heading) or xml_id or artifact_id
            caption = _text(description)
            element_page, artifact_bbox = _tei_coordinates(element)
            caption_page, caption_bbox = _tei_coordinates(description)
            page = element_page or caption_page or page_by_element.get(id(element))
            if page is None:
                warnings.append(
                    f"GROBID artifact {label!r} was skipped because it has no page coordinates"
                )
                continue
            table_data = None
            if artifact_type == "table":
                rows = []
                for row in (
                    child for child in element.iter() if _local_name(child.tag) == "row"
                ):
                    rows.append(
                        [
                            _text(cell)
                            for cell in row
                            if _local_name(cell.tag) == "cell"
                        ]
                    )
                table_data = rows or None
            artifacts.append(
                ParsedArtifact(
                    id=artifact_id,
                    artifact_type=artifact_type,
                    label=label,
                    caption=caption,
                    page=page,
                    bbox=artifact_bbox,
                    caption_bbox=caption_bbox,
                    table_data=table_data,
                    markdown=(
                        PyMuPdfAdapter._table_markdown(table_data)
                        if table_data is not None
                        else None
                    ),
                )
            )
            if xml_id:
                raw_artifact_ids[xml_id] = artifact_id
            if not caption:
                warnings.append(f"GROBID artifact {label!r} has no figDesc caption")

        references: list[ParsedReference] = []
        used_references: set[str] = set()
        for element in root.iter():
            if _local_name(element.tag) != "ref" or element.attrib.get(
                "type", ""
            ).casefold() not in {"figure", "table"}:
                continue
            target = element.attrib.get("target", "").split()[0].lstrip("#")
            artifact_id = raw_artifact_ids.get(target)
            if artifact_id is None:
                warnings.append(
                    f"GROBID reference target {target or '<missing>'!r} was not mapped"
                )
                continue
            coordinate_page, reference_bbox = _tei_coordinates(element)
            page = coordinate_page or page_by_element.get(id(element))
            if page is None:
                warnings.append(
                    f"GROBID reference to {target!r} was skipped because it has no page coordinates"
                )
                continue
            xml_id = element.attrib.get(
                "{http://www.w3.org/XML/1998/namespace}id", ""
            )
            references.append(
                ParsedReference(
                    id=_unique_id(xml_id, "ref", used_references),
                    artifact_id=artifact_id,
                    text=_text(element),
                    page=page,
                    bbox=reference_bbox,
                )
            )

        page_count = max(
            [
                1,
                *page_numbers,
                *(item.page_start for item in sections),
                *(item.page for item in artifacts),
                *(item.page for item in references),
            ]
        )
        _set_section_page_ends(sections, page_count)
        if not sections:
            warnings.append("GROBID TEI contains no headed section divs")
        return ParsedDocument(
            parser_name=cls.name,
            parser_version=parser_version,
            file_sha256=file_sha256,
            page_count=page_count,
            sections=sections,
            artifacts=artifacts,
            references=references,
            warnings=warnings,
        )


class MinerUJsonAdapter:
    name = "mineru"

    def __init__(self, client: MinerUClient | None = None) -> None:
        self.client = client
        self.version = client.version if client is not None else "unconfigured"

    def parse(self, path: Path) -> ParsedDocument:
        if self.client is None:
            raise ExternalParserUnavailableError(
                "MinerU is unavailable: configure a MinerUClient; "
                "no synthetic result was substituted"
            )
        payload = self.client.analyze_pdf(path)
        return self.map_json(
            payload,
            file_sha256=_hash_path(path),
            parser_version=self.client.version,
        )

    @staticmethod
    def _block_text(block: Mapping[str, Any]) -> str:
        for key in ("text", "content"):
            if isinstance(block.get(key), str):
                return " ".join(str(block[key]).split())
        parts: list[str] = []
        children = (
            block.get("blocks", [])
            or block.get("lines", [])
            or block.get("spans", [])
            or []
        )
        for child in children:
            if isinstance(child, Mapping):
                value = MinerUJsonAdapter._block_text(child)
                if value:
                    parts.append(value)
        return " ".join(parts)

    @staticmethod
    def _caption(block: Mapping[str, Any], artifact_type: str) -> str:
        caption_keys = (
            ("caption", "table_caption")
            if artifact_type == "table"
            else ("caption", "figure_caption", "image_caption", "chart_caption")
        )
        for key in caption_keys:
            value = block.get(key)
            if isinstance(value, str):
                return " ".join(value.split())
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                text = " ".join(str(item) for item in value if item is not None)
                if text:
                    return " ".join(text.split())
        for child in block.get("blocks", []) or []:
            if isinstance(child, Mapping) and str(child.get("type", "")).endswith(
                "_caption"
            ):
                return MinerUJsonAdapter._block_text(child)
        return ""

    @staticmethod
    def _caption_bbox(
        block: Mapping[str, Any], artifact_type: str
    ) -> list[float] | None:
        direct = _bbox(block.get("caption_bbox"))
        if direct is not None:
            return direct
        prefixes = {"table"} if artifact_type == "table" else {
            "figure",
            "image",
            "chart",
        }
        for child in block.get("blocks", []) or []:
            if not isinstance(child, Mapping):
                continue
            child_type = str(child.get("type", "")).casefold()
            if child_type.endswith("_caption") and child_type.split("_", 1)[0] in prefixes:
                return _bbox(child.get("bbox"))
        return None

    @staticmethod
    def _table_html(block: Mapping[str, Any]) -> str | None:
        direct = block.get("table_body")
        if isinstance(direct, str) and "<table" in direct.casefold():
            return direct
        for child in block.get("blocks", []) or []:
            if not isinstance(child, Mapping):
                continue
            if str(child.get("type", "")).casefold() == "table_body":
                for key in ("html", "content", "table_body"):
                    value = child.get(key)
                    if isinstance(value, str) and "<table" in value.casefold():
                        return value
                nested_text = MinerUJsonAdapter._block_text(child)
                if "<table" in nested_text.casefold():
                    return nested_text
        return None

    @classmethod
    def map_json(
        cls,
        payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        file_sha256: str,
        parser_version: str,
    ) -> ParsedDocument:
        if isinstance(payload, Mapping):
            raw_pages = payload.get("pages", payload.get("pdf_info"))
            root_references: object = payload.get("references", [])
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
            for raw_block in payload:
                if not isinstance(raw_block, Mapping):
                    raise ParserOutputError(
                        "each MinerU content-list block must be an object"
                    )
                try:
                    page_index = int(raw_block.get("page_idx", 0))
                except (TypeError, ValueError) as exc:
                    raise ParserOutputError(
                        "MinerU content-list page_idx must be an integer"
                    ) from exc
                grouped[page_index].append(raw_block)
            raw_pages = [
                {"page_idx": page_index, "blocks": grouped[page_index]}
                for page_index in sorted(grouped)
            ]
            root_references = []
        else:
            raw_pages = None
            root_references = []
        if not isinstance(raw_pages, Sequence) or isinstance(raw_pages, (str, bytes)):
            raise ParserOutputError(
                "MinerU JSON must be a content-list array or contain pages/pdf_info"
            )
        if not raw_pages:
            raise ParserOutputError("MinerU JSON contains no pages")

        sections: list[ParsedSection] = []
        artifacts: list[ParsedArtifact] = []
        references: list[ParsedReference] = []
        warnings: list[str] = []
        used_sections: set[str] = set()
        used_artifacts: set[str] = set()
        used_references: set[str] = set()
        artifact_aliases: dict[str, str] = {}
        reference_candidates: list[tuple[Mapping[str, Any], int]] = []
        page_count = 0

        for offset, raw_page in enumerate(raw_pages):
            if not isinstance(raw_page, Mapping):
                raise ParserOutputError("each MinerU page must be an object")
            try:
                if raw_page.get("page_number") is not None:
                    page = int(raw_page["page_number"])
                else:
                    page = int(raw_page.get("page_idx", offset)) + 1
            except (TypeError, ValueError) as exc:
                raise ParserOutputError("MinerU page number must be an integer") from exc
            if page < 1:
                raise ParserOutputError("MinerU page number must be positive")
            page_count = max(page_count, page)
            blocks = raw_page.get("blocks", raw_page.get("para_blocks", []))
            if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)):
                raise ParserOutputError("MinerU page blocks must be an array")
            for raw_block in blocks:
                if not isinstance(raw_block, Mapping):
                    continue
                block_type = str(
                    raw_block.get("type", raw_block.get("block_type", ""))
                ).casefold()
                raw_id = str(raw_block.get("id", raw_block.get("block_id", "")))
                raw_text_level = raw_block.get("text_level")
                try:
                    text_level = int(raw_text_level or 0)
                except (TypeError, ValueError):
                    text_level = 0
                if block_type in {
                    "title",
                    "section_title",
                    "heading",
                    "header",
                } or (block_type == "text" and text_level > 0):
                    title = cls._block_text(raw_block)
                    if not title:
                        warnings.append("MinerU heading without text was skipped")
                        continue
                    raw_level = raw_block.get(
                        "level",
                        raw_block.get("heading_level", text_level or 1),
                    )
                    try:
                        level = max(int(raw_level), 1)
                    except (TypeError, ValueError):
                        level = 1
                        warnings.append(
                            f"MinerU heading {title!r} has invalid level; defaulted to 1"
                        )
                    sections.append(
                        ParsedSection(
                            id=_unique_id(raw_id, "sec", used_sections),
                            title=title,
                            level=level,
                            page_start=page,
                            page_end=page,
                            heading_bbox=_bbox(raw_block.get("bbox")),
                        )
                    )
                elif block_type in {"image", "figure", "chart", "table"}:
                    artifact_type = "table" if block_type == "table" else "figure"
                    artifact_id = _unique_id(raw_id, "art", used_artifacts)
                    label = str(raw_block.get("label", "")).strip()
                    caption = cls._caption(raw_block, artifact_type)
                    if not label:
                        match = re.match(
                            r"((?:Figure|Fig\.|Table)\s*\d+)", caption, re.I
                        )
                        label = match.group(1) if match else (raw_id or artifact_id)
                        if match:
                            caption = caption[match.end() :].lstrip(" .:-")
                    table_html = (
                        cls._table_html(raw_block)
                        if artifact_type == "table"
                        else None
                    )
                    table_data = None
                    if artifact_type == "table":
                        table_data = _normalized_table_data(
                            raw_block.get("table_data", raw_block.get("cells"))
                        )
                        if table_data is None and table_html is not None:
                            table_data = _table_data_from_html(table_html)
                    markdown_value = raw_block.get(
                        "markdown", raw_block.get("table_markdown")
                    )
                    markdown = (
                        str(markdown_value) if markdown_value is not None else None
                    )
                    if artifact_type == "table" and markdown is None and table_data:
                        markdown = PyMuPdfAdapter._table_markdown(table_data)
                    artifacts.append(
                        ParsedArtifact(
                            id=artifact_id,
                            artifact_type=artifact_type,
                            label=label,
                            caption=caption,
                            page=page,
                            bbox=_bbox(raw_block.get("bbox")),
                            caption_bbox=cls._caption_bbox(
                                raw_block, artifact_type
                            ),
                            markdown=markdown,
                            table_data=table_data,
                        )
                    )
                    for alias in (raw_id, label):
                        if alias:
                            artifact_aliases[alias.casefold()] = artifact_id
                    if not caption:
                        warnings.append(f"MinerU artifact {label!r} has no caption")
                elif block_type in {
                    "reference",
                    "artifact_reference",
                    "figure_reference",
                    "table_reference",
                }:
                    reference_candidates.append((raw_block, page))

            raw_references = raw_page.get("references", [])
            if isinstance(raw_references, Sequence) and not isinstance(
                raw_references, (str, bytes)
            ):
                reference_candidates.extend(
                    (item, page) for item in raw_references if isinstance(item, Mapping)
                )

        if isinstance(root_references, Sequence) and not isinstance(
            root_references, (str, bytes)
        ):
            for item in root_references:
                if not isinstance(item, Mapping):
                    continue
                try:
                    page = int(item.get("page", item.get("page_number", 1)))
                except (TypeError, ValueError):
                    page = 1
                reference_candidates.append((item, max(page, 1)))
                page_count = max(page_count, max(page, 1))

        for raw_reference, page in reference_candidates:
            raw_target = str(
                raw_reference.get(
                    "artifact_id",
                    raw_reference.get("target_id", raw_reference.get("target", "")),
                )
            ).lstrip("#")
            artifact_id = artifact_aliases.get(raw_target.casefold())
            if artifact_id is None:
                warnings.append(
                    f"MinerU reference target {raw_target or '<missing>'!r} was not mapped"
                )
                continue
            raw_id = str(
                raw_reference.get("id", raw_reference.get("block_id", ""))
            )
            references.append(
                ParsedReference(
                    id=_unique_id(raw_id, "ref", used_references),
                    artifact_id=artifact_id,
                    text=cls._block_text(raw_reference),
                    page=page,
                    bbox=_bbox(raw_reference.get("bbox")),
                )
            )

        page_count = max(page_count, 1)
        _set_section_page_ends(sections, page_count)
        if not sections:
            warnings.append("MinerU JSON contains no recognized section headings")
        if artifacts and not references:
            warnings.append(
                "MinerU JSON contains no explicit figure/table reference targets; "
                "body references were not inferred"
            )
        return ParsedDocument(
            parser_name=cls.name,
            parser_version=parser_version,
            file_sha256=file_sha256,
            page_count=page_count,
            sections=sections,
            artifacts=artifacts,
            references=references,
            warnings=warnings,
        )


def create_pdf_parser(
    name: str,
    *,
    grobid_client: GrobidClient | None = None,
    mineru_client: MinerUClient | None = None,
) -> PdfParser:
    if name == "pymupdf":
        return PyMuPdfAdapter()
    if name == "grobid":
        return GrobidTeiAdapter(grobid_client)
    if name == "mineru":
        return MinerUJsonAdapter(mineru_client)
    raise ValueError(f"unsupported PDF parser: {name}")
