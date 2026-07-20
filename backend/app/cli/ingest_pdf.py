import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.pdf.adapters import ExternalParserUnavailableError, create_pdf_parser
from app.pdf.contracts import PersistenceRight
from app.pdf.persistence import PersistenceDeniedError, require_persistence_right
from app.pdf.service import PdfLayoutService


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse PDF layout facts; persistence requires explicit rights and --commit"
    )
    parser.add_argument("paper_id", help="Existing authoritative MySQL paper ID")
    parser.add_argument("pdf_path", type=Path, help="Local PDF path; the file is never stored")
    parser.add_argument(
        "--parser", choices=["pymupdf", "grobid", "mineru"], default="pymupdf"
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist structured facts to MySQL; omitted means local dry-run preview",
    )
    parser.add_argument(
        "--rights-basis",
        choices=["open_full_text", "user_private_copy", "institution_authorized"],
    )
    parser.add_argument("--confirmed-by")
    parser.add_argument("--rights-note", default="")
    parser.add_argument(
        "--paper-source-key",
        help="Optional existing PaperSource key associated with this PDF",
    )
    return parser.parse_args(argv)


def _right_from_args(args: argparse.Namespace) -> PersistenceRight | None:
    if args.rights_basis is None and args.confirmed_by is None:
        return None
    if args.rights_basis is None or not args.confirmed_by:
        raise PersistenceDeniedError(
            "--rights-basis and --confirmed-by must be supplied together"
        )
    return PersistenceRight(
        basis=args.rights_basis,
        confirmed_by=args.confirmed_by,
        note=args.rights_note,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    service = PdfLayoutService()
    try:
        preview = service.preview(
            args.paper_id, args.pdf_path, create_pdf_parser(args.parser)
        )
    except ExternalParserUnavailableError as exc:
        print(
            json.dumps(
                {
                    "paper_id": args.paper_id,
                    "committed": False,
                    "overall_status": "unavailable",
                    "parser": args.parser,
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 4
    persistence = None
    right = None
    if args.commit:
        try:
            right = require_persistence_right(_right_from_args(args))
        except PersistenceDeniedError as exc:
            print(
                json.dumps(
                    {
                        "paper_id": args.paper_id,
                        "committed": False,
                        "overall_status": "blocked",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 3
        from app.storage.runtime import get_pdf_repository

        persistence = service.persist(
            preview,
            right,
            get_pdf_repository(get_settings().mysql_url),
            args.paper_source_key,
        )

    print(
        json.dumps(
            {
                "paper_id": preview.paper_id,
                "committed": persistence is not None,
                "database_action": persistence.action if persistence else "planned",
                "parse_run_id": persistence.parse_run_id if persistence else None,
                "overall_status": "ok" if persistence else "dry_run",
                "rights_basis": right.basis if right else None,
                "file_sha256": preview.file_sha256,
                "file_size_bytes": preview.file_size_bytes,
                "structure": preview.structure.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
