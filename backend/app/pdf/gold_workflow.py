import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.pdf.adapters import GrobidTeiAdapter, MinerUJsonAdapter, PyMuPdfAdapter
from app.pdf.contracts import ParsedDocument, PersistenceRight
from app.pdf.evaluation import GoldAnnotator, LayoutGold
from app.pdf.service import PdfLayoutService


RightsStatus = Literal["needs_authorized_pdf", "confirmed"]
AnnotationWorkflowStatus = Literal[
    "annotation_not_started",
    "needs_second_annotator",
    "independent_annotation_pending",
    "needs_adjudication",
    "adjudicated",
]
CaseWorkflowStatus = Literal[
    "blocked", "annotation_in_progress", "needs_adjudication", "adjudicated"
]
CandidateStatus = Literal[
    "blocked_missing_authorized_pdf",
    "pending_external_parser",
    "persisted_not_exported",
    "available",
    "unavailable",
    "error",
]


class ConfirmedPdfSource(BaseModel):
    source_description: str = Field(min_length=1)
    source_uri: str | None = None
    rights_basis: Literal[
        "open_full_text", "user_private_copy", "institution_authorized"
    ]
    rights_confirmed_by: str = Field(min_length=1)
    rights_confirmed_at: datetime
    rights_note: str = ""
    file_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    file_size_bytes: int = Field(gt=0)
    page_count: int = Field(ge=1)

    @model_validator(mode="after")
    def reject_local_source_paths(self) -> "ConfirmedPdfSource":
        if self.source_uri and not re.match(r"^https?://", self.source_uri, re.I):
            raise ValueError(
                "source_uri must be an HTTP(S) provenance URL, never a local PDF path"
            )
        return self


class ParserCandidateRecord(BaseModel):
    parser_name: Literal["pymupdf", "grobid", "mineru"]
    status: CandidateStatus
    parser_version: str | None = None
    relative_path: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_candidate_state(self) -> "ParserCandidateRecord":
        if self.status == "available":
            if not self.parser_version or not self.relative_path:
                raise ValueError(
                    "available parser candidate requires version and relative path"
                )
            if Path(self.relative_path).is_absolute() or ".." in Path(
                self.relative_path
            ).parts:
                raise ValueError("candidate path must remain relative to its case")
        elif self.status == "persisted_not_exported":
            if not self.parser_version or self.relative_path is not None or self.error:
                raise ValueError(
                    "persisted_not_exported requires a parser version and no case file"
                )
        elif self.relative_path is not None:
            raise ValueError("unavailable candidate must not claim an output path")
        return self


