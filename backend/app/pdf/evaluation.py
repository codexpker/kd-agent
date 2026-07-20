import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from difflib import SequenceMatcher
from importlib.resources import files
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.pdf.adapters import GrobidTeiAdapter, MinerUJsonAdapter
from app.pdf.contracts import (
    ParsedArtifact,
    ParsedDocument,
    ParsedReference,
    ParsedSection,
)


EvaluationKind = Literal["real_paper_evaluation", "synthetic_smoke_test"]
GoldRightsBasis = Literal[
    "open_full_text",
    "user_private_copy",
    "institution_authorized",
    "synthetic_generated",
]


class GoldAnnotator(BaseModel):
    annotator_id: str = Field(min_length=1)
    role: Literal["annotator", "adjudicator"]


class LayoutGold(BaseModel):
    schema_version: Literal["layout-gold-v1"] = "layout-gold-v1"
    evaluation_id: str = Field(min_length=1)
    evaluation_kind: EvaluationKind
    paper_id: str = Field(min_length=1)
    file_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    page_count: int = Field(ge=1)
    source_rights_basis: GoldRightsBasis
    annotation_status: Literal[
        "draft", "double_annotated", "adjudicated", "synthetic_generated"
    ]
    annotators: list[GoldAnnotator] = Field(default_factory=list)
    annotation_notes: str = ""
    sections: list[ParsedSection]
    artifacts: list[ParsedArtifact]
    references: list[ParsedReference]

    @model_validator(mode="after")
    def validate_gold_provenance(self) -> "LayoutGold":
        synthetic = self.evaluation_kind == "synthetic_smoke_test"
        if synthetic != (self.source_rights_basis == "synthetic_generated"):
            raise ValueError(
                "synthetic_smoke_test and synthetic_generated must be used together"
            )
        if synthetic != (self.annotation_status == "synthetic_generated"):
            raise ValueError(
                "synthetic_smoke_test must be marked synthetic_generated, never adjudicated"
            )
        if synthetic and self.annotators:
            raise ValueError("synthetic smoke fixtures must not claim human annotators")
        if not synthetic and self.annotation_status in {
            "double_annotated",
            "adjudicated",
        }:
            annotators = {
                item.annotator_id
                for item in self.annotators
                if item.role == "annotator"
            }
            if len(annotators) < 2:
                raise ValueError(
                    "double-annotated real Gold requires two distinct annotators"
                )
            if self.annotation_status == "adjudicated":
                adjudicators = {
                    item.annotator_id
                    for item in self.annotators
                    if item.role == "adjudicator"
                }
                if not adjudicators:
                    raise ValueError("adjudicated real Gold requires an adjudicator")
                if annotators & adjudicators:
                    raise ValueError(
                        "the adjudicator must be distinct from both annotators"
                    )
        section_ids = [item.id for item in self.sections]
        artifact_id_list = [item.id for item in self.artifacts]
        reference_ids = [item.id for item in self.references]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("duplicate Gold section id")
        if len(artifact_id_list) != len(set(artifact_id_list)):
            raise ValueError("duplicate Gold artifact id")
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("duplicate Gold reference id")
        artifact_ids = {item.id for item in self.artifacts}
        unknown = {item.artifact_id for item in self.references} - artifact_ids
        if unknown:
            raise ValueError(f"Gold references unknown artifact ids: {sorted(unknown)}")
        pages = [
            *(item.page_end for item in self.sections),
            *(item.page for item in self.artifacts),
            *(item.page for item in self.references),
        ]
        if any(page > self.page_count for page in pages):
            raise ValueError("Gold layout page exceeds page_count")
        return self


class F1Metric(BaseModel):
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    true_positive: int = Field(ge=0)
    predicted: int = Field(ge=0)
    gold: int = Field(ge=0)


class AccuracyMetric(BaseModel):
    value: float = Field(ge=0, le=1)
    correct: int = Field(ge=0)
    support: int = Field(ge=0)


