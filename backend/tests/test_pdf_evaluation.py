import inspect
import json
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.cli import evaluate_pdf_layout as evaluate_cli
from app.cli import ingest_pdf as ingest_pdf_cli
from app.pdf import adapters
from app.pdf.adapters import (
    ExternalParserUnavailableError,
    GrobidTeiAdapter,
    MinerUJsonAdapter,
    ParserOutputError,
)
from app.pdf.contracts import ParsedDocument
from app.pdf.evaluation import (
    LayoutGold,
    build_evaluation_report,
    evaluate_parsed_document,
    load_synthetic_smoke_case,
    render_markdown_report,
)


SYNTHETIC_SHA256 = (
    "ae8b58e8c16440d3e9a5f4cbc5e35e6038f566283519c04ed22894975cb61f7a"
)


def test_all_three_synthetic_paths_return_the_unified_contract() -> None:
    gold, predictions = load_synthetic_smoke_case()

    assert gold.evaluation_kind == "synthetic_smoke_test"
    assert [item.parser_name for item in predictions] == [
        "pymupdf",
        "grobid",
        "mineru",
    ]
    assert all(isinstance(item, ParsedDocument) for item in predictions)
    assert all(len(item.sections) == 2 for item in predictions)
    assert all(len(item.artifacts) == 2 for item in predictions)
    assert all(len(item.references) == 2 for item in predictions)

    report = build_evaluation_report(gold, predictions)
    assert report.report_label == "synthetic_smoke_test"
    for result in report.parser_results:
        assert result.metrics.section_title_f1.f1 == 1
        assert result.metrics.section_hierarchy_accuracy.value == 1
        assert result.metrics.figure_detection_f1.f1 == 1
        assert result.metrics.table_detection_f1.f1 == 1
        assert result.metrics.caption_text_similarity.value == 1
        assert result.metrics.page_number_accuracy.value == 1
        assert result.metrics.body_artifact_reference_f1.f1 == 1
        assert result.metrics.table_cell_f1.f1 == 1


def test_grobid_tei_maps_nested_sections_coordinates_tables_and_references() -> None:
    tei = """
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <text><body><pb n="1"/><div xml:id="outer">
        <head coords="1,10,20,100,15">Method</head>
        <div xml:id="inner"><head coords="1,15,50,90,12">Training</head></div>
        <figure xml:id="tab-x" type="table" coords="1,20,100,200,80">
          <head>Table 2</head><figDesc coords="1,20,185,200,15">Results</figDesc>
          <table><row><cell>A</cell><cell>B</cell></row></table>
        </figure>
        <p><ref type="table" target="#tab-x" coords="1,20,230,80,12">Table 2</ref></p>
      </div></body></text>
    </TEI>
    """

    parsed = GrobidTeiAdapter.map_tei(
        tei,
        file_sha256=SYNTHETIC_SHA256,
        parser_version="0.8.1-test",
    )

    assert parsed.parser_name == "grobid"
    assert [(item.title, item.level) for item in parsed.sections] == [
        ("Method", 1),
        ("Training", 2),
    ]
    assert parsed.sections[0].heading_bbox == [10, 20, 110, 35]
    assert parsed.artifacts[0].artifact_type == "table"
    assert parsed.artifacts[0].table_data == [["A", "B"]]
    assert parsed.artifacts[0].markdown is not None
    assert parsed.references[0].artifact_id == parsed.artifacts[0].id


def test_grobid_invalid_tei_is_an_explicit_mapping_error() -> None:
    with pytest.raises(ParserOutputError, match="invalid GROBID TEI XML"):
        GrobidTeiAdapter.map_tei(
            "<TEI>",
            file_sha256=SYNTHETIC_SHA256,
            parser_version="test",
        )


def test_mineru_maps_pdf_info_variant_and_explicit_reference() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "block_id": "heading-1",
                        "type": "section_title",
                        "content": "Results",
                        "heading_level": 2,
                        "bbox": [10, 20, 100, 40],
                    },
                    {
                        "block_id": "figure-x",
                        "type": "image",
                        "label": "Figure 3",
                        "blocks": [
                            {
                                "type": "image_caption",
                                "text": "A result plot",
                            }
                        ],
                        "bbox": [10, 50, 200, 180],
                    },
                ],
                "references": [
                    {
                        "id": "reference-x",
                        "target": "figure-x",
                        "text": "See Figure 3.",
                        "bbox": [10, 190, 120, 205],
                    }
                ],
            }
        ]
    }

    parsed = MinerUJsonAdapter.map_json(
        payload,
        file_sha256=SYNTHETIC_SHA256,
        parser_version="2.1-test",
    )

    assert parsed.parser_name == "mineru"
    assert parsed.sections[0].title == "Results"
    assert parsed.sections[0].level == 2
    assert parsed.artifacts[0].caption == "A result plot"
    assert parsed.references[0].artifact_id == parsed.artifacts[0].id