class LayoutGoldCaseManifest(BaseModel):
    schema_version: Literal["layout-gold-case-v1"] = "layout-gold-case-v1"
    case_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    workflow_status: CaseWorkflowStatus
    rights_status: RightsStatus
    annotation_status: AnnotationWorkflowStatus
    source: ConfirmedPdfSource | None = None
    annotator_a_id: str | None = None
    annotator_b_id: str | None = None
    adjudicator_id: str | None = None
    parser_candidates: list[ParserCandidateRecord]
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    git_exclusions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_state(self) -> "LayoutGoldCaseManifest":
        names = [item.parser_name for item in self.parser_candidates]
        if sorted(names) != ["grobid", "mineru", "pymupdf"]:
            raise ValueError("case manifest requires exactly three parser records")
        if self.rights_status == "needs_authorized_pdf":
            if self.source is not None or self.workflow_status != "blocked":
                raise ValueError("missing-rights case must remain blocked without a source")
            if any(
                item.status != "blocked_missing_authorized_pdf"
                for item in self.parser_candidates
            ):
                raise ValueError("parser candidates require an authorized PDF first")
        elif self.source is None:
            raise ValueError("confirmed rights require recorded PDF source provenance")
        elif self.annotator_a_id is None:
            if (
                self.annotation_status != "annotation_not_started"
                or self.workflow_status != "blocked"
                or self.annotator_b_id is not None
                or self.adjudicator_id is not None
            ):
                raise ValueError(
                    "authorized case without annotator A must remain annotation_not_started"
                )
        identities = [
            item
            for item in (
                self.annotator_a_id,
                self.annotator_b_id,
                self.adjudicator_id,
            )
            if item is not None
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("annotators and adjudicator must be distinct people")
        if self.annotator_a_id is None:
            pass
        elif self.annotation_status == "annotation_not_started":
            raise ValueError("case with annotator A cannot remain annotation_not_started")
        elif self.annotator_b_id is None:
            if self.annotation_status != "needs_second_annotator":
                raise ValueError(
                    "case without annotator B must stay needs_second_annotator"
                )
            if self.workflow_status != "blocked":
                raise ValueError("case without annotator B must remain blocked")
        elif self.annotation_status == "needs_second_annotator":
            raise ValueError(
                "case with annotator B cannot remain needs_second_annotator"
            )
        expected_workflow = {
            "independent_annotation_pending": "annotation_in_progress",
            "needs_adjudication": "needs_adjudication",
            "adjudicated": "adjudicated",
        }.get(self.annotation_status)
        if expected_workflow and self.workflow_status != expected_workflow:
            raise ValueError(
                "workflow_status must agree with the annotation workflow state"
            )
        if self.annotation_status == "adjudicated" and self.adjudicator_id is None:
            raise ValueError("adjudicated case requires an independent adjudicator")
        return self


class AnnotationDifference(BaseModel):
    difference_id: str
    entity_type: Literal["section", "artifact", "reference"]
    entity_id: str
    difference_type: Literal["missing_in_a", "missing_in_b", "field_mismatch"]
    field: str | None = None
    annotator_a_value: Any = None
    annotator_b_value: Any = None


class LayoutGoldDiffReport(BaseModel):
    schema_version: Literal["layout-gold-diff-v1"] = "layout-gold-diff-v1"
    paper_id: str
    file_sha256: str
    annotator_a_id: str
    annotator_b_id: str
    annotator_a_sha256: str
    annotator_b_sha256: str
    status: Literal["needs_adjudication"] = "needs_adjudication"
    difference_count: int = Field(ge=0)
    differences: list[AnnotationDifference]

    @model_validator(mode="after")
    def validate_difference_inventory(self) -> "LayoutGoldDiffReport":
        if self.difference_count != len(self.differences):
            raise ValueError("difference_count must equal the differences list length")
        ids = [item.difference_id for item in self.differences]
        if len(ids) != len(set(ids)):
            raise ValueError("difference identifiers must be unique")
        return self


class AdjudicationDecision(BaseModel):
    difference_id: str
    decision: Literal["annotator_a", "annotator_b", "custom"] | None = None
    resolved_value: Any = None
    rationale: str = ""


class LayoutGoldAdjudicationTemplate(BaseModel):
    schema_version: Literal["layout-gold-adjudication-v1"] = (
        "layout-gold-adjudication-v1"
    )
    paper_id: str
    file_sha256: str
    annotator_a_id: str
    annotator_b_id: str
    annotator_a_sha256: str
    annotator_b_sha256: str
    adjudicator_id: str | None = None
    status: Literal["pending"] = "pending"
    final_gold_status: Literal["not_generated"] = "not_generated"
    signoff_required: Literal[True] = True
    decisions: list[AdjudicationDecision]

    @model_validator(mode="after")
    def validate_decision_inventory(self) -> "LayoutGoldAdjudicationTemplate":
        ids = [item.difference_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("adjudication difference identifiers must be unique")
        return self


class AnnotationImportResult(BaseModel):
    status: Literal["needs_second_annotator", "needs_adjudication"]
    paper_id: str
    file_sha256: str | None
    annotator_a_id: str | None
    annotator_b_id: str | None
    difference_report: LayoutGoldDiffReport | None = None
    adjudication_template: LayoutGoldAdjudicationTemplate | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review_state(self) -> "AnnotationImportResult":
        any_reports_present = (
            self.difference_report is not None
            or self.adjudication_template is not None
        )
        reports_present = (
            self.difference_report is not None
            and self.adjudication_template is not None
        )
        if self.status == "needs_second_annotator":
            if self.annotator_b_id is not None or any_reports_present:
                raise ValueError(
                    "needs_second_annotator cannot contain B or review reports"
                )
        elif self.annotator_b_id is None or not reports_present:
            raise ValueError(
                "needs_adjudication requires annotator B and both review reports"
            )
        return self


@dataclass(frozen=True)
class PreparedLayoutGoldCase:
    manifest: LayoutGoldCaseManifest
    pymupdf_candidate: ParsedDocument
    annotation_a: LayoutGold | None
    annotation_b: LayoutGold | None


@dataclass(frozen=True)
class CandidateImportPlan:
    manifest: LayoutGoldCaseManifest
    candidate: ParsedDocument
    output_path: Path


@dataclass(frozen=True)
class SecondAnnotatorRegistration:
    manifest: LayoutGoldCaseManifest
    annotation_b: LayoutGold


def _canonical_sha256(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _annotation_template(
    manifest: LayoutGoldCaseManifest, annotator_id: str, slot: str
) -> LayoutGold:
    if manifest.source is None:
        raise ValueError("annotation template requires confirmed PDF provenance")
    return LayoutGold(
        evaluation_id=f"{manifest.case_id}-{slot}",
        evaluation_kind="real_paper_evaluation",
        paper_id=manifest.paper_id,
        file_sha256=manifest.source.file_sha256,
        page_count=manifest.source.page_count,
        source_rights_basis=manifest.source.rights_basis,
        annotation_status="draft",
        annotators=[GoldAnnotator(annotator_id=annotator_id, role="annotator")],
        annotation_notes=(
            "Independent annotation file. Do not copy another annotator's decisions "
            "or parser candidate output without marking a reviewed correction."
        ),
        sections=[],
        artifacts=[],
        references=[],
    )


def prepare_layout_gold_case(
    *,
    paper_id: str,
    title: str,
    pdf_path: Path,
    source_description: str,
    source_uri: str | None,
    right: PersistenceRight,
    annotator_a_id: str,
    annotator_b_id: str | None,
) -> PreparedLayoutGoldCase:
    if not annotator_a_id:
        raise ValueError("authorized annotation case requires annotator A")
    if annotator_a_id and annotator_b_id and annotator_a_id == annotator_b_id:
        raise ValueError("annotator A and B must be distinct people")
    preview = PdfLayoutService().preview(paper_id, pdf_path, PyMuPdfAdapter())
    source = ConfirmedPdfSource(
        source_description=source_description,
        source_uri=source_uri,
        rights_basis=right.basis,
        rights_confirmed_by=right.confirmed_by,
        rights_confirmed_at=datetime.now(timezone.utc),
        rights_note=right.note,
        file_sha256=preview.file_sha256,
        file_size_bytes=preview.file_size_bytes,
        page_count=preview.parsed.page_count,
    )
    needs_second = annotator_b_id is None
    manifest = LayoutGoldCaseManifest(
        case_id=f"{paper_id}-layout-gold-v1",
        paper_id=paper_id,
        title=title,
        workflow_status="blocked" if needs_second else "annotation_in_progress",
        rights_status="confirmed",
        annotation_status=(
            "needs_second_annotator"
            if needs_second
            else "independent_annotation_pending"
        ),
        source=source,
        annotator_a_id=annotator_a_id,
        annotator_b_id=annotator_b_id,
        parser_candidates=[
            ParserCandidateRecord(
                parser_name="pymupdf",
                status="available",
                parser_version=preview.parsed.parser_version,
                relative_path="candidates/pymupdf.json",
            ),
            ParserCandidateRecord(
                parser_name="grobid", status="pending_external_parser"
            ),
            ParserCandidateRecord(
                parser_name="mineru", status="pending_external_parser"
            ),
        ],
        blockers=(
            ["A distinct second annotator has not been registered."]
            if needs_second
            else []
        ),
        next_actions=[
            "Run GROBID with head, figure and ref coordinates enabled; import its TEI output.",
            "Run a pinned MinerU version; import middle.json or content_list.json.",
            "Annotators A and B work independently before generating a diff report.",
            "An independent adjudicator resolves every recorded difference.",
        ],
        git_exclusions=[
            "Original PDF",
            "Rendered page images",
            "Extracted figures without redistribution permission",
            "Local absolute file paths",
        ],
    )
    return PreparedLayoutGoldCase(
        manifest=manifest,
        pymupdf_candidate=preview.parsed,
        annotation_a=(
            _annotation_template(manifest, annotator_a_id, "annotator-a")
            if annotator_a_id
            else None
        ),
        annotation_b=(
            _annotation_template(manifest, annotator_b_id, "annotator-b")
            if annotator_b_id
            else None
        ),
    )


def _write_json(path: Path, value: BaseModel, *, exclusive: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(f"refusing to overwrite existing workflow file: {path}")
    path.write_text(
        json.dumps(value.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def write_prepared_case(case: PreparedLayoutGoldCase, output_dir: Path) -> None:
    targets = [
        output_dir / "case_manifest.json",
        output_dir / "candidates" / "pymupdf.json",
    ]
    if case.annotation_a is not None:
        targets.append(output_dir / "annotations" / "annotator_a.json")
    if case.annotation_b is not None:
        targets.append(output_dir / "annotations" / "annotator_b.json")
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite existing workflow files: {existing}"
        )
    _write_json(output_dir / "case_manifest.json", case.manifest, exclusive=True)
    _write_json(
        output_dir / "candidates" / "pymupdf.json",
        case.pymupdf_candidate,
        exclusive=True,
    )
    if case.annotation_a is not None:
        _write_json(
            output_dir / "annotations" / "annotator_a.json",
            case.annotation_a,
            exclusive=True,
        )
    if case.annotation_b is not None:
        _write_json(
            output_dir / "annotations" / "annotator_b.json",
            case.annotation_b,
            exclusive=True,
        )


def register_second_annotator(
    manifest: LayoutGoldCaseManifest, annotator_b_id: str
) -> SecondAnnotatorRegistration:
    if manifest.source is None:
        raise PermissionError("second annotator registration requires authorized PDF provenance")
    if not manifest.annotator_a_id:
        raise ValueError("register annotator A before annotator B")
    if manifest.annotator_b_id is not None:
        raise ValueError("annotator B is already registered")
    if annotator_b_id == manifest.annotator_a_id:
        raise ValueError("annotator A and B must be distinct people")
    updated = manifest.model_copy(
        update={
            "annotator_b_id": annotator_b_id,
            "workflow_status": "annotation_in_progress",
            "annotation_status": "independent_annotation_pending",
            "blockers": [
                item
                for item in manifest.blockers
                if "second annotator" not in item.casefold()
            ],
        }
    )
    updated = LayoutGoldCaseManifest.model_validate(
        updated.model_dump(mode="json")
    )
    return SecondAnnotatorRegistration(
        manifest=updated,
        annotation_b=_annotation_template(updated, annotator_b_id, "annotator-b"),
    )


def write_second_annotator_registration(
    registration: SecondAnnotatorRegistration, manifest_path: Path
) -> None:
    annotation_path = manifest_path.parent / "annotations" / "annotator_b.json"
    if annotation_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing annotator B file: {annotation_path}"
        )
    _write_json(annotation_path, registration.annotation_b, exclusive=True)
    _write_json(manifest_path, registration.manifest, exclusive=False)


def plan_candidate_import(
    manifest_path: Path,
    parser_name: Literal["pymupdf", "grobid", "mineru"],
    input_path: Path,
    parser_version: str | None,
) -> CandidateImportPlan:
    manifest = LayoutGoldCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.source is None:
        raise PermissionError("candidate import requires an authorized PDF source")
    if parser_name == "grobid":
        if not parser_version:
            raise ValueError("GROBID candidate import requires --parser-version")
        candidate = GrobidTeiAdapter.map_tei(
            input_path.read_text(encoding="utf-8"),
            file_sha256=manifest.source.file_sha256,
            parser_version=parser_version,
        )
    elif parser_name == "mineru":
        if not parser_version:
            raise ValueError("MinerU candidate import requires --parser-version")
        candidate = MinerUJsonAdapter.map_json(
            json.loads(input_path.read_text(encoding="utf-8")),
            file_sha256=manifest.source.file_sha256,
            parser_version=parser_version,
        )
    else:
        candidate = ParsedDocument.model_validate_json(
            input_path.read_text(encoding="utf-8")
        )
        if candidate.parser_name != "pymupdf":
            raise ValueError("PyMuPDF candidate JSON has the wrong parser identity")
    if candidate.file_sha256 != manifest.source.file_sha256:
        raise ValueError("candidate file SHA-256 does not match the authorized PDF")
    output_path = manifest_path.parent / "candidates" / f"{parser_name}.json"
    records = []
    for record in manifest.parser_candidates:
        if record.parser_name == parser_name:
            records.append(
                ParserCandidateRecord(
                    parser_name=parser_name,
                    status="available",
                    parser_version=candidate.parser_version,
                    relative_path=f"candidates/{parser_name}.json",
                )
            )
        else:
            records.append(record)
    return CandidateImportPlan(
        manifest=manifest.model_copy(update={"parser_candidates": records}),
        candidate=candidate,
        output_path=output_path,
    )


def write_candidate_import(plan: CandidateImportPlan, manifest_path: Path) -> None:
    _write_json(plan.output_path, plan.candidate, exclusive=True)
    _write_json(manifest_path, plan.manifest, exclusive=False)


def _single_annotator(annotation: LayoutGold, slot: str) -> str:
    if annotation.evaluation_kind != "real_paper_evaluation":
        raise ValueError(f"{slot} must be a real-paper annotation")
    if annotation.annotation_status != "draft":
        raise ValueError(f"{slot} must remain draft until adjudication")
    people = [item.annotator_id for item in annotation.annotators if item.role == "annotator"]
    if len(people) != 1 or len(annotation.annotators) != 1:
        raise ValueError(f"{slot} must contain exactly one independent annotator")
    return people[0]


def _compare_entities(
    entity_type: Literal["section", "artifact", "reference"],
    a_items: list[BaseModel],
    b_items: list[BaseModel],
) -> list[AnnotationDifference]:
    a_by_id = {str(item.model_dump()["id"]): item.model_dump(mode="json") for item in a_items}
    b_by_id = {str(item.model_dump()["id"]): item.model_dump(mode="json") for item in b_items}
    differences: list[AnnotationDifference] = []
    counter = 1
    for entity_id in sorted(set(a_by_id) | set(b_by_id)):
        if entity_id not in a_by_id:
            differences.append(
                AnnotationDifference(
                    difference_id=f"diff-{counter:04d}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    difference_type="missing_in_a",
                    annotator_b_value=b_by_id[entity_id],
                )
            )
            counter += 1
            continue
        if entity_id not in b_by_id:
            differences.append(
                AnnotationDifference(
                    difference_id=f"diff-{counter:04d}",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    difference_type="missing_in_b",
                    annotator_a_value=a_by_id[entity_id],
                )
            )
            counter += 1
            continue
        for field in sorted(set(a_by_id[entity_id]) | set(b_by_id[entity_id])):
            if field == "id":
                continue
            a_value = a_by_id[entity_id].get(field)
            b_value = b_by_id[entity_id].get(field)
            if a_value != b_value:
                differences.append(
                    AnnotationDifference(
                        difference_id=f"diff-{counter:04d}",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        difference_type="field_mismatch",
                        field=field,
                        annotator_a_value=a_value,
                        annotator_b_value=b_value,
                    )
                )
                counter += 1
    return differences


def import_independent_annotations(
    manifest: LayoutGoldCaseManifest,
    annotation_a: LayoutGold,
    annotation_b: LayoutGold | None,
) -> AnnotationImportResult:
    if manifest.source is None:
        raise PermissionError("annotation import requires an authorized PDF source")
    annotator_a_id = _single_annotator(annotation_a, "annotator A")
    if manifest.annotator_a_id and annotator_a_id != manifest.annotator_a_id:
        raise ValueError("annotator A identity does not match the case manifest")
    for field in ("paper_id", "file_sha256", "page_count"):
        expected = (
            manifest.paper_id
            if field == "paper_id"
            else getattr(manifest.source, field)
        )
        if getattr(annotation_a, field) != expected:
            raise ValueError(f"annotator A {field} does not match the case manifest")
    if annotation_a.source_rights_basis != manifest.source.rights_basis:
        raise ValueError("annotator A rights basis does not match the case manifest")
    if annotation_b is None:
        return AnnotationImportResult(
            status="needs_second_annotator",
            paper_id=manifest.paper_id,
            file_sha256=manifest.source.file_sha256,
            annotator_a_id=annotator_a_id,
            annotator_b_id=None,
            warnings=[
                "No annotator B file was supplied; no diff or adjudication file was generated."
            ],
        )
    if manifest.annotator_b_id is None:
        raise ValueError(
            "register annotator B in the case manifest before importing their file"
        )
    annotator_b_id = _single_annotator(annotation_b, "annotator B")
    if annotator_a_id == annotator_b_id:
        raise ValueError("annotator A and B must be distinct people")
    if manifest.annotator_b_id and annotator_b_id != manifest.annotator_b_id:
        raise ValueError("annotator B identity does not match the case manifest")
    for field in ("paper_id", "file_sha256", "page_count", "source_rights_basis"):
        if getattr(annotation_a, field) != getattr(annotation_b, field):
            raise ValueError(f"independent annotations disagree on provenance field {field}")
    differences: list[AnnotationDifference] = []
    differences.extend(
        _compare_entities("section", annotation_a.sections, annotation_b.sections)
    )
    artifact_differences = _compare_entities(
        "artifact", annotation_a.artifacts, annotation_b.artifacts
    )
    reference_differences = _compare_entities(
        "reference", annotation_a.references, annotation_b.references
    )
    offset = len(differences)
    for difference in [*artifact_differences, *reference_differences]:
        offset += 1
        differences.append(
            difference.model_copy(update={"difference_id": f"diff-{offset:04d}"})
        )
    a_sha = _canonical_sha256(annotation_a)
    b_sha = _canonical_sha256(annotation_b)
    diff_report = LayoutGoldDiffReport(
        paper_id=manifest.paper_id,
        file_sha256=manifest.source.file_sha256,
        annotator_a_id=annotator_a_id,
        annotator_b_id=annotator_b_id,
        annotator_a_sha256=a_sha,
        annotator_b_sha256=b_sha,
        difference_count=len(differences),
        differences=differences,
    )
    adjudication = LayoutGoldAdjudicationTemplate(
        paper_id=manifest.paper_id,
        file_sha256=manifest.source.file_sha256,
        annotator_a_id=annotator_a_id,
        annotator_b_id=annotator_b_id,
        annotator_a_sha256=a_sha,
        annotator_b_sha256=b_sha,
        adjudicator_id=manifest.adjudicator_id,
        decisions=[
            AdjudicationDecision(difference_id=item.difference_id)
            for item in differences
        ],
    )
    return AnnotationImportResult(
        status="needs_adjudication",
        paper_id=manifest.paper_id,
        file_sha256=manifest.source.file_sha256,
        annotator_a_id=annotator_a_id,
        annotator_b_id=annotator_b_id,
        difference_report=diff_report,
        adjudication_template=adjudication,
        warnings=[
            "Annotations were compared without modifying either source file.",
            "An adjudicator must explicitly resolve differences and sign off even "
            "when the difference count is zero.",
        ],
    )


def mark_case_needs_adjudication(
    manifest: LayoutGoldCaseManifest, result: AnnotationImportResult
) -> LayoutGoldCaseManifest:
    if result.status != "needs_adjudication":
        return manifest
    updated = manifest.model_copy(
        update={
            "workflow_status": "needs_adjudication",
            "annotation_status": "needs_adjudication",
            "blockers": [
                "An independent adjudicator has not resolved and signed off the comparison."
            ],
        }
    )
    return LayoutGoldCaseManifest.model_validate(updated.model_dump(mode="json"))


def write_annotation_import(
    result: AnnotationImportResult, output_dir: Path
) -> None:
    targets = [output_dir / "annotation_import_status.json"]
    if result.difference_report is not None:
        targets.append(output_dir / "annotation_diff.json")
    if result.adjudication_template is not None:
        targets.append(output_dir / "adjudication.json")
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(
            f"refusing to overwrite existing review files: {existing}"
        )
    _write_json(
        output_dir / "annotation_import_status.json", result, exclusive=True
    )
    if result.difference_report is not None:
        _write_json(
            output_dir / "annotation_diff.json",
            result.difference_report,
            exclusive=True,
        )
    if result.adjudication_template is not None:
        _write_json(
            output_dir / "adjudication.json",
            result.adjudication_template,
            exclusive=True,
        )