class LayoutMetrics(BaseModel):
    section_title_f1: F1Metric
    section_hierarchy_accuracy: AccuracyMetric
    figure_detection_f1: F1Metric
    table_detection_f1: F1Metric
    caption_text_similarity: AccuracyMetric
    page_number_accuracy: AccuracyMetric
    body_artifact_reference_f1: F1Metric
    table_cell_f1: F1Metric


class ParserEvaluation(BaseModel):
    parser_name: str
    parser_version: str
    metrics: LayoutMetrics
    parser_warnings: list[str] = Field(default_factory=list)


class LayoutEvaluationReport(BaseModel):
    schema_version: Literal["layout-evaluation-report-v1"] = (
        "layout-evaluation-report-v1"
    )
    evaluation_kind: EvaluationKind
    report_label: Literal["real_paper_evaluation", "synthetic_smoke_test"]
    gold_evaluation_id: str
    gold_annotation_status: str
    gold_source_rights_basis: GoldRightsBasis
    paper_id: str
    file_sha256: str
    disclaimer: str
    parser_results: list[ParserEvaluation]


T = TypeVar("T")
K = TypeVar("K")
MappingLike = dict[str, str]


def _normalize(value: str) -> str:
    canonical = re.sub(r"\bfig(?:ure)?\.?", "figure", value.casefold())
    return re.sub(r"[^\w]+", " ", canonical).strip()


def _pair_by_key(
    gold: Sequence[T], predicted: Sequence[T], key: Callable[[T], K]
) -> list[tuple[T, T]]:
    buckets: dict[K, list[T]] = defaultdict(list)
    for item in predicted:
        buckets[key(item)].append(item)
    pairs: list[tuple[T, T]] = []
    for item in gold:
        candidates = buckets.get(key(item))
        if candidates:
            pairs.append((item, candidates.pop(0)))
    return pairs


def _f1(true_positive: int, predicted: int, gold: int) -> F1Metric:
    precision = true_positive / predicted if predicted else (1.0 if not gold else 0.0)
    recall = true_positive / gold if gold else (1.0 if not predicted else 0.0)
    score = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return F1Metric(
        precision=precision,
        recall=recall,
        f1=score,
        true_positive=true_positive,
        predicted=predicted,
        gold=gold,
    )


def _accuracy(values: Iterable[bool]) -> AccuracyMetric:
    materialized = list(values)
    correct = sum(materialized)
    support = len(materialized)
    return AccuracyMetric(
        value=correct / support if support else 1.0,
        correct=correct,
        support=support,
    )


def _mean_similarity(pairs: Sequence[tuple[str, str]]) -> AccuracyMetric:
    scores = [
        SequenceMatcher(None, _normalize(gold), _normalize(predicted)).ratio()
        for gold, predicted in pairs
    ]
    value = sum(scores) / len(scores) if scores else 1.0
    return AccuracyMetric(
        value=value,
        correct=sum(score == 1.0 for score in scores),
        support=len(scores),
    )


def _counter_f1(gold: Counter[object], predicted: Counter[object]) -> F1Metric:
    true_positive = sum((gold & predicted).values())
    return _f1(true_positive, sum(predicted.values()), sum(gold.values()))