def test_mineru_rejects_payload_without_pages() -> None:
    with pytest.raises(ParserOutputError, match="content-list array"):
        MinerUJsonAdapter.map_json(
            {}, file_sha256=SYNTHETIC_SHA256, parser_version="test"
        )


def test_mineru_maps_official_content_list_fields_and_html_table_cells() -> None:
    content_list = [
        {
            "type": "text",
            "text": "Evaluation",
            "text_level": 2,
            "bbox": [10, 20, 200, 40],
            "page_idx": 0,
        },
        {
            "type": "image",
            "image_caption": ["Fig. 4. Error analysis"],
            "bbox": [10, 50, 300, 250],
            "page_idx": 1,
        },
        {
            "type": "table",
            "table_caption": ["Table 3 Ablation results"],
            "table_body": (
                "<table><tr><th>Model</th><th>F1</th></tr>"
                "<tr><td>Demo</td><td>0.9</td></tr></table>"
            ),
            "bbox": [10, 280, 300, 480],
            "page_idx": 1,
        },
    ]

    parsed = MinerUJsonAdapter.map_json(
        content_list,
        file_sha256=SYNTHETIC_SHA256,
        parser_version="official-content-list-test",
    )

    assert parsed.page_count == 2
    assert [(item.title, item.level) for item in parsed.sections] == [
        ("Evaluation", 2)
    ]
    assert parsed.artifacts[0].label == "Fig. 4"
    assert parsed.artifacts[0].caption == "Error analysis"
    assert parsed.artifacts[1].label == "Table 3"
    assert parsed.artifacts[1].caption == "Ablation results"
    assert parsed.artifacts[1].table_data == [
        ["Model", "F1"],
        ["Demo", "0.9"],
    ]
    assert any("were not inferred" in item for item in parsed.warnings)


