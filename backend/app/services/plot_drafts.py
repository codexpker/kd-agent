import csv
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.experiment_plan_models import ArtifactPlan, ExperimentPlanBundle
from app.plot_draft_models import (
    ColumnSchema,
    DatasetUploadReport,
    PlotDraft,
    PlotExecution,
    PlotExecutionResponse,
    PlotGenerationRequest,
    PlotLibraryVersions,
    PlotQualityCheck,
    PlotQualityReport,
    ValidationIssue,
)
from app.services.experiment_plans import ExperimentPlanService


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100
EXECUTION_TIMEOUT_SECONDS = 20
CODE_GENERATOR_VERSION = "matplotlib-traceable-v1"


class DatasetUploadError(ValueError):
    pass


class PlotDraftNotFoundError(LookupError):
    pass


class PlotExecutionError(RuntimeError):
    pass


@dataclass
class _StoredUpload:
    report: DatasetUploadReport
    normalized_rows: list[dict[str, Any]]
    run_id: str | None
    expires_at: datetime | None


class InMemoryPlotDraftStore:
    """Process-local storage. Uploaded data never enters the repository tree."""

    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="kd-agent-plot-drafts-"
        )
        self.root = Path(self._temporary_directory.name)
        self.uploads: dict[str, _StoredUpload] = {}
        self.drafts: dict[str, PlotDraft] = {}
        self.draft_directories: dict[str, Path] = {}

    def save_upload(
        self,
        report: DatasetUploadReport,
        normalized_rows: list[dict[str, Any]],
        run_id: str | None,
        expires_at: datetime | None,
    ) -> None:
        self.uploads[report.upload_id] = _StoredUpload(
            report, normalized_rows, run_id, expires_at
        )

    def get_upload(self, upload_id: str) -> _StoredUpload:
        try:
            upload = self.uploads[upload_id]
        except KeyError as exc:
            raise DatasetUploadError("uploaded dataset was not found or has expired") from exc
        if upload.expires_at is not None and upload.expires_at <= datetime.now(UTC):
            del self.uploads[upload_id]
            raise DatasetUploadError("uploaded dataset was not found or has expired")
        return upload

    def purge_upload(self, upload_id: str) -> None:
        self.uploads.pop(upload_id, None)

    def purge_run(self, run_id: str) -> None:
        upload_ids = [
            upload_id
            for upload_id, upload in self.uploads.items()
            if upload.run_id == run_id
        ]
        for upload_id in upload_ids:
            del self.uploads[upload_id]
        draft_ids = [
            draft_id
            for draft_id, draft in self.drafts.items()
            if draft.run_id == run_id
        ]
        for draft_id in draft_ids:
            directory = self.draft_directories.pop(draft_id, None)
            self.drafts.pop(draft_id, None)
            if (
                directory is not None
                and directory.is_dir()
                and directory.resolve().is_relative_to(self.root.resolve())
            ):
                shutil.rmtree(directory)

    def save_draft(self, draft: PlotDraft, directory: Path) -> None:
        self.drafts[draft.draft_id] = draft
        self.draft_directories[draft.draft_id] = directory

    def get_draft(self, draft_id: str) -> PlotDraft:
        try:
            return self.drafts[draft_id]
        except KeyError as exc:
            raise PlotDraftNotFoundError(f"plot draft not found: {draft_id}") from exc

    def get_directory(self, draft_id: str) -> Path:
        self.get_draft(draft_id)
        return self.draft_directories[draft_id]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DatasetUploadError("non-finite numeric values are not accepted")
        return "number"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in {"true", "false"}:
            return "boolean"
        try:
            int(stripped)
            return "integer"
        except ValueError:
            try:
                parsed = float(stripped)
            except ValueError:
                return "string"
            if not math.isfinite(parsed):
                raise DatasetUploadError("non-finite numeric values are not accepted")
            return "number"
    return "string"


