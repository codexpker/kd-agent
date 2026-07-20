import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.cli import layout_gold_workflow as workflow_cli
from app.pdf.contracts import ParsedSection, PersistenceRight
from app.pdf.evaluation import LayoutGold
from app.pdf.gold_workflow import (
    AnnotationImportResult,
    LayoutGoldAdjudicationTemplate,
    LayoutGoldDiffReport,
    LayoutGoldCaseManifest,
    import_independent_annotations,
    plan_candidate_import,
    prepare_layout_gold_case,
    register_second_annotator,
    write_candidate_import,
    write_prepared_case,
    write_second_annotator_registration,
)


PAPER_ID = "anomaly-transformer-2022"
TITLE = "Anomaly Transformer: Time Series Anomaly Detection with Association Discrepancy"


@pytest.fixture
def authorized_pdf(tmp_path: Path) -> Path:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "authorized-private-fixture.pdf"
    document = fitz.open()
    first_page = document.new_page()
    first_page.insert_text((72, 72), "1 Introduction")
    first_page.insert_text((72, 110), "Figure 1: Fixture overview")
    first_page.insert_text((72, 150), "As shown in Figure 1, this is a test.")
    second_page = document.new_page()
    second_page.insert_text((72, 72), "2 Method")
    document.save(path)
    document.close()
    return path


def _prepare(
    authorized_pdf: Path,
    *,
    annotator_a: str | None = "reviewer-a",
    annotator_b: str | None = None,
):
    return prepare_layout_gold_case(
        paper_id=PAPER_ID,
        title=TITLE,
        pdf_path=authorized_pdf,
        source_description="User-provided private test fixture",
        source_uri=None,
        right=PersistenceRight(
            basis="user_private_copy",
            confirmed_by="fixture-owner",
            note="Synthetic PDF created inside this test only.",
        ),
        annotator_a_id=annotator_a,
        annotator_b_id=annotator_b,
    )