def evaluate_parsed_document(
    gold: LayoutGold, parsed: ParsedDocument
) -> ParserEvaluation:
    if parsed.file_sha256.casefold() != gold.file_sha256.casefold():
        raise ValueError("prediction and Gold file_sha256 do not identify the same input")

    section_pairs = _pair_by_key(
        gold.sections, parsed.sections, lambda item: _normalize(item.title)
    )
    artifact_pairs = _pair_by_key(
        gold.artifacts,
        parsed.artifacts,
        lambda item: (item.artifact_type, _normalize(item.label)),
    )
    predicted_to_gold_artifact = {
        predicted_item.id: gold_item.id for gold_item, predicted_item in artifact_pairs
    }
    remapped_predicted_references = [
        item.model_copy(
            update={
                "artifact_id": predicted_to_gold_artifact.get(
                    item.artifact_id, f"unmatched:{item.artifact_id}"
                )
            }
        )
        for item in parsed.references
    ]
    reference_pairs = _pair_by_key(
        gold.references,
        remapped_predicted_references,
        lambda item: (item.artifact_id, item.page),
    )

    page_checks: list[bool] = []
    for gold_item, predicted_item in section_pairs:
        page_checks.extend(
            [
                gold_item.page_start == predicted_item.page_start,
                gold_item.page_end == predicted_item.page_end,
            ]
        )
    page_checks.extend(
        gold_item.page == predicted_item.page
        for gold_item, predicted_item in artifact_pairs
    )
    page_checks.extend(
        gold_item.page == predicted_item.page
        for gold_item, predicted_item in reference_pairs
    )

    def table_cells(
        artifacts: Sequence[ParsedArtifact], id_map: MappingLike
    ) -> Counter[object]:
        cells: Counter[object] = Counter()
        for artifact in artifacts:
            if artifact.artifact_type != "table" or artifact.table_data is None:
                continue
            mapped_id = id_map.get(artifact.id, f"unmatched:{artifact.id}")
            for row_index, row in enumerate(artifact.table_data):
                for column_index, cell in enumerate(row):
                    cells[(mapped_id, row_index, column_index, _normalize(cell))] += 1
        return cells

    gold_tables = table_cells(
        gold.artifacts, {item.id: item.id for item in gold.artifacts}
    )
    predicted_tables = table_cells(parsed.artifacts, predicted_to_gold_artifact)
    figures_gold = [item for item in gold.artifacts if item.artifact_type == "figure"]
    figures_predicted = [
        item for item in parsed.artifacts if item.artifact_type == "figure"
    ]
    tables_gold = [item for item in gold.artifacts if item.artifact_type == "table"]
    tables_predicted = [
        item for item in parsed.artifacts if item.artifact_type == "table"
    ]
    matched_figures = sum(
        gold_item.artifact_type == "figure" for gold_item, _ in artifact_pairs
    )
    matched_tables = sum(
        gold_item.artifact_type == "table" for gold_item, _ in artifact_pairs
    )

    metrics = LayoutMetrics(
        section_title_f1=_f1(
            len(section_pairs), len(parsed.sections), len(gold.sections)
        ),
        section_hierarchy_accuracy=_accuracy(
            gold_item.level == predicted_item.level
            for gold_item, predicted_item in section_pairs
        ),
        figure_detection_f1=_f1(
            matched_figures, len(figures_predicted), len(figures_gold)
        ),
        table_detection_f1=_f1(
            matched_tables, len(tables_predicted), len(tables_gold)
        ),
        caption_text_similarity=_mean_similarity(
            [
                (gold_item.caption, predicted_item.caption)
                for gold_item, predicted_item in artifact_pairs
            ]
        ),
        page_number_accuracy=_accuracy(page_checks),
        body_artifact_reference_f1=_f1(
            len(reference_pairs), len(parsed.references), len(gold.references)
        ),
        table_cell_f1=_counter_f1(gold_tables, predicted_tables),
    )
    return ParserEvaluation(
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        metrics=metrics,
        parser_warnings=parsed.warnings,
    )


def build_evaluation_report(
    gold: LayoutGold, predictions: Sequence[ParsedDocument]
) -> LayoutEvaluationReport:
    if not predictions:
        raise ValueError("at least one parser prediction is required")
    synthetic = gold.evaluation_kind == "synthetic_smoke_test"
    if not synthetic and gold.annotation_status != "adjudicated":
        raise ValueError("real-paper evaluation requires adjudicated layout Gold")
    if not synthetic and gold.file_sha256 == "0" * 64:
        raise ValueError("real-paper evaluation cannot use the template SHA-256 placeholder")
    if not synthetic and any(
        "synthetic" in prediction.parser_version.casefold()
        for prediction in predictions
    ):
        raise ValueError("real-paper evaluation cannot use a synthetic parser fixture")
    disclaimer = (
        "Synthetic smoke test only. These values verify evaluator wiring and are not "
        "real-paper parser performance."
        if synthetic
        else "Real-paper evaluation; interpret results with the documented Gold and sampling scope."
    )
    return LayoutEvaluationReport(
        evaluation_kind=gold.evaluation_kind,
        report_label=gold.evaluation_kind,
        gold_evaluation_id=gold.evaluation_id,
        gold_annotation_status=gold.annotation_status,
        gold_source_rights_basis=gold.source_rights_basis,
        paper_id=gold.paper_id,
        file_sha256=gold.file_sha256,
        disclaimer=disclaimer,
        parser_results=[
            evaluate_parsed_document(gold, prediction) for prediction in predictions
        ],
    )