def _infer_type(values: list[Any]) -> str:
    kinds = {_value_kind(value) for value in values if not _is_missing(value)}
    if not kinds:
        return "null"
    if kinds <= {"integer"}:
        return "integer"
    if kinds <= {"integer", "number"}:
        return "number"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def _normalize_value(value: Any, inferred_type: str) -> Any:
    if _is_missing(value):
        return None
    if inferred_type == "integer":
        return int(value)
    if inferred_type == "number":
        parsed = float(value)
        if not math.isfinite(parsed):
            raise DatasetUploadError("non-finite numeric values are not accepted")
        return parsed
    if inferred_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"
    return str(value)


class DatasetValidator:
    def validate(
        self, project_id: str, filename: str, payload: bytes
    ) -> tuple[DatasetUploadReport, list[dict[str, Any]]]:
        if not payload:
            raise DatasetUploadError("uploaded file is empty")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise DatasetUploadError("uploaded file exceeds the 5 MiB limit")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".json"}:
            raise DatasetUploadError("only .csv and .json uploads are accepted")
        source_format = suffix[1:]
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DatasetUploadError("uploaded data must use UTF-8 encoding") from exc
        rows, columns, source_rows = (
            self._parse_csv(text) if source_format == "csv" else self._parse_json(text)
        )
        if not rows:
            raise DatasetUploadError("uploaded data contains no records")
        if len(rows) > MAX_ROWS:
            raise DatasetUploadError(f"uploaded data exceeds the {MAX_ROWS} row limit")
        if len(columns) > MAX_COLUMNS:
            raise DatasetUploadError(f"uploaded data exceeds the {MAX_COLUMNS} column limit")

        schema: list[ColumnSchema] = []
        issues: list[ValidationIssue] = []
        inferred: dict[str, str] = {}
        for column in columns:
            values = [row.get(column) for row in rows]
            inferred_type = _infer_type(values)
            inferred[column] = inferred_type
            missing = sum(_is_missing(value) for value in values)
            schema.append(
                ColumnSchema(
                    name=column,
                    inferred_type=inferred_type,
                    missing_count=missing,
                    non_missing_count=len(rows) - missing,
                )
            )
            if missing:
                issues.append(
                    ValidationIssue(
                        code="missing_values",
                        severity="warning",
                        field=column,
                        message=f"{missing} missing value(s); no values were imputed",
                    )
                )
            if inferred_type in {"mixed", "null"}:
                issues.append(
                    ValidationIssue(
                        code="ambiguous_column_type",
                        severity="warning",
                        field=column,
                        message=f"column inferred as {inferred_type}",
                    )
                )

        normalized_rows = []
        for source_row, row in zip(source_rows, rows, strict=True):
            normalized = {
                column: _normalize_value(row.get(column), inferred[column])
                for column in columns
            }
            normalized["__source_row__"] = source_row
            normalized_rows.append(normalized)

        upload_id = f"upload-{uuid.uuid4().hex}"
        report = DatasetUploadReport(
            upload_id=upload_id,
            project_id=project_id,
            original_filename=Path(filename).name,
            source_format=source_format,
            data_sha256=_sha256(payload),
            byte_size=len(payload),
            row_count=len(rows),
            columns=schema,
            issues=issues,
            valid=not any(issue.severity == "error" for issue in issues),
        )
        return report, normalized_rows

    @staticmethod
    def _parse_csv(text: str) -> tuple[list[dict[str, Any]], list[str], list[int]]:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if not reader.fieldnames:
            raise DatasetUploadError("CSV header is required")
        columns = [field.strip() for field in reader.fieldnames if field is not None]
        if any(not column for column in columns):
            raise DatasetUploadError("CSV column names must not be empty")
        if len(columns) != len(set(columns)):
            raise DatasetUploadError("CSV column names must be unique")
        rows: list[dict[str, Any]] = []
        source_rows: list[int] = []
        try:
            for line_number, raw in enumerate(reader, start=2):
                if None in raw:
                    raise DatasetUploadError(
                        f"CSV row {line_number} contains more fields than the header"
                    )
                rows.append({column: raw.get(original) for column, original in zip(columns, reader.fieldnames, strict=True)})
                source_rows.append(line_number)
        except csv.Error as exc:
            raise DatasetUploadError(f"invalid CSV: {exc}") from exc
        return rows, columns, source_rows

    @staticmethod
    def _parse_json(text: str) -> tuple[list[dict[str, Any]], list[str], list[int]]:
        def reject_constant(value: str) -> None:
            raise DatasetUploadError(f"non-finite JSON number is not accepted: {value}")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise DatasetUploadError(f"duplicate JSON object key is not accepted: {key}")
                result[key] = value
            return result

        try:
            payload = json.loads(
                text,
                parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            )
        except json.JSONDecodeError as exc:
            raise DatasetUploadError(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, list) or not payload:
            raise DatasetUploadError("JSON must be a non-empty array of objects")
        if not all(isinstance(row, dict) for row in payload):
            raise DatasetUploadError("every JSON array item must be an object")
        columns: list[str] = []
        for row in payload:
            for key in row:
                if not isinstance(key, str) or not key.strip():
                    raise DatasetUploadError("JSON object keys must be non-empty strings")
                if key not in columns:
                    columns.append(key)
        return payload, columns, list(range(1, len(payload) + 1))