def test_pending_anomaly_manifest_records_confirmed_private_copy_without_fake_annotator() -> None:
    fixture_root = files("app.data").joinpath("evaluation")
    manifest = LayoutGoldCaseManifest.model_validate_json(
        fixture_root.joinpath(
            "anomaly_transformer_layout_gold_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest.workflow_status == "blocked"
    assert manifest.rights_status == "confirmed"
    assert manifest.annotation_status == "annotation_not_started"
    assert manifest.source is not None
    assert manifest.source.rights_basis == "user_private_copy"
    assert manifest.source.file_sha256 == "ff8d3bb627fce9914eb8a9e78c4139e4852771dbee801da2c766dea028a17053"
    assert manifest.annotator_a_id is None
    assert manifest.parser_candidates[0].status == "persisted_not_exported"
    assert all(item.relative_path is None for item in manifest.parser_candidates)
    assert not any("frozen" in item.casefold() for item in manifest.blockers)
    assert any("Human layout annotation is postponed" in item for item in manifest.blockers)


def test_case_manifest_rejects_contradictory_annotation_state(
    authorized_pdf: Path,
) -> None:
    case = _prepare(
        authorized_pdf, annotator_a="reviewer-a", annotator_b="reviewer-b"
    )
    payload = case.manifest.model_dump(mode="json")
    payload["annotation_status"] = "needs_second_annotator"
    payload["workflow_status"] = "blocked"

    with pytest.raises(ValidationError, match="cannot remain"):
        LayoutGoldCaseManifest.model_validate(payload)


def test_review_schemas_reject_inconsistent_inventory() -> None:
    with pytest.raises(ValidationError, match="difference_count"):
        LayoutGoldDiffReport(
            paper_id=PAPER_ID,
            file_sha256="a" * 64,
            annotator_a_id="reviewer-a",
            annotator_b_id="reviewer-b",
            annotator_a_sha256="b" * 64,
            annotator_b_sha256="c" * 64,
            difference_count=1,
            differences=[],
        )

    with pytest.raises(ValidationError, match="requires annotator B"):
        AnnotationImportResult(
            status="needs_adjudication",
            paper_id=PAPER_ID,
            file_sha256="a" * 64,
            annotator_a_id="reviewer-a",
            annotator_b_id=None,
        )

    with pytest.raises(ValidationError, match="literal_error"):
        LayoutGoldAdjudicationTemplate(
            paper_id=PAPER_ID,
            file_sha256="a" * 64,
            annotator_a_id="reviewer-a",
            annotator_b_id="reviewer-b",
            annotator_a_sha256="b" * 64,
            annotator_b_sha256="c" * 64,
            signoff_required=False,
            decisions=[],
        )


def test_human_annotation_template_is_blank_and_single_reviewer() -> None:
    fixture_root = files("app.data").joinpath("evaluation")
    template = LayoutGold.model_validate_json(
        fixture_root.joinpath("layout_gold_template.json").read_text(encoding="utf-8")
    )

    assert template.annotation_status == "draft"
    assert len(template.annotators) == 1
    assert template.sections == []
    assert template.artifacts == []
    assert template.references == []


def test_prepare_hashes_authorized_pdf_but_stops_without_second_annotator(
    authorized_pdf: Path, tmp_path: Path
) -> None:
    case = _prepare(authorized_pdf)
    output_dir = tmp_path / "case"

    assert case.manifest.rights_status == "confirmed"
    assert case.manifest.workflow_status == "blocked"
    assert case.manifest.annotation_status == "needs_second_annotator"
    assert case.manifest.source is not None
    assert case.manifest.source.file_sha256 == hashlib.sha256(
        authorized_pdf.read_bytes()
    ).hexdigest()
    assert case.manifest.source.page_count == 2
    assert case.annotation_a is not None
    assert case.annotation_b is None

    write_prepared_case(case, output_dir)

    assert (output_dir / "case_manifest.json").is_file()
    assert (output_dir / "candidates" / "pymupdf.json").is_file()
    assert (output_dir / "annotations" / "annotator_a.json").is_file()
    assert not (output_dir / "annotations" / "annotator_b.json").exists()
    assert list(output_dir.rglob("*.pdf")) == []
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.json")
    )
    assert str(authorized_pdf) not in serialized


def test_prepare_cli_defaults_to_dry_run_and_does_not_copy_pdf(
    authorized_pdf: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "dry-run-case"

    exit_code = workflow_cli.main(
        [
            "prepare",
            PAPER_ID,
            str(authorized_pdf),
            "--title",
            TITLE,
            "--source-description",
            "User-provided private test fixture",
            "--rights-basis",
            "user_private_copy",
            "--confirmed-by",
            "fixture-owner",
            "--annotator-a",
            "reviewer-a",
            "--output-dir",
            str(output_dir),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["committed"] is False
    assert payload["annotation_status"] == "needs_second_annotator"
    assert payload["original_pdf_copied"] is False
    assert not output_dir.exists()


def test_source_uri_rejects_local_file_paths(authorized_pdf: Path) -> None:
    with pytest.raises(ValidationError, match="never a local PDF path"):
        prepare_layout_gold_case(
            paper_id=PAPER_ID,
            title=TITLE,
            pdf_path=authorized_pdf,
            source_description="Invalid local source record",
            source_uri=str(authorized_pdf),
            right=PersistenceRight(
                basis="user_private_copy", confirmed_by="fixture-owner"
            ),
            annotator_a_id="reviewer-a",
            annotator_b_id=None,
        )


def test_authorized_case_requires_annotator_a(authorized_pdf: Path) -> None:
    with pytest.raises(ValueError, match="requires annotator A"):
        prepare_layout_gold_case(
            paper_id=PAPER_ID,
            title=TITLE,
            pdf_path=authorized_pdf,
            source_description="Authorized test fixture",
            source_uri=None,
            right=PersistenceRight(
                basis="user_private_copy", confirmed_by="fixture-owner"
            ),
            annotator_a_id="",
            annotator_b_id=None,
        )


def test_second_annotator_registration_is_explicit_and_non_overwriting(
    authorized_pdf: Path, tmp_path: Path
) -> None:
    case = _prepare(authorized_pdf)
    case_dir = tmp_path / "case"
    write_prepared_case(case, case_dir)
    manifest_path = case_dir / "case_manifest.json"

    registration = register_second_annotator(case.manifest, "reviewer-b")
    assert registration.manifest.annotation_status == "independent_annotation_pending"
    assert registration.manifest.workflow_status == "annotation_in_progress"
    assert registration.annotation_b.annotators[0].annotator_id == "reviewer-b"

    write_second_annotator_registration(registration, manifest_path)
    reloaded = LayoutGoldCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert reloaded.annotator_b_id == "reviewer-b"
    assert (case_dir / "annotations" / "annotator_b.json").is_file()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_second_annotator_registration(registration, manifest_path)


def test_candidate_import_normalizes_tei_and_never_copies_raw_output(
    authorized_pdf: Path, tmp_path: Path
) -> None:
    case = _prepare(authorized_pdf)
    case_dir = tmp_path / "case"
    write_prepared_case(case, case_dir)
    manifest_path = case_dir / "case_manifest.json"
    raw_dir = tmp_path / "external-output"
    raw_dir.mkdir()
    raw_tei = raw_dir / "grobid.tei.xml"
    raw_tei.write_text(
        """
        <TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
          <div xml:id="sec-1"><head coords="1,10,20,100,12">Introduction</head></div>
        </body></text></TEI>
        """,
        encoding="utf-8",
    )

    plan = plan_candidate_import(
        manifest_path, "grobid", raw_tei, "0.8.1-test"
    )
    write_candidate_import(plan, manifest_path)

    normalized = json.loads(plan.output_path.read_text(encoding="utf-8"))
    reloaded = LayoutGoldCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert normalized["parser_name"] == "grobid"
    assert normalized["file_sha256"] == case.manifest.source.file_sha256  # type: ignore[union-attr]
    assert next(
        item for item in reloaded.parser_candidates if item.parser_name == "grobid"
    ).status == "available"
    assert not (case_dir / raw_tei.name).exists()


def test_candidate_import_normalizes_mineru_without_copying_raw_output(
    authorized_pdf: Path, tmp_path: Path
) -> None:
    case = _prepare(authorized_pdf)
    case_dir = tmp_path / "case"
    write_prepared_case(case, case_dir)
    manifest_path = case_dir / "case_manifest.json"
    raw_dir = tmp_path / "external-output"
    raw_dir.mkdir()
    raw_json = raw_dir / "mineru-content-list.json"
    raw_json.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Introduction",
                    "text_level": 1,
                    "bbox": [72, 60, 180, 78],
                    "page_idx": 0,
                }
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_candidate_import(
        manifest_path, "mineru", raw_json, "2.1.0-test"
    )
    write_candidate_import(plan, manifest_path)

    normalized = json.loads(plan.output_path.read_text(encoding="utf-8"))
    reloaded = LayoutGoldCaseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert normalized["parser_name"] == "mineru"
    assert normalized["file_sha256"] == case.manifest.source.file_sha256  # type: ignore[union-attr]
    assert next(
        item for item in reloaded.parser_candidates if item.parser_name == "mineru"
    ).status == "available"
    assert not (case_dir / raw_json.name).exists()


def test_annotation_import_without_b_stops_before_diff(
    authorized_pdf: Path,
) -> None:
    case = _prepare(authorized_pdf)
    assert case.annotation_a is not None

    result = import_independent_annotations(
        case.manifest, case.annotation_a, None
    )

    assert result.status == "needs_second_annotator"
    assert result.difference_report is None
    assert result.adjudication_template is None


def test_import_cli_missing_b_writes_only_needs_second_status(
    authorized_pdf: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _prepare(authorized_pdf)
    case_dir = tmp_path / "case"
    review_dir = case_dir / "review"
    write_prepared_case(case, case_dir)

    exit_code = workflow_cli.main(
        [
            "import-annotations",
            "--manifest",
            str(case_dir / "case_manifest.json"),
            "--annotator-a",
            str(case_dir / "annotations" / "annotator_a.json"),
            "--output-dir",
            str(review_dir),
            "--commit",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "needs_second_annotator"
    assert (review_dir / "annotation_import_status.json").is_file()
    assert not (review_dir / "annotation_diff.json").exists()
    assert not (review_dir / "adjudication.json").exists()


def test_independent_disagreement_creates_unresolved_adjudication_without_mutation(
    authorized_pdf: Path,
) -> None:
    case = _prepare(
        authorized_pdf, annotator_a="reviewer-a", annotator_b="reviewer-b"
    )
    assert case.annotation_a is not None
    assert case.annotation_b is not None
    section_a = ParsedSection(
        id="sec-introduction",
        title="Introduction",
        level=1,
        page_start=1,
        page_end=1,
        heading_bbox=[72, 60, 180, 78],
    )
    section_b = section_a.model_copy(update={"level": 2})
    annotation_a = case.annotation_a.model_copy(update={"sections": [section_a]})
    annotation_b = case.annotation_b.model_copy(update={"sections": [section_b]})
    before_a = annotation_a.model_dump_json()
    before_b = annotation_b.model_dump_json()

    result = import_independent_annotations(
        case.manifest, annotation_a, annotation_b
    )

    assert result.status == "needs_adjudication"
    assert result.difference_report is not None
    assert result.difference_report.difference_count == 1
    assert result.difference_report.differences[0].field == "level"
    assert result.adjudication_template is not None
    assert result.adjudication_template.status == "pending"
    assert result.adjudication_template.final_gold_status == "not_generated"
    assert result.adjudication_template.decisions[0].decision is None
    assert annotation_a.model_dump_json() == before_a
    assert annotation_b.model_dump_json() == before_b


def test_import_cli_advances_only_to_needs_adjudication(
    authorized_pdf: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _prepare(
        authorized_pdf, annotator_a="reviewer-a", annotator_b="reviewer-b"
    )
    case_dir = tmp_path / "case"
    review_dir = case_dir / "review"
    write_prepared_case(case, case_dir)
    annotation_a_path = case_dir / "annotations" / "annotator_a.json"
    annotation_b_path = case_dir / "annotations" / "annotator_b.json"
    before_a = hashlib.sha256(annotation_a_path.read_bytes()).hexdigest()
    before_b = hashlib.sha256(annotation_b_path.read_bytes()).hexdigest()

    exit_code = workflow_cli.main(
        [
            "import-annotations",
            "--manifest",
            str(case_dir / "case_manifest.json"),
            "--annotator-a",
            str(annotation_a_path),
            "--annotator-b",
            str(annotation_b_path),
            "--output-dir",
            str(review_dir),
            "--commit",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    manifest = LayoutGoldCaseManifest.model_validate_json(
        (case_dir / "case_manifest.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert payload["status"] == "needs_adjudication"
    assert payload["final_gold_generated"] is False
    assert manifest.workflow_status == "needs_adjudication"
    assert manifest.annotation_status == "needs_adjudication"
    assert (review_dir / "annotation_diff.json").is_file()
    adjudication = json.loads(
        (review_dir / "adjudication.json").read_text(encoding="utf-8")
    )
    assert adjudication["status"] == "pending"
    assert adjudication["final_gold_status"] == "not_generated"
    assert hashlib.sha256(annotation_a_path.read_bytes()).hexdigest() == before_a
    assert hashlib.sha256(annotation_b_path.read_bytes()).hexdigest() == before_b


def test_independent_annotations_must_share_exact_pdf_provenance(
    authorized_pdf: Path,
) -> None:
    case = _prepare(
        authorized_pdf, annotator_a="reviewer-a", annotator_b="reviewer-b"
    )
    assert case.annotation_a is not None
    assert case.annotation_b is not None
    annotation_b = case.annotation_b.model_copy(update={"file_sha256": "f" * 64})

    with pytest.raises(ValueError, match="provenance field file_sha256"):
        import_independent_annotations(
            case.manifest, case.annotation_a, annotation_b
        )
