import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from collections.abc import Callable
from typing import Protocol

from app.experiment_run_models import (
    ExperimentRunCreateRequest,
    ExperimentRunHistory,
    ExperimentRunManifest,
    PlotExecutionBinding,
    RunDataAsset,
)
from app.plot_draft_models import DatasetUploadReport, PlotDraft
from app.services.experiment_plans import ExperimentPlanService


class ExperimentRunNotFoundError(LookupError):
    pass


class ExperimentRunVersionConflictError(RuntimeError):
    pass


class ExperimentRunIdentityError(PermissionError):
    pass


class ExperimentRunStore(Protocol):
    def latest(self, project_id: str, run_id: str) -> ExperimentRunManifest | None: ...

    def list_revisions(
        self, project_id: str, run_id: str
    ) -> list[ExperimentRunManifest]: ...

    def save(self, manifest: ExperimentRunManifest, expected_revision: int) -> None: ...


class InMemoryExperimentRunStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], list[ExperimentRunManifest]] = {}

    def latest(self, project_id: str, run_id: str) -> ExperimentRunManifest | None:
        revisions = self._runs.get((project_id, run_id), [])
        return revisions[-1].model_copy(deep=True) if revisions else None

    def list_revisions(
        self, project_id: str, run_id: str
    ) -> list[ExperimentRunManifest]:
        return [
            item.model_copy(deep=True)
            for item in self._runs.get((project_id, run_id), [])
        ]

    def save(self, manifest: ExperimentRunManifest, expected_revision: int) -> None:
        key = (manifest.project_id, manifest.run_id)
        revisions = self._runs.setdefault(key, [])
        actual = revisions[-1].revision if revisions else 0
        if actual != expected_revision:
            raise ExperimentRunVersionConflictError(
                f"Expected run revision {expected_revision}, got {actual}"
            )
        revisions.append(manifest.model_copy(deep=True))


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExperimentRunService:
    def __init__(
        self,
        store: ExperimentRunStore,
        experiment_plan_service: ExperimentPlanService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.experiment_plan_service = experiment_plan_service
        self.clock = clock or (lambda: datetime.now(UTC))

    def create(
        self, project_id: str, request: ExperimentRunCreateRequest
    ) -> ExperimentRunManifest:
        plan = self.experiment_plan_service.get(project_id, request.plan_revision)
        if not any(
            experiment.experiment_id == request.experiment_id
            for experiment in plan.experiments
        ):
            raise ValueError(
                "experiment_id is not present in the selected plan revision"
            )
        now = self.clock()
        run_id = f"run-{uuid.uuid4().hex}"
        manifest = ExperimentRunManifest(
            run_revision_id=f"{run_id}:r1",
            run_id=run_id,
            project_id=project_id,
            revision=1,
            supersedes_run_revision_id=None,
            plan_revision_id=plan.plan_revision_id,
            plan_revision=plan.revision,
            experiment_id=request.experiment_id,
            identity=request.identity,
            run_configuration=request.run_configuration,
            run_configuration_sha256=canonical_sha256(
                request.run_configuration.model_dump(mode="json")
            ),
            execution_environment=request.execution_environment,
            result_provenance=request.result_provenance,
            external_verification=request.external_verification,
            lifecycle_policy=request.lifecycle_policy,
            status="registered",
            data_asset=None,
            plot_execution=None,
            created_at=now,
        )
        self.store.save(manifest, expected_revision=0)
        return manifest

    def get(
        self, project_id: str, run_id: str, *, expire_due: bool = True
    ) -> ExperimentRunManifest:
        manifest = self.store.latest(project_id, run_id)
        if manifest is None:
            raise ExperimentRunNotFoundError(f"experiment run not found: {run_id}")
        if expire_due:
            manifest = self._expire_if_due(manifest)
        return manifest

    def history(self, project_id: str, run_id: str) -> ExperimentRunHistory:
        self.get(project_id, run_id)
        return ExperimentRunHistory(
            project_id=project_id,
            run_id=run_id,
            revisions=self.store.list_revisions(project_id, run_id),
        )

    def assert_actor(
        self, project_id: str, run_id: str, actor_id: str
    ) -> ExperimentRunManifest:
        manifest = self.get(project_id, run_id)
        if manifest.identity.actor_id != actor_id:
            raise ExperimentRunIdentityError(
                "actor_id does not match the run's self-asserted identity"
            )
        return manifest

    def attach_data(
        self,
        project_id: str,
        run_id: str,
        actor_id: str,
        upload: DatasetUploadReport,
    ) -> ExperimentRunManifest:
        current = self.assert_actor(project_id, run_id, actor_id)
        if current.data_asset is not None:
            raise ExperimentRunVersionConflictError(
                "run already has a data asset; create a new run for different data"
            )
        if upload.project_id != project_id:
            raise ValueError("uploaded dataset belongs to a different project")
        now = self.clock()
        policy = current.lifecycle_policy
        state = (
            "metadata_only"
            if policy.mode == "metadata_only"
            else "normalized_process_local"
        )
        expires_at = (
            None
            if policy.mode == "metadata_only"
            else now + timedelta(hours=policy.normalized_retention_hours)
        )
        schema_payload = {
            "source_format": upload.source_format,
            "row_count": upload.row_count,
            "columns": [column.model_dump(mode="json") for column in upload.columns],
            "issues": [issue.model_dump(mode="json") for issue in upload.issues],
        }
        data_asset = RunDataAsset(
            upload_id=upload.upload_id,
            original_filename=upload.original_filename,
            source_format=upload.source_format,
            data_sha256=upload.data_sha256,
            schema_sha256=canonical_sha256(schema_payload),
            row_count=upload.row_count,
            lifecycle_state=state,
            attached_at=now,
            expires_at=expires_at,
        )
        return self._append(
            current,
            status="data_attached",
            data_asset=data_asset,
        )

    def assert_plot_binding(
        self,
        project_id: str,
        run_id: str,
        actor_id: str,
        plan_revision: int,
        artifact_plan_id: str,
        upload_id: str,
    ) -> ExperimentRunManifest:
        current = self.assert_actor(project_id, run_id, actor_id)
        if current.plan_revision != plan_revision:
            raise ValueError("plot plan_revision does not match the run manifest")
        if current.data_asset is None or current.data_asset.upload_id != upload_id:
            raise ValueError("plot upload_id does not match the run data asset")
        if current.data_asset.lifecycle_state != "normalized_process_local":
            raise ValueError("run data is not available for plotting")
        plan = self.experiment_plan_service.get(project_id, plan_revision)
        artifact = next(
            (
                item
                for item in plan.artifacts
                if item.artifact_id == artifact_plan_id
            ),
            None,
        )
        if artifact is None:
            raise ValueError("artifact_plan_id is not present in the run plan")
        if current.experiment_id not in artifact.source_experiment_ids:
            raise ValueError(
                "ArtifactPlan is not linked to the run's ExperimentPlan"
            )
        return current

    def record_plot(
        self,
        project_id: str,
        run_id: str,
        draft: PlotDraft,
    ) -> ExperimentRunManifest:
        current = self.get(project_id, run_id)
        if current.data_asset is None:
            raise ExperimentRunVersionConflictError("run has no attached data")
        if draft.run_id != run_id:
            raise ValueError("plot draft is not bound to this run")
        if draft.execution.status not in {"succeeded", "failed"}:
            raise ValueError("plot execution must be terminal before recording")
        binding = PlotExecutionBinding(
            draft_id=draft.draft_id,
            execution_status=draft.execution.status,
            code_sha256=draft.code_sha256,
            normalized_data_sha256=draft.normalized_data_sha256,
            config_sha256=draft.config_sha256,
            generated_files=draft.execution.generated_files,
            recorded_at=self.clock(),
        )
        return self._append(
            current,
            status=(
                "plot_succeeded"
                if draft.execution.status == "succeeded"
                else "plot_failed"
            ),
            plot_execution=binding,
        )

    def delete_data(
        self, project_id: str, run_id: str, actor_id: str
    ) -> ExperimentRunManifest:
        current = self.assert_actor(project_id, run_id, actor_id)
        if current.data_asset is None:
            raise ExperimentRunVersionConflictError("run has no attached data")
        if current.data_asset.lifecycle_state in {"deleted", "expired"}:
            raise ExperimentRunVersionConflictError("run data is already unavailable")
        data_asset = current.data_asset.model_copy(
            update={
                "lifecycle_state": "deleted",
                "deleted_at": self.clock(),
            }
        )
        return self._append(
            current,
            status="data_deleted",
            data_asset=data_asset,
        )

    def _expire_if_due(self, current: ExperimentRunManifest) -> ExperimentRunManifest:
        if (
            current.data_asset is None
            or current.data_asset.lifecycle_state != "normalized_process_local"
            or current.data_asset.expires_at is None
            or current.data_asset.expires_at > self.clock()
        ):
            return current
        data_asset = current.data_asset.model_copy(
            update={"lifecycle_state": "expired"}
        )
        return self._append(
            current,
            status="data_expired",
            data_asset=data_asset,
        )

    def _append(
        self, current: ExperimentRunManifest, **updates: object
    ) -> ExperimentRunManifest:
        revision = current.revision + 1
        payload = current.model_dump()
        payload.update(updates)
        payload.update(
            {
                "run_revision_id": f"{current.run_id}:r{revision}",
                "revision": revision,
                "supersedes_run_revision_id": current.run_revision_id,
                "created_at": self.clock(),
            }
        )
        manifest = ExperimentRunManifest.model_validate(payload)
        self.store.save(manifest, expected_revision=current.revision)
        return manifest
