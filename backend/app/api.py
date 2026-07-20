from fastapi import APIRouter, File, Form, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.assistant_models import (
    AssistantMessageRequest,
    AssistantSession,
    AssistantSessionCreateRequest,
    AssistantTurnResponse,
)
from app.gold_dataset import get_gold_dataset
from app.models import DocumentStructure, PaperDeconstruction, SearchRequest, SearchResponse
from app.evidence_graph_models import EvidenceGraphResponse
from app.project_claim_models import (
    EvidenceDiagnosisEditRequest,
    ProjectClaimCreateRequest,
    ProjectClaimEnvelope,
    ProjectClaimHistory,
    TadProjectClaimExample,
)
from app.experiment_plan_models import (
    ExperimentPlanBundle,
    ExperimentPlanEditRequest,
    ExperimentPlanGenerateRequest,
    ExperimentPlanHistory,
)
from app.plot_draft_models import (
    DatasetUploadReport,
    PlotDraft,
    PlotExecutionResponse,
    PlotGenerationRequest,
)
from app.experiment_run_models import (
    ExperimentRunCreateRequest,
    ExperimentRunDataAttachResponse,
    ExperimentRunDataDeleteRequest,
    ExperimentRunHistory,
    ExperimentRunManifest,
)
from app.research_models import ResearchOpportunityRequest, ResearchOpportunityResponse
from app.research_planning_models import ResearchCoachResponse, ResearchPlanRequest
from app.services.deconstruction import DeconstructionService, PaperNotFoundError
from app.services.assistant_sessions import (
    AssistantSessionConflictError,
    AssistantSessionNotFoundError,
    AssistantSessionService,
    InMemoryAssistantSessionStore,
)
from app.services.astron_workflow import AssistantProviderError, AstronWorkflowClient
from app.services.document_structure import DocumentStructureService
from app.services.evidence_graph import (
    EvidenceGraphNotFoundError,
    EvidenceGraphUnavailableError,
    GoldEvidenceGraphSource,
    Neo4jEvidenceGraphSource,
)
from app.services.project_claims import (
    InMemoryProjectClaimStore,
    InvalidProjectIdError,
    ProjectClaimNotFoundError,
    ProjectClaimService,
    ProjectClaimVersionConflictError,
    tad_project_claim_example,
)
from app.services.experiment_plans import (
    ExperimentPlanNotFoundError,
    ExperimentPlanService,
    ExperimentPlanVersionConflictError,
    InMemoryExperimentPlanStore,
)
from app.services.plot_drafts import (
    MAX_UPLOAD_BYTES,
    DatasetUploadError,
    InMemoryPlotDraftStore,
    PlotDraftNotFoundError,
    PlotDraftService,
    PlotExecutionError,
)
from app.services.experiment_runs import (
    ExperimentRunIdentityError,
    ExperimentRunNotFoundError,
    ExperimentRunService,
    ExperimentRunVersionConflictError,
    InMemoryExperimentRunStore,
)
from app.services.research_opportunities import ResearchOpportunityService
from app.services.research_planning import (
    CandidateNotFoundError,
    ResearchPlanningService,
)
from app.services.search import DemoSearchService

router = APIRouter(prefix="/api/v1")
_memory_project_claim_store = InMemoryProjectClaimStore()
_memory_experiment_plan_store = InMemoryExperimentPlanStore()
_memory_plot_draft_store = InMemoryPlotDraftStore()
_memory_experiment_run_store = InMemoryExperimentRunStore()
_memory_assistant_session_store = InMemoryAssistantSessionStore()