def render_markdown_report(report: LayoutEvaluationReport) -> str:
    synthetic = report.report_label == "synthetic_smoke_test"
    title = (
        "PDF Layout Evaluation — SYNTHETIC SMOKE TEST"
        if synthetic
        else "PDF Layout Evaluation — Real Paper"
    )
    rows = []
    for result in report.parser_results:
        metrics = result.metrics
        rows.append(
            "| {name} | {section:.3f} | {hierarchy:.3f} | {figure:.3f} | "
            "{table:.3f} | {caption:.3f} | {page:.3f} | {reference:.3f} | "
            "{cells:.3f} |".format(
                name=f"{result.parser_name} {result.parser_version}",
                section=metrics.section_title_f1.f1,
                hierarchy=metrics.section_hierarchy_accuracy.value,
                figure=metrics.figure_detection_f1.f1,
                table=metrics.table_detection_f1.f1,
                caption=metrics.caption_text_similarity.value,
                page=metrics.page_number_accuracy.value,
                reference=metrics.body_artifact_reference_f1.f1,
                cells=metrics.table_cell_f1.f1,
            )
        )
    return "\n".join(
        [
            f"# {title}",
            "",
            f"> **{report.report_label}** — {report.disclaimer}",
            "",
            f"Gold: `{report.gold_evaluation_id}`  ",
            f"Gold status: `{report.gold_annotation_status}`  ",
            f"Rights basis: `{report.gold_source_rights_basis}`  ",
            f"Paper: `{report.paper_id}`  ",
            f"File SHA-256: `{report.file_sha256}`",
            "",
            "| Parser | Section title F1 | Hierarchy accuracy | Figure F1 | "
            "Table F1 | Caption similarity | Page accuracy | Body reference F1 | "
            "Table cell F1 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "Exact normalized titles/labels identify sections and artifacts. Caption "
            "similarity uses normalized character-sequence similarity; page accuracy "
            "covers matched section ranges, artifacts and body references; table cells "
            "are compared by matched table, row, column and normalized content. Body "
            "references are matched by their mapped artifact and page because parsers "
            "return different surrounding-text spans.",
            "",
        ]
    )


def write_evaluation_reports(
    report: LayoutEvaluationReport, json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")


def load_synthetic_smoke_case() -> tuple[LayoutGold, list[ParsedDocument]]:
    fixture_root = files("app.data").joinpath("evaluation")
    gold = LayoutGold.model_validate_json(
        fixture_root.joinpath("synthetic_layout_gold.json").read_text(encoding="utf-8")
    )
    pymupdf = ParsedDocument.model_validate_json(
        fixture_root.joinpath("synthetic_pymupdf_parsed.json").read_text(
            encoding="utf-8"
        )
    )
    grobid = GrobidTeiAdapter.map_tei(
        fixture_root.joinpath("synthetic_grobid.tei.xml").read_text(encoding="utf-8"),
        file_sha256=gold.file_sha256,
        parser_version="synthetic-fixture-v1",
    )
    mineru_payload = json.loads(
        fixture_root.joinpath("synthetic_mineru.json").read_text(encoding="utf-8")
    )
    mineru = MinerUJsonAdapter.map_json(
        mineru_payload,
        file_sha256=gold.file_sha256,
        parser_version="synthetic-fixture-v1",
    )
    return gold, [pymupdf, grobid, mineru]