class PlotIntegrityChecker:
    def check(
        self, request: PlotGenerationRequest, rows: list[dict[str, Any]]
    ) -> PlotQualityReport:
        y_values = [float(row[request.y_column]) for row in rows]
        checks: list[PlotQualityCheck] = []
        minimum = min(y_values)
        if request.y_axis_min is not None and (
            request.y_axis_min > minimum
            or (request.plot_kind == "bar" and request.y_axis_min != 0)
        ):
            checks.append(
                PlotQualityCheck(
                    check_type="truncated_axis",
                    status="error",
                    message="the requested y-axis minimum would hide data or distort bar lengths",
                    remediation="remove y_axis_min or use zero for a bar chart",
                )
            )
        elif request.y_axis_min is not None and request.y_axis_min != 0:
            checks.append(
                PlotQualityCheck(
                    check_type="truncated_axis",
                    status="warning",
                    message="the y-axis does not start at zero; the exact lower bound is retained in provenance",
                    remediation="confirm the scientific reason and disclose the truncated range in the caption",
                )
            )
        else:
            checks.append(
                PlotQualityCheck(
                    check_type="truncated_axis",
                    status="pass",
                    message="no hidden or non-zero bar baseline was requested",
                    remediation="none",
                )
            )

        if request.smoothing != "none":
            checks.append(
                PlotQualityCheck(
                    check_type="unreasonable_smoothing",
                    status="error",
                    message="smoothing is not executed by this integrity-preserving generator",
                    remediation="use smoothing='none' and show observed or explicitly aggregated values",
                )
            )
        else:
            checks.append(
                PlotQualityCheck(
                    check_type="unreasonable_smoothing",
                    status="pass",
                    message="no smoothing is applied",
                    remediation="none",
                )
            )

        grouping = defaultdict(int)
        for row in rows:
            grouping[(row[request.x_column], row.get(request.hue_column) if request.hue_column else None)] += 1
        has_repeated_groups = any(count > 1 for count in grouping.values())
        if request.aggregation == "mean" and has_repeated_groups and request.error_bar == "none":
            checks.append(
                PlotQualityCheck(
                    check_type="missing_error_bar",
                    status="warning",
                    message="repeated observations are averaged without error bars",
                    remediation="use standard_deviation or explain why variability is omitted",
                )
            )
        else:
            checks.append(
                PlotQualityCheck(
                    check_type="missing_error_bar",
                    status="pass",
                    message="error-bar use is consistent with the selected aggregation",
                    remediation="none",
                )
            )

        if request.plot_kind == "bar" and request.aggregation == "none" and has_repeated_groups:
            checks.append(
                PlotQualityCheck(
                    check_type="visual_misleading",
                    status="error",
                    message="multiple raw bars would overlap for the same x/series group",
                    remediation="select mean aggregation and an error-bar policy",
                )
            )
        elif request.plot_kind == "line" and request.aggregation == "none" and has_repeated_groups:
            checks.append(
                PlotQualityCheck(
                    check_type="visual_misleading",
                    status="warning",
                    message="a line through repeated x values can imply an ordering not present in the data",
                    remediation="aggregate repeated observations or use a scatter plot",
                )
            )
        else:
            checks.append(
                PlotQualityCheck(
                    check_type="visual_misleading",
                    status="pass",
                    message="no overlapping bar or repeated-x line risk was detected",
                    remediation="none",
                )
            )

        checks.append(
            PlotQualityCheck(
                check_type="paper_labels_and_export",
                status="pass",
                message="title, axis labels, explicit units, legend policy and publication formats are recorded",
                remediation="none",
            )
        )
        return PlotQualityReport(
            checks=checks,
            has_errors=any(check.status == "error" for check in checks),
        )


