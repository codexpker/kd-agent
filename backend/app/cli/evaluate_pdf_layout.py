import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from app.pdf.contracts import ParsedDocument
from app.pdf.evaluation import (
    LayoutGold,
    build_evaluation_report,
    load_synthetic_smoke_case,
    write_evaluation_reports,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate unified ParsedDocument output against layout Gold"
    )
    parser.add_argument(
        "--synthetic-smoke-test",
        action="store_true",
        help="Run all three adapters against bundled synthetic fixtures",
    )
    parser.add_argument("--gold", type=Path, help="Adjudicated layout Gold JSON")
    parser.add_argument(
        "--prediction",
        action="append",
        type=Path,
        default=[],
        help="ParsedDocument JSON; repeat once per parser",
    )
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--markdown-report", type=Path)
    parser.add_argument(
        "--print-gold-schema",
        action="store_true",
        help="Print the machine-readable layout Gold JSON Schema and exit",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_gold_schema:
        print(json.dumps(LayoutGold.model_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if args.json_report is None or args.markdown_report is None:
        raise SystemExit("--json-report and --markdown-report are required")

    if args.synthetic_smoke_test:
        if args.gold is not None or args.prediction:
            raise SystemExit(
                "--synthetic-smoke-test cannot be combined with real Gold/predictions"
            )
        gold, predictions = load_synthetic_smoke_case()
    else:
        if args.gold is None or not args.prediction:
            raise SystemExit("real evaluation requires --gold and --prediction")
        gold = LayoutGold.model_validate_json(args.gold.read_text(encoding="utf-8"))
        predictions = [
            ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))
            for path in args.prediction
        ]

    report = build_evaluation_report(gold, predictions)
    write_evaluation_reports(report, args.json_report, args.markdown_report)
    print(
        json.dumps(
            {
                "status": "ok",
                "report_label": report.report_label,
                "parsers": [item.parser_name for item in report.parser_results],
                "json_report": str(args.json_report),
                "markdown_report": str(args.markdown_report),
                "disclaimer": report.disclaimer,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