def _assistant_session_service() -> AssistantSessionService:
    settings = get_settings()
    if settings.assistant_backend == "offline":
        return AssistantSessionService(
            _memory_assistant_session_store,
            get_gold_dataset(),
            backend="offline",
        )
    if settings.assistant_backend == "astron":
        try:
            provider = AstronWorkflowClient(
                api_url=settings.astron_agent_api_url,
                api_key=settings.astron_agent_api_key,
                api_secret=settings.astron_agent_api_secret,
                flow_id=settings.astron_agent_flow_id,
                model_label=settings.astron_agent_model_label,
                timeout_seconds=settings.assistant_model_timeout_seconds,
            )
        except AssistantProviderError as exc:
            return AssistantSessionService(
                _memory_assistant_session_store,
                get_gold_dataset(),
                backend="astron",
                provider_warning=str(exc),
            )
        return AssistantSessionService(
            _memory_assistant_session_store,
            get_gold_dataset(),
            backend="astron",
            provider=provider,
        )
    raise RuntimeError(f"Unsupported assistant_backend: {settings.assistant_backend}")


def _project_claim_service() -> ProjectClaimService:
    settings = get_settings()
    if settings.project_claim_backend == "memory":
        return ProjectClaimService(_memory_project_claim_store)
    if settings.project_claim_backend == "mysql":
        from app.storage.runtime import get_project_claim_repository

        return ProjectClaimService(get_project_claim_repository(settings.mysql_url))
    raise RuntimeError(
        f"Unsupported project_claim_backend: {settings.project_claim_backend}"
    )


def _project_claim_backend_errors() -> tuple[type[BaseException], ...]:
    if get_settings().project_claim_backend == "mysql":
        from sqlalchemy.exc import SQLAlchemyError

        return (SQLAlchemyError, RuntimeError, ImportError)
    return (RuntimeError, ImportError)


def _experiment_plan_service() -> ExperimentPlanService:
    settings = get_settings()
    claim_service = _project_claim_service()
    if settings.project_claim_backend == "memory":
        return ExperimentPlanService(_memory_experiment_plan_store, claim_service)
    if settings.project_claim_backend == "mysql":
        from app.storage.runtime import get_experiment_plan_repository

        return ExperimentPlanService(
            get_experiment_plan_repository(settings.mysql_url), claim_service
        )
    raise RuntimeError(
        f"Unsupported project_claim_backend: {settings.project_claim_backend}"
    )


def _plot_draft_service() -> PlotDraftService:
    return PlotDraftService(_memory_plot_draft_store, _experiment_plan_service())


def _experiment_run_service() -> ExperimentRunService:
    settings = get_settings()
    plan_service = _experiment_plan_service()
    if settings.experiment_run_backend == "memory":
        return ExperimentRunService(_memory_experiment_run_store, plan_service)
    if settings.experiment_run_backend == "mysql":
        if settings.project_claim_backend != "mysql":
            raise RuntimeError(
                "EXPERIMENT_RUN_BACKEND=mysql requires PROJECT_CLAIM_BACKEND=mysql"
            )
        from app.storage.runtime import get_experiment_run_repository

        return ExperimentRunService(
            get_experiment_run_repository(settings.mysql_url), plan_service
        )
    raise RuntimeError(
        f"Unsupported experiment_run_backend: {settings.experiment_run_backend}"
    )


def _experiment_run_backend_errors() -> tuple[type[BaseException], ...]:
    if get_settings().experiment_run_backend == "mysql":
        from sqlalchemy.exc import SQLAlchemyError

        return (SQLAlchemyError, RuntimeError, ImportError)
    return (RuntimeError, ImportError)


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "mode": "offline-ready"}


@router.post("/tools/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    return DemoSearchService(get_gold_dataset()).search(request.query, request.limit)


@router.post("/assistant/sessions", response_model=AssistantSession)
def create_assistant_session(
    request: AssistantSessionCreateRequest,
) -> AssistantSession:
    try:
        return _assistant_session_service().create(request.paper_id)
    except AssistantSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No public paper record") from exc
    except (RuntimeError, ImportError) as exc:
        raise HTTPException(status_code=503, detail="Assistant backend unavailable") from exc


@router.get("/assistant/sessions/{session_id}", response_model=AssistantSession)
def get_assistant_session(session_id: str) -> AssistantSession:
    try:
        return _assistant_session_service().get(session_id)
    except AssistantSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assistant session not found") from exc
    except (RuntimeError, ImportError) as exc:
        raise HTTPException(status_code=503, detail="Assistant backend unavailable") from exc


@router.post(
    "/assistant/sessions/{session_id}/messages",
    response_model=AssistantTurnResponse,
)
def send_assistant_message(
    session_id: str,
    request: AssistantMessageRequest,
) -> AssistantTurnResponse:
    try:
        return _assistant_session_service().send(session_id, request)
    except AssistantSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Assistant session not found") from exc
    except AssistantSessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, ImportError) as exc:
        raise HTTPException(status_code=503, detail="Assistant backend unavailable") from exc


