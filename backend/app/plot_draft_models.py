from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnSchema(StrictModel):
    name: str
    inferred_type: Literal["integer", "number", "boolean", "string", "mixed", "null"]
    missing_count: int = Field(ge=0)
    non_missing_count: int = Field(ge=0)


class ValidationIssue(StrictModel):
    code: str
    severity: Literal["warning", "error"]
    field: str | None = None
    message: str


class DatasetUploadReport(StrictModel):
    upload_id: str
    project_id: str
    original_filename: str
    source_format: Literal["csv", "json"]
    data_sha256: str
    byte_size: int = Field(ge=1)
    row_count: int = Field(ge=1)
    columns: list[ColumnSchema] = Field(min_length=1)
    issues: list[ValidationIssue]
    valid: bool
    storage_policy: Literal["ephemeral_process_local"] = "ephemeral_process_local"
    authenticity_statement: Literal["user_uploaded_not_independently_verified"] = (
        "user_uploaded_not_independently_verified"
    )


class PlotGenerationRequest(StrictModel):
    upload_id: str
    plan_revision: int = Field(ge=1)
    artifact_plan_id: str = Field(min_length=1, max_length=191)
    plot_kind: Literal["line", "bar", "scatter"]
    x_column: str = Field(min_length=1, max_length=255)
    y_column: str = Field(min_length=1, max_length=255)
    hue_column: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=300)
    x_label: str = Field(min_length=1, max_length=200)
    y_label: str = Field(min_length=1, max_length=200)
    x_unit: str = Field(min_length=1, max_length=80)
    y_unit: str = Field(min_length=1, max_length=80)
    legend_title: str | None = Field(default=None, max_length=120)
    aggregation: Literal["none", "mean"] = "none"
    error_bar: Literal["none", "standard_deviation"] = "none"
    smoothing: str = Field(default="none", max_length=80)
    y_axis_min: float | None = None
    export_formats: list[Literal["png", "svg", "pdf"]] = Field(
        default_factory=lambda: ["png", "svg"]
    )
    dpi: int = Field(default=300, ge=150, le=600)

    @model_validator(mode="after")
    def validate_plot_options(self) -> "PlotGenerationRequest":
        if len(set(self.export_formats)) != len(self.export_formats):
            raise ValueError("export_formats must be unique")
        if not self.export_formats:
            raise ValueError("at least one export format is required")
        if self.hue_column and not self.legend_title:
            raise ValueError("legend_title is required when hue_column is set")
        if not self.hue_column and self.legend_title:
            raise ValueError("legend_title requires hue_column")
        if self.error_bar != "none" and self.aggregation != "mean":
            raise ValueError("error bars require mean aggregation")
        return self


class PlotQualityCheck(StrictModel):
    check_type: Literal[
        "truncated_axis",
        "unreasonable_smoothing",
        "missing_error_bar",
        "visual_misleading",
        "paper_labels_and_export",
    ]
    status: Literal["pass", "warning", "error"]
    message: str
    remediation: str


class PlotQualityReport(StrictModel):
    checker_version: Literal["plot-integrity-rules-v1"] = "plot-integrity-rules-v1"
    checks: list[PlotQualityCheck]
    has_errors: bool


class PlotLibraryVersions(StrictModel):
    python: str
    matplotlib: str


class PlotExecution(StrictModel):
    status: Literal["not_run", "succeeded", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    library_versions: PlotLibraryVersions | None = None
    generated_files: list[str] = Field(default_factory=list)
    traceability_file: str | None = None
    download_bundle: str | None = None


class PlotDraft(StrictModel):
    draft_id: str
    project_id: str
    upload: DatasetUploadReport
    plan_revision: int
    plan_revision_id: str
    artifact_plan_id: str
    artifact_claim_version_ids: list[str] = Field(min_length=1)
    code_generator_version: Literal["matplotlib-traceable-v1"] = (
        "matplotlib-traceable-v1"
    )
    generated_code: str
    code_sha256: str
    normalized_data_sha256: str
    config_sha256: str
    generation_parameters: PlotGenerationRequest
    quality_report: PlotQualityReport
    execution: PlotExecution
    created_at: str


class PlotExecutionResponse(StrictModel):
    draft: PlotDraft
    message: str
