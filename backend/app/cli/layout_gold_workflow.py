import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.pdf.contracts import PersistenceRight
from app.pdf.evaluation import LayoutGold
from app.pdf.gold_workflow import (
    LayoutGoldCaseManifest,
    import_independent_annotations,
    mark_case_needs_adjudication,
    plan_candidate_import,
    prepare_layout_gold_case,
    register_second_annotator,
    write_annotation_import,
    write_candidate_import,
    write_prepared_case,
    write_second_annotator_registration,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and audit rights-gated, independently annotated PDF layout Gold"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="Hash an authorized PDF and create an isolated annotation case"
    )
    prepare.add_argument("paper_id")
    prepare.add_argument("pdf_path", type=Path)
    prepare.add_argument("--title", required=True)
    prepare.add_argument("--source-description", required=True)
    prepare.add_argument("--source-uri")
    prepare.add_argument(
        "--rights-basis",
        required=True,
        choices=[
            "open_full_text",
            "user_private_copy",
            "institution_authorized",
        ],
    )
    prepare.add_argument("--confirmed-by", required=True)
    prepare.add_argument("--rights-note", default="")
    prepare.add_argument("--annotator-a", required=True)
    prepare.add_argument("--annotator-b")
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--commit", action="store_true")

    register = subparsers.add_parser(
        "register-second-annotator",
        help="Register a distinct annotator B and create only their blank file",
    )
    register.add_argument("--manifest", type=Path, required=True)
    register.add_argument("--annotator-b", required=True)
    register.add_argument("--commit", action="store_true")

    candidate = subparsers.add_parser(
        "import-candidate",
        help="Normalize an external parser result without copying its raw output",
    )
    candidate.add_argument("--manifest", type=Path, required=True)
    candidate.add_argument(
        "--parser", required=True, choices=["pymupdf", "grobid", "mineru"]
    )
    candidate.add_argument("--input", type=Path, required=True)
    candidate.add_argument("--parser-version")
    candidate.add_argument("--commit", action="store_true")

    annotations = subparsers.add_parser(
        "import-annotations",
        help="Validate independent annotations and create unresolved review files",
    )
    annotations.add_argument("--manifest", type=Path, required=True)
    annotations.add_argument("--annotator-a", type=Path, required=True)
    annotations.add_argument("--annotator-b", type=Path)
    annotations.add_argument("--output-dir", type=Path, required=True)
    annotations.add_argument("--commit", action="store_true")
    return parser.parse_args(argv)


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "prepare":
        case = prepare_layout_gold_case(
            paper_id=args.paper_id,
            title=args.title,
            pdf_path=args.pdf_path,
            source_description=args.source_description,
            source_uri=args.source_uri,
            right=PersistenceRight(
                basis=args.rights_basis,
                confirmed_by=args.confirmed_by,
                note=args.rights_note,
            ),
            annotator_a_id=args.annotator_a,
            annotator_b_id=args.annotator_b,
        )
        if args.commit:
            write_prepared_case(case, args.output_dir)
        _print(
            {
                "status": case.manifest.workflow_status,
                "rights_status": case.manifest.rights_status,
                "annotation_status": case.manifest.annotation_status,
                "committed": args.commit,
                "file_sha256": case.manifest.source.file_sha256,
                "page_count": case.manifest.source.page_count,
                "pymupdf_version": case.pymupdf_candidate.parser_version,
                "original_pdf_copied": False,
            }
        )
        return 2 if case.manifest.annotation_status == "needs_second_annotator" else 0

    manifest = LayoutGoldCaseManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    if args.command == "register-second-annotator":
        registration = register_second_annotator(manifest, args.annotator_b)
        if args.commit:
            write_second_annotator_registration(registration, args.manifest)
        _print(
            {
                "status": registration.manifest.annotation_status,
                "committed": args.commit,
                "annotator_b_id": registration.manifest.annotator_b_id,
                "source_annotations_modified": False,
            }
        )
        return 0

    if args.command == "import-candidate":
        plan = plan_candidate_import(
            args.manifest,
            args.parser,
            args.input,
            args.parser_version,
        )
        if args.commit:
            write_candidate_import(plan, args.manifest)
        _print(
            {
                "status": "available",
                "parser": plan.candidate.parser_name,
                "parser_version": plan.candidate.parser_version,
                "committed": args.commit,
                "file_sha256": plan.candidate.file_sha256,
                "raw_output_copied": False,
            }
        )
        return 0

    annotation_a = LayoutGold.model_validate_json(
        args.annotator_a.read_text(encoding="utf-8")
    )
    annotation_b = (
        LayoutGold.model_validate_json(args.annotator_b.read_text(encoding="utf-8"))
        if args.annotator_b
        else None
    )
    result = import_independent_annotations(manifest, annotation_a, annotation_b)
    if args.commit:
        write_annotation_import(result, args.output_dir)
        updated_manifest = mark_case_needs_adjudication(manifest, result)
        if updated_manifest != manifest:
            args.manifest.write_text(
                json.dumps(
                    updated_manifest.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    _print(
        {
            "status": result.status,
            "committed": args.commit,
            "annotator_a_id": result.annotator_a_id,
            "annotator_b_id": result.annotator_b_id,
            "difference_count": (
                result.difference_report.difference_count
                if result.difference_report
                else None
            ),
            "source_annotations_modified": False,
            "final_gold_generated": False,
        }
    )
    return 2 if result.status == "needs_second_annotator" else 0


if __name__ == "__main__":
    raise SystemExit(main())
