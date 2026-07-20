from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.plot_draft_models import DatasetUploadReport


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunIdentity(StrictModel):
    actor_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    assurance: Literal["self_asserted_local_identity"] = "self_asserted_local_identity"


class RunConfiguration(StrictModel):
    entrypoint: str = Field(min_length=1, max_length=1000)
    code_revision: str = Field(min_length=1, max_length=191)
    dataset_versions: list[str] = Field(min_length=1, max_length=50)
    random_seeds: list[int] = Field(min_length=1, max_length=100)
    command_arguments: list[str] = Field(default_factory=list, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_safe_json_parameters(self) -> "RunConfiguration":
        forbidden_fragments = {"password", "secret", "token", "api_key", "apikey"}

        def walk(value: Any, path: str) -> None:
            if value is None or isinstance(value, (str, int, float, bool)):
                return
            if isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ValueError(f"configuration key must be a string: {path}")
                    normalized = key.lower().replace("-", "_")
                    if any(fragment in normalized for fragment in forbidden_fragments):
                        raise ValueError(
                            f"secret-like configuration key is forbidden: {path}.{key}"
                        )
                    walk(item, f"{path}.{key}")
                return
            raise ValueError(f"configuration contains a non-JSON value at {path}")

        walk(self.parameters, "parameters")
        if len(set(self.dataset_versions)) != len(self.dataset_versions):
            raise ValueError("dataset_versions must be unique")
        if len(set(self.random_seeds)) != len(self.random_seeds):
            raise ValueError("random_seeds must be unique")
        return self


class ReportedExecutionEnvironment(StrictModel):
    source: Literal["user_reported"] = "user_reported"
    operating_system: str = Field(min_length=1, max_length=255)
    python_version: str = Field(min_length=1, max_length=80)
    hardware_summary: str = Field(min_length=1, max_length=1000)
    framework_versions: dict[str, str] = Field(min_length=1, max_length=100)
    container_image_digest: str | None = Field(default=None, max_length=255)


class ExternalVerificationEvidence(StrictModel):
    issuer: str = Field(min_length=1, max_length=255)
    evidence_reference: str = Field(min_length=1, max_length=1000)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending_external_verification"] = (
        "pending_external_verification"
    )


class DataLifecyclePolicy(StrictModel):
    mode: Literal["process_session", "metadata_only"] = "process_session"
    normalized_retention_hours: int = Field(default=24, ge=0, le=72)
    raw_upload_persisted: Literal[False] = False
    mysql_payload_persisted: Literal[False] = False

    @model_validator(mode="after")
    def validate_retention(self) -> "DataLifecyclePolicy":
        if self.mode == "metadata_only" and self.normalized_retention_hours != 0:
            raise ValueError("metadata_only requires normalized_retention_hours=0")
        if self.mode == "process_session" and self.normalized_retention_hours == 0:
            raise ValueError("process_session requires positive normalized_retention_hours")
        return self


class RunDataAsset(StrictModel):
    upload_id: str
    original_filename: str
    source_format: Literal["csv", "json"]
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=1)
    lifecycle_state: Literal[
        "normalized_process_local",
        "metadata_only",
        "deleted",
        "expired",
    ]
    attached_at: datetime
    expires_at: datetime | None
    deleted_at: datetime | None = None


class PlotExecutionBinding(StrictModel):
    draft_id: str
    execution_status: Literal["succeeded", "failed"]
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_files: list[str]
    recorded_at: datetime


class ExperimentRunManifest(StrictModel):
    run_revision_id: str
    run_id: str
    project_id: str
    revision: int = Field(ge=1)
    supersedes_run_revision_id: str | None
    plan_revision_id: str
    plan_revision: int = Field(ge=1)
    experiment_id: str
    identity: RunIdentity
    run_configuration: RunConfiguration
    run_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_environment: ReportedExecutionEnvironment
    result_provenance: Literal["user_declared", "externally_verifiable"]
    external_verification: ExternalVerificationEvidence | None
    lifecycle_policy: DataLifecyclePolicy
    status: Literal[
        "registered",
        "data_attached",
        "plot_succeeded",
        "plot_failed",
        "data_deleted",
        "data_expired",
    ]
    data_asset: RunDataAsset | None
    plot_execution: PlotExecutionBinding | None
    created_at: datetime

    @model_validator(mode="after")
    def validate_provenance_and_state(self) -> "ExperimentRunManifest":
        if self.result_provenance == "user_declared" and self.external_verification:
            raise ValueError("user_declared results cannot carry external verification")
        if self.result_provenance == "externally_verifiable" and not self.external_verification:
            raise ValueError("externally_verifiable results require pending evidence")
        if self.status == "registered" and self.data_asset is not None:
            raise ValueError("registered run cannot already contain a data asset")
        if (
            self.status
            in {
                "data_attached",
                "plot_succeeded",
                "plot_failed",
                "data_deleted",
                "data_expired",
            }
            and self.data_asset is None
        ):
            raise ValueError("run status requires a data asset")
        if self.status in {"plot_succeeded", "plot_failed"} and self.plot_execution is None:
            raise ValueError("plot status requires execution binding")
        return self


class ExperimentRunCreateRequest(StrictModel):
    plan_revision: int = Field(ge=1)
    experiment_id: str = Field(min_length=1, max_length=191)
    identity: RunIdentity
    run_configuration: RunConfiguration
    execution_environment: ReportedExecutionEnvironment
    result_provenance: Literal["user_declared", "externally_verifiable"]
    external_verification: ExternalVerificationEvidence | None = None
    lifecycle_policy: DataLifecyclePolicy = Field(default_factory=DataLifecyclePolicy)

    @model_validator(mode="after")
    def validate_provenance(self) -> "ExperimentRunCreateRequest":
        if self.result_provenance == "user_declared" and self.external_verification:
            raise ValueError("user_declared results cannot carry external verification")
        if self.result_provenance == "externally_verifiable" and not self.external_verification:
            raise ValueError("externally_verifiable results require pending evidence")
        return self


class ExperimentRunHistory(StrictModel):
    project_id: str
    run_id: str
    revisions: list[ExperimentRunManifest]


class ExperimentRunDataDeleteRequest(StrictModel):
    actor_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,63}$")


class ExperimentRunDataAttachResponse(StrictModel):
    run: ExperimentRunManifest
    upload: DatasetUploadReport