@router.get(
    "/papers/{paper_id}/evidence-graph", response_model=EvidenceGraphResponse
)
def evidence_graph(paper_id: str) -> EvidenceGraphResponse:
    settings = get_settings()
    try:
        if settings.evidence_graph_backend == "gold":
            return GoldEvidenceGraphSource(get_gold_dataset()).get(paper_id)
        if settings.evidence_graph_backend == "neo4j":
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise EvidenceGraphUnavailableError(
                    "Neo4j graph backend requires the backend[infra] dependencies"
                ) from exc
            with GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
                connection_timeout=2.0,
            ) as driver:
                return Neo4jEvidenceGraphSource(driver).get(paper_id)
        raise EvidenceGraphUnavailableError(
            f"Unsupported evidence_graph_backend: {settings.evidence_graph_backend}"
        )
    except EvidenceGraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail="evidence graph not found") from exc
    except EvidenceGraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/research/opportunities", response_model=ResearchOpportunityResponse
)
def research_opportunities(
    request: ResearchOpportunityRequest,
) -> ResearchOpportunityResponse:
    return ResearchOpportunityService(get_gold_dataset()).analyze(request)


@router.post("/research/experiment-plans", response_model=ResearchCoachResponse)
def research_experiment_plan(request: ResearchPlanRequest) -> ResearchCoachResponse:
    try:
        return ResearchPlanningService(get_gold_dataset()).create(request)
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/research/project-claims/examples/tad",
    response_model=TadProjectClaimExample,
)
def tad_claim_example() -> TadProjectClaimExample:
    return tad_project_claim_example()


@router.post(
    "/research/projects/{project_id}/claims",
    response_model=ProjectClaimEnvelope,
)
def create_project_claim(
    project_id: str, request: ProjectClaimCreateRequest
) -> ProjectClaimEnvelope:
    backend_errors = _project_claim_backend_errors()
    try:
        return _project_claim_service().create(project_id, request)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectClaimVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Project Claim backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/claims",
    response_model=ProjectClaimHistory,
)
def project_claim_history(project_id: str) -> ProjectClaimHistory:
    backend_errors = _project_claim_backend_errors()
    try:
        return _project_claim_service().history(project_id)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Project Claim backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/claims/{version}",
    response_model=ProjectClaimEnvelope,
)
def get_project_claim(
    project_id: str,
    version: int = Path(ge=1),
) -> ProjectClaimEnvelope:
    backend_errors = _project_claim_backend_errors()
    try:
        return _project_claim_service().get(project_id, version)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectClaimNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Project Claim backend unavailable") from exc


@router.put(
    "/research/projects/{project_id}/claims/{version}/diagnosis",
    response_model=ProjectClaimEnvelope,
)
def edit_project_claim_diagnosis(
    request: EvidenceDiagnosisEditRequest,
    project_id: str,
    version: int = Path(ge=1),
) -> ProjectClaimEnvelope:
    backend_errors = _project_claim_backend_errors()
    try:
        return _project_claim_service().edit_diagnosis(project_id, version, request)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectClaimNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectClaimVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Project Claim backend unavailable") from exc