GENERATED_PLOT_CODE = r'''# Generated by KD Agent matplotlib-traceable-v1.
# This file reads only adjacent normalized data and configuration files.
import hashlib
import json
import math
import platform
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
config = json.loads((ROOT / "plot_config.json").read_text(encoding="utf-8"))
normalized_data = (ROOT / "data.normalized.json").read_bytes()
if hashlib.sha256(normalized_data).hexdigest() != config["normalized_data_sha256"]:
    raise RuntimeError("normalized data hash mismatch")
rows = json.loads(normalized_data)

groups = defaultdict(list)
for row in rows:
    series = row.get(config["hue_column"]) if config.get("hue_column") else "all"
    groups[(str(series), row[config["x_column"]])].append(row)

points = []
for (series, x_value), members in groups.items():
    if config["aggregation"] == "mean":
        values = [float(item[config["y_column"]]) for item in members]
        y_value = statistics.fmean(values)
        error = statistics.stdev(values) if config["error_bar"] == "standard_deviation" and len(values) > 1 else 0.0
        points.append({
            "series": series,
            "x": x_value,
            "y": y_value,
            "error": error,
            "source_rows": [item["__source_row__"] for item in members],
            "aggregation_rule": "arithmetic_mean" + ("_plus_minus_sample_standard_deviation" if config["error_bar"] == "standard_deviation" else ""),
        })
    else:
        for item in members:
            points.append({
                "series": series,
                "x": x_value,
                "y": float(item[config["y_column"]]),
                "error": 0.0,
                "source_rows": [item["__source_row__"]],
                "aggregation_rule": "identity_no_aggregation",
            })

series_names = list(dict.fromkeys(point["series"] for point in points))
fig, ax = plt.subplots(figsize=(7.2, 4.5))
if config["plot_kind"] == "bar":
    x_values = list(dict.fromkeys(point["x"] for point in points))
    width = 0.8 / max(len(series_names), 1)
    for series_index, series in enumerate(series_names):
        selected = [point for point in points if point["series"] == series]
        positions = [x_values.index(point["x"]) + (series_index - (len(series_names) - 1) / 2) * width for point in selected]
        ax.bar(positions, [point["y"] for point in selected], width=width, yerr=[point["error"] for point in selected] if config["error_bar"] != "none" else None, capsize=3, label=series if config.get("hue_column") else None)
    ax.set_xticks(range(len(x_values)), [str(value) for value in x_values])
else:
    for series in series_names:
        selected = [point for point in points if point["series"] == series]
        xs = [point["x"] for point in selected]
        ys = [point["y"] for point in selected]
        errors = [point["error"] for point in selected]
        label = series if config.get("hue_column") else None
        if config["plot_kind"] == "scatter":
            ax.scatter(xs, ys, label=label, alpha=0.85)
        else:
            ax.errorbar(xs, ys, yerr=errors if config["error_bar"] != "none" else None, marker="o", capsize=3, label=label)

def axis_label(label, unit):
    return label if unit in {"unitless", "not_applicable"} else f"{label} [{unit}]"

ax.set_title(config["title"])
ax.set_xlabel(axis_label(config["x_label"], config["x_unit"]))
ax.set_ylabel(axis_label(config["y_label"], config["y_unit"]))
if config.get("hue_column"):
    ax.legend(title=config["legend_title"], frameon=False)
if config.get("y_axis_min") is not None:
    ax.set_ylim(bottom=config["y_axis_min"])
ax.grid(axis="y", alpha=0.2)
fig.tight_layout()

generated_files = []
for output_format in config["export_formats"]:
    filename = f"figure.{output_format}"
    save_options = {"dpi": config["dpi"]} if output_format == "png" else {}
    fig.savefig(ROOT / filename, format=output_format, bbox_inches="tight", **save_options)
    generated_files.append(filename)
plt.close(fig)

traceability = {
    "schema_version": "plot-traceability-v1",
    "data_sha256": config["data_sha256"],
    "code_sha256": config["code_sha256"],
    "x_column": config["x_column"],
    "y_column": config["y_column"],
    "hue_column": config.get("hue_column"),
    "points": points,
}
(ROOT / "traceability.json").write_text(json.dumps(traceability, ensure_ascii=False, indent=2), encoding="utf-8")
manifest = {
    "schema_version": "plot-execution-manifest-v1",
    "data_sha256": config["data_sha256"],
    "normalized_data_sha256": hashlib.sha256(normalized_data).hexdigest(),
    "code_sha256": config["code_sha256"],
    "code_generator_version": "matplotlib-traceable-v1",
    "python_version": platform.python_version(),
    "matplotlib_version": matplotlib.__version__,
    "generation_parameters": config["generation_parameters"],
    "generated_files": generated_files,
    "generated_file_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in generated_files},
    "result_policy": "user_uploaded_data_only_no_imputation_no_synthetic_results",
}
(ROOT / "execution_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
'''