def test_mineru_middle_json_reads_nested_line_spans() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "title",
                        "bbox": [10, 20, 200, 40],
                        "lines": [
                            {
                                "spans": [
                                    {"type": "text", "content": "Discussion"}
                                ]
                            }
                        ],
                    },
                    {
                        "type": "image",
                        "bbox": [10, 50, 300, 250],
                        "blocks": [
                            {
                                "type": "image_caption",
                                "bbox": [10, 255, 300, 275],
                                "lines": [
                                    {
                                        "spans": [
                                            {
                                                "type": "text",
                                                "content": "Figure 5: Failure modes",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
    }

    parsed = MinerUJsonAdapter.map_json(
        payload,
        file_sha256=SYNTHETIC_SHA256,
        parser_version="official-middle-test",
    )

    assert parsed.sections[0].title == "Discussion"
    assert parsed.artifacts[0].label == "Figure 5"
    assert parsed.artifacts[0].caption == "Failure modes"
    assert parsed.artifacts[0].caption_bbox == [10, 255, 300, 275]


def test_grobid_uses_facsimile_for_page_count_but_not_as_a_fake_locator() -> None:
    tei = """
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <facsimile><surface n="1"/><surface n="2"/></facsimile>
      <text><body><div xml:id="missing-page"><head>Unlocated</head></div></body></text>
    </TEI>
    """

    parsed = GrobidTeiAdapter.map_tei(
        tei,
        file_sha256=SYNTHETIC_SHA256,
        parser_version="test",
    )

    assert parsed.page_count == 2
    assert parsed.sections == []
    assert any("no page coordinates" in item for item in parsed.warnings)


@pytest.mark.parametrize("adapter_type", [GrobidTeiAdapter, MinerUJsonAdapter])
def test_unconfigured_external_parser_never_substitutes_a_result(
    adapter_type: type[GrobidTeiAdapter] | type[MinerUJsonAdapter], tmp_path: Path
) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"not needed by the unavailable adapter")

    with pytest.raises(
        ExternalParserUnavailableError, match="no synthetic result was substituted"
    ):
        adapter_type().parse(source)


def test_external_parser_cli_returns_explicit_unavailable_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"not a real PDF; availability is checked before decoding")

    exit_code = ingest_pdf_cli.main(
        ["synthetic-paper", str(source), "--parser", "grobid"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 4
    assert payload["overall_status"] == "unavailable"
    assert payload["committed"] is False
    assert "no synthetic result" in payload["error"]


def test_parser_adapters_have_no_storage_dependency() -> None:
    source = inspect.getsource(adapters)
    assert "app.storage" not in source
    assert "PdfRepository" not in source
    assert "session" not in source.casefold()


def test_gold_template_validates_but_cannot_claim_a_real_score_before_adjudication() -> None:
    fixture_root = files("app.data").joinpath("evaluation")
    template = LayoutGold.model_validate_json(
        fixture_root.joinpath("layout_gold_template.json").read_text(encoding="utf-8")
    )
    _, predictions = load_synthetic_smoke_case()
    prediction = predictions[0].model_copy(update={"file_sha256": template.file_sha256})

    with pytest.raises(ValueError, match="requires adjudicated layout Gold"):
        build_evaluation_report(template, [prediction])


def test_synthetic_gold_cannot_be_relabelled_as_real_or_adjudicated() -> None:
    gold, _ = load_synthetic_smoke_case()
    payload = gold.model_dump(mode="json")
    payload["evaluation_kind"] = "real_paper_evaluation"

    with pytest.raises(ValidationError, match="synthetic_smoke_test"):
        LayoutGold.model_validate(payload)

    payload = gold.model_dump(mode="json")
    payload["annotation_status"] = "adjudicated"
    with pytest.raises(ValidationError, match="synthetic_generated"):
        LayoutGold.model_validate(payload)


def test_real_adjudication_requires_a_distinct_adjudicator() -> None:
    fixture_root = files("app.data").joinpath("evaluation")
    payload = json.loads(
        fixture_root.joinpath("layout_gold_template.json").read_text(encoding="utf-8")
    )
    payload["annotators"].append(
        {"annotator_id": "annotator-b", "role": "annotator"}
    )
    payload["annotation_status"] = "adjudicated"

    with pytest.raises(ValidationError, match="requires an adjudicator"):
        LayoutGold.model_validate(payload)

    payload["annotators"].append(
        {
            "annotator_id": payload["annotators"][0]["annotator_id"],
            "role": "adjudicator",
        }
    )
    with pytest.raises(ValidationError, match="must be distinct"):
        LayoutGold.model_validate(payload)

def test_each_metric_detects_a_corresponding_synthetic_error() -> None:
    gold, predictions = load_synthetic_smoke_case()
    prediction = predictions[0].model_copy(deep=True)
    prediction.sections[0].title = "Wrong heading"
    prediction.sections[1].level = 2
    prediction.artifacts[0].caption = "Unrelated caption"
    prediction.artifacts[0].page = 2
    prediction.references.pop()
    prediction.artifacts[1].table_data[1][1] = "11"  # type: ignore[index]

    metrics = evaluate_parsed_document(gold, prediction).metrics
    assert metrics.section_title_f1.f1 < 1
    assert metrics.section_hierarchy_accuracy.value < 1
    assert metrics.caption_text_similarity.value < 1
    assert metrics.page_number_accuracy.value < 1
    assert metrics.body_artifact_reference_f1.f1 < 1
    assert metrics.table_cell_f1.f1 < 1

    without_figure = prediction.model_copy(deep=True)
    without_figure.artifacts = [
        item for item in without_figure.artifacts if item.artifact_type != "figure"
    ]
    without_figure.references = [
        item
        for item in without_figure.references
        if item.artifact_id in {artifact.id for artifact in without_figure.artifacts}
    ]
    assert evaluate_parsed_document(gold, without_figure).metrics.figure_detection_f1.f1 < 1

    without_table = predictions[0].model_copy(deep=True)
    without_table.artifacts = [
        item for item in without_table.artifacts if item.artifact_type != "table"
    ]
    without_table.references = [
        item
        for item in without_table.references
        if item.artifact_id in {artifact.id for artifact in without_table.artifacts}
    ]
    assert evaluate_parsed_document(gold, without_table).metrics.table_detection_f1.f1 < 1


def test_synthetic_cli_writes_machine_and_team_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_report = tmp_path / "layout-report.json"
    markdown_report = tmp_path / "layout-report.md"

    exit_code = evaluate_cli.main(
        [
            "--synthetic-smoke-test",
            "--json-report",
            str(json_report),
            "--markdown-report",
            str(markdown_report),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    machine_report = json.loads(json_report.read_text(encoding="utf-8"))
    team_report = markdown_report.read_text(encoding="utf-8")
    assert exit_code == 0
    assert output["report_label"] == "synthetic_smoke_test"
    assert machine_report["report_label"] == "synthetic_smoke_test"
    assert machine_report["gold_annotation_status"] == "synthetic_generated"
    assert machine_report["gold_source_rights_basis"] == "synthetic_generated"
    assert len(machine_report["parser_results"]) == 3
    assert "SYNTHETIC SMOKE TEST" in team_report
    assert "not real-paper parser performance" in team_report


def test_gold_json_schema_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluate_cli.main(["--print-gold-schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "LayoutGold"
    assert "evaluation_kind" in schema["properties"]


def test_markdown_real_and_synthetic_labels_cannot_be_confused() -> None:
    gold, predictions = load_synthetic_smoke_case()
    report = build_evaluation_report(gold, predictions)

    rendered = render_markdown_report(report)

    assert "synthetic_smoke_test" in rendered
    assert "SYNTHETIC SMOKE TEST" in rendered