@router.post(
    "/research/projects/{project_id}/experiment-plans",
    response_model=ExperimentPlanBundle,
)
def generate_project_experiment_plan(
    request: ExperimentPlanGenerateRequest,
    project_id: str,
) -> ExperimentPlanBundle:
    backend_errors = _project_claim_backend_errors()
    try:
        return _experiment_plan_service().generate(project_id, request)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectClaimNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentPlanVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment plan backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/experiment-plans",
    response_model=ExperimentPlanHistory,
)
def project_experiment_plan_history(project_id: str) -> ExperimentPlanHistory:
    backend_errors = _project_claim_backend_errors()
    try:
        return _experiment_plan_service().history(project_id)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment plan backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/experiment-plans/{revision}",
    response_model=ExperimentPlanBundle,
)
def get_project_experiment_plan(
    project_id: str,
    revision: int = Path(ge=1),
) -> ExperimentPlanBundle:
    backend_errors = _project_claim_backend_errors()
    try:
        return _experiment_plan_service().get(project_id, revision)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExperimentPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment plan backend unavailable") from exc


@router.put(
    "/research/projects/{project_id}/experiment-plans/{revision}",
    response_model=ExperimentPlanBundle,
)
def edit_project_experiment_plan(
    request: ExperimentPlanEditRequest,
    project_id: str,
    revision: int = Path(ge=1),
) -> ExperimentPlanBundle:
    backend_errors = _project_claim_backend_errors()
    try:
        return _experiment_plan_service().edit(project_id, revision, request)
    except InvalidProjectIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExperimentPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentPlanVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment plan backend unavailable") from exc


@router.post(
    "/research/projects/{project_id}/experiment-runs",
    response_model=ExperimentRunManifest,
)
def create_experiment_run(
    project_id: str,
    request: ExperimentRunCreateRequest,
) -> ExperimentRunManifest:
    backend_errors = _experiment_run_backend_errors()
    try:
        return _experiment_run_service().create(project_id, request)
    except ExperimentPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/experiment-runs/{run_id}",
    response_model=ExperimentRunManifest,
)
def get_experiment_run(project_id: str, run_id: str) -> ExperimentRunManifest:
    backend_errors = _experiment_run_backend_errors()
    try:
        run = _experiment_run_service().get(project_id, run_id)
        if run.status == "data_expired":
            _memory_plot_draft_store.purge_run(run_id)
        return run
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/experiment-runs/{run_id}/history",
    response_model=ExperimentRunHistory,
)
def experiment_run_history(project_id: str, run_id: str) -> ExperimentRunHistory:
    backend_errors = _experiment_run_backend_errors()
    try:
        history = _experiment_run_service().history(project_id, run_id)
        if history.revisions[-1].status == "data_expired":
            _memory_plot_draft_store.purge_run(run_id)
        return history
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc


@router.post(
    "/research/projects/{project_id}/experiment-runs/{run_id}/data",
    response_model=ExperimentRunDataAttachResponse,
)
async def attach_experiment_run_data(
    project_id: str,
    run_id: str,
    actor_id: str = Form(...),
    file: UploadFile = File(...),
) -> ExperimentRunDataAttachResponse:
    if not file.filename:
        raise HTTPException(status_code=422, detail="uploaded filename is required")
    backend_errors = _experiment_run_backend_errors()
    try:
        run_service = _experiment_run_service()
        current = run_service.assert_actor(project_id, run_id, actor_id)
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        plot_service = _plot_draft_service()
        upload = plot_service.upload(
            project_id,
            file.filename,
            payload,
            run_id=run_id,
            retention_hours=current.lifecycle_policy.normalized_retention_hours,
        )
        try:
            updated = run_service.attach_data(project_id, run_id, actor_id, upload)
        except Exception:
            _memory_plot_draft_store.purge_upload(upload.upload_id)
            raise
        if current.lifecycle_policy.mode == "metadata_only":
            _memory_plot_draft_store.purge_upload(upload.upload_id)
        return ExperimentRunDataAttachResponse(run=updated, upload=upload)
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentRunIdentityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (DatasetUploadError, ExperimentRunVersionConflictError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc
    finally:
        await file.close()


@router.delete(
    "/research/projects/{project_id}/experiment-runs/{run_id}/data",
    response_model=ExperimentRunManifest,
)
def delete_experiment_run_data(
    project_id: str,
    run_id: str,
    request: ExperimentRunDataDeleteRequest,
) -> ExperimentRunManifest:
    backend_errors = _experiment_run_backend_errors()
    try:
        updated = _experiment_run_service().delete_data(
            project_id, run_id, request.actor_id
        )
        _memory_plot_draft_store.purge_run(run_id)
        return updated
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentRunIdentityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ExperimentRunVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc


@router.post(
    "/research/projects/{project_id}/plot-drafts/uploads",
    response_model=DatasetUploadReport,
)
async def upload_plot_dataset(
    project_id: str,
    file: UploadFile = File(...),
) -> DatasetUploadReport:
    if not file.filename:
        raise HTTPException(status_code=422, detail="uploaded filename is required")
    try:
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        return _plot_draft_service().upload(project_id, file.filename, payload)
    except DatasetUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post(
    "/research/projects/{project_id}/plot-drafts",
    response_model=PlotDraft,
)
def generate_plot_draft(
    project_id: str,
    request: PlotGenerationRequest,
) -> PlotDraft:
    backend_errors = _project_claim_backend_errors()
    try:
        if request.run_id and request.actor_id:
            _experiment_run_service().assert_plot_binding(
                project_id,
                request.run_id,
                request.actor_id,
                request.plan_revision,
                request.artifact_plan_id,
                request.upload_id,
            )
        return _plot_draft_service().generate(project_id, request)
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExperimentRunIdentityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (DatasetUploadError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExperimentPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Plot draft backend unavailable") from exc


@router.post(
    "/research/projects/{project_id}/plot-drafts/{draft_id}/execute",
    response_model=PlotExecutionResponse,
)
def execute_plot_draft(project_id: str, draft_id: str) -> PlotExecutionResponse:
    try:
        response = _plot_draft_service().execute(project_id, draft_id)
        if response.draft.run_id:
            try:
                _experiment_run_service().record_plot(
                    project_id, response.draft.run_id, response.draft
                )
            except Exception:
                _memory_plot_draft_store.purge_run(response.draft.run_id)
                raise
        return response
    except PlotDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlotExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExperimentRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ExperimentRunVersionConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _experiment_run_backend_errors() as exc:
        raise HTTPException(status_code=503, detail="Experiment run backend unavailable") from exc


@router.get(
    "/research/projects/{project_id}/plot-drafts/{draft_id}/files/{filename}"
)
def download_plot_draft_file(
    project_id: str,
    draft_id: str,
    filename: str,
) -> FileResponse:
    try:
        path = _plot_draft_service().file(project_id, draft_id, filename)
    except PlotDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_types = {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".zip": "application/zip",
    }
    return FileResponse(
        path,
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=path.name,
        content_disposition_type=(
            "inline" if path.suffix.lower() in {".png", ".svg"} else "attachment"
        ),
    )


@router.post("/tools/paper-deconstruct/{paper_id}", response_model=PaperDeconstruction)
def deconstruct(paper_id: str) -> PaperDeconstruction:
    try:
        return DeconstructionService(get_gold_dataset()).get(paper_id)
    except PaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No reviewed Gold record for this paper") from exc


@router.get("/papers/{paper_id}/document-structure", response_model=DocumentStructure)
def document_structure(paper_id: str) -> DocumentStructure:
    settings = get_settings()
    repository = None
    backend_errors: tuple[type[BaseException], ...] = (RuntimeError,)
    if settings.document_structure_backend == "mysql":
        from sqlalchemy.exc import SQLAlchemyError
        backend_errors = (SQLAlchemyError, RuntimeError, ImportError)
    try:
        if settings.document_structure_backend == "mysql":
            from app.storage.runtime import get_pdf_repository

            repository = get_pdf_repository(settings.mysql_url)
        result = DocumentStructureService(get_gold_dataset(), repository).get(
            paper_id, settings.document_structure_backend
        )
    except backend_errors as exc:
        raise HTTPException(status_code=503, detail="Document structure backend unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No document structure for this paper")
    return result