class PlotDraftService:
    def __init__(
        self,
        store: InMemoryPlotDraftStore,
        experiment_plan_service: ExperimentPlanService,
    ) -> None:
        self.store = store
        self.experiment_plan_service = experiment_plan_service
        self.validator = DatasetValidator()
        self.checker = PlotIntegrityChecker()

    def upload(
        self,
        project_id: str,
        filename: str,
        payload: bytes,
        *,
        run_id: str | None = None,
        retention_hours: int = 24,
    ) -> DatasetUploadReport:
        report, rows = self.validator.validate(project_id, filename, payload)
        expires_at = (
            None
            if run_id is None
            else datetime.now(UTC) + timedelta(hours=retention_hours)
        )
        self.store.save_upload(report, rows, run_id, expires_at)
        return report

    def generate(self, project_id: str, request: PlotGenerationRequest) -> PlotDraft:
        upload = self.store.get_upload(request.upload_id)
        if upload.report.project_id != project_id:
            raise DatasetUploadError("uploaded dataset belongs to a different project")
        if upload.run_id != request.run_id:
            raise DatasetUploadError(
                "plot request run_id does not match the uploaded dataset binding"
            )
        plan = self.experiment_plan_service.get(project_id, request.plan_revision)
        artifact = self._artifact(plan, request.artifact_plan_id)
        if artifact.artifact_kind != "figure":
            raise DatasetUploadError("the selected ArtifactPlan is a table, not a figure")
        self._validate_key_fields(upload.report, upload.normalized_rows, request)
        quality = self.checker.check(request, upload.normalized_rows)
        code = GENERATED_PLOT_CODE
        code_hash = _sha256(code.encode("utf-8"))
        draft_id = f"plot-{uuid.uuid4().hex}"
        directory = self.store.root / draft_id
        directory.mkdir(parents=False, exist_ok=False)
        parameters = request.model_dump(mode="json")
        normalized_payload = json.dumps(
            upload.normalized_rows, ensure_ascii=False, indent=2
        ).encode("utf-8")
        normalized_hash = _sha256(normalized_payload)
        config = {
            **parameters,
            "data_sha256": upload.report.data_sha256,
            "code_sha256": code_hash,
            "normalized_data_sha256": normalized_hash,
            "generation_parameters": parameters,
        }
        config_payload = json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
        config_hash = _sha256(config_payload)
        (directory / "plot.py").write_text(code, encoding="utf-8", newline="\n")
        (directory / "plot_config.json").write_bytes(config_payload)
        (directory / "data.normalized.json").write_bytes(normalized_payload)
        draft = PlotDraft(
            draft_id=draft_id,
            project_id=project_id,
            run_id=request.run_id,
            upload=upload.report,
            plan_revision=request.plan_revision,
            plan_revision_id=plan.plan_revision_id,
            artifact_plan_id=artifact.artifact_id,
            artifact_claim_version_ids=artifact.supports_claim_version_ids,
            generated_code=code,
            code_sha256=code_hash,
            normalized_data_sha256=normalized_hash,
            config_sha256=config_hash,
            generation_parameters=request,
            quality_report=quality,
            execution=PlotExecution(status="not_run"),
            created_at=_utc_now(),
        )
        self.store.save_draft(draft, directory)
        return draft

    def execute(self, project_id: str, draft_id: str) -> PlotExecutionResponse:
        draft = self.store.get_draft(draft_id)
        if draft.project_id != project_id:
            raise PlotDraftNotFoundError(f"plot draft not found: {draft_id}")
        if draft.execution.status != "not_run":
            raise PlotExecutionError(
                "plot draft execution is immutable; generate a new draft to run again"
            )
        if draft.quality_report.has_errors:
            raise PlotExecutionError("plot integrity errors must be resolved before execution")
        directory = self.store.get_directory(draft_id)
        script = directory / "plot.py"
        if _sha256(script.read_bytes()) != draft.code_sha256:
            raise PlotExecutionError("generated code hash mismatch; execution refused")
        data_path = directory / "data.normalized.json"
        if not data_path.is_file() or _sha256(data_path.read_bytes()) != draft.normalized_data_sha256:
            raise PlotExecutionError("normalized data hash mismatch; execution refused")
        config_path = directory / "plot_config.json"
        if not config_path.is_file() or _sha256(config_path.read_bytes()) != draft.config_sha256:
            raise PlotExecutionError("plot configuration hash mismatch; execution refused")
        started_at = _utc_now()
        env = self._execution_environment(directory)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=directory,
                env=env,
                shell=False,
                capture_output=True,
                text=True,
                timeout=EXECUTION_TIMEOUT_SECONDS,
                creationflags=creationflags,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return self._failed(draft, started_at, "execution_timeout", str(exc))
        except OSError as exc:
            return self._failed(draft, started_at, "executor_unavailable", str(exc))
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "plot process failed")[-4000:]
            return self._failed(draft, started_at, "plot_process_failed", message)

        manifest_path = directory / "execution_manifest.json"
        trace_path = directory / "traceability.json"
        expected = [f"figure.{item}" for item in draft.generation_parameters.export_formats]
        required = [manifest_path, trace_path, *(directory / item for item in expected)]
        if not all(path.is_file() and path.stat().st_size > 0 for path in required):
            return self._failed(
                draft,
                started_at,
                "missing_execution_output",
                "plot process exited successfully but required outputs are missing",
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundle_name = "plot-draft-bundle.zip"
        bundle_path = directory / bundle_name
        bundle_files = [
            "plot.py",
            "plot_config.json",
            "data.normalized.json",
            "traceability.json",
            "execution_manifest.json",
            *expected,
        ]
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in bundle_files:
                archive.write(directory / filename, arcname=filename)
        execution = PlotExecution(
            status="succeeded",
            started_at=started_at,
            finished_at=_utc_now(),
            library_versions=PlotLibraryVersions(
                python=manifest["python_version"],
                matplotlib=manifest["matplotlib_version"],
            ),
            generated_files=expected,
            traceability_file="traceability.json",
            download_bundle=bundle_name,
        )
        updated = draft.model_copy(update={"execution": execution})
        self.store.save_draft(updated, directory)
        return PlotExecutionResponse(
            draft=updated,
            message="plot code executed successfully; files are available for download",
        )

    def file(self, project_id: str, draft_id: str, filename: str) -> Path:
        draft = self.store.get_draft(draft_id)
        if draft.project_id != project_id or draft.execution.status != "succeeded":
            raise PlotDraftNotFoundError(f"plot output not found: {draft_id}")
        allowed = set(draft.execution.generated_files)
        allowed.update({draft.execution.traceability_file, draft.execution.download_bundle})
        allowed.discard(None)
        if filename not in allowed:
            raise PlotDraftNotFoundError(f"plot output not found: {filename}")
        path = self.store.get_directory(draft_id) / filename
        if not path.is_file():
            raise PlotDraftNotFoundError(f"plot output not found: {filename}")
        return path

    @staticmethod
    def _artifact(plan: ExperimentPlanBundle, artifact_id: str) -> ArtifactPlan:
        for artifact in plan.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise DatasetUploadError("artifact_plan_id is not present in the selected plan revision")

    @staticmethod
    def _validate_key_fields(
        report: DatasetUploadReport,
        rows: list[dict[str, Any]],
        request: PlotGenerationRequest,
    ) -> None:
        columns = {column.name: column for column in report.columns}
        key_fields = [request.x_column, request.y_column]
        if request.hue_column:
            key_fields.append(request.hue_column)
        missing = [field for field in key_fields if field not in columns]
        if missing:
            raise DatasetUploadError(f"required plotting column(s) missing: {', '.join(missing)}")
        for field in key_fields:
            if columns[field].missing_count:
                raise DatasetUploadError(
                    f"key field '{field}' contains missing values; no automatic imputation is allowed"
                )
        if columns[request.y_column].inferred_type not in {"integer", "number"}:
            raise DatasetUploadError("y_column must have a consistently numeric type")
        if request.x_column == request.y_column:
            raise DatasetUploadError("x_column and y_column must be different")
        if request.hue_column in {request.x_column, request.y_column}:
            raise DatasetUploadError("hue_column must be distinct from x_column and y_column")
        if not rows:
            raise DatasetUploadError("uploaded data contains no records")

    def _failed(
        self, draft: PlotDraft, started_at: str, code: str, message: str
    ) -> PlotExecutionResponse:
        directory = self.store.get_directory(draft.draft_id)
        for path in directory.glob("figure.*"):
            if path.is_file():
                path.unlink()
        for filename in ("traceability.json", "execution_manifest.json", "plot-draft-bundle.zip"):
            path = directory / filename
            if path.exists():
                path.unlink()
        execution = PlotExecution(
            status="failed",
            started_at=started_at,
            finished_at=_utc_now(),
            error_code=code,
            error_message=message,
        )
        updated = draft.model_copy(update={"execution": execution})
        self.store.save_draft(updated, directory)
        return PlotExecutionResponse(
            draft=updated,
            message="plot execution failed; no image is available",
        )

    @staticmethod
    def _execution_environment(directory: Path) -> dict[str, str]:
        allowed_names = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
        env = {name: value for name, value in os.environ.items() if name in allowed_names}
        env["MPLBACKEND"] = "Agg"
        env["MPLCONFIGDIR"] = str(directory / ".matplotlib")
        env["PYTHONHASHSEED"] = "0"
        return env
