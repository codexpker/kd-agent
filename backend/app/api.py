from fastapi import APIRouter, File, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.gold_dataset import get_gold_dataset
from app.models import DocumentStructure, PaperDeconstruction, SearchRequest, SearchResponse
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
from app.research_models import ResearchOpportunityRequest, ResearchOpportunityResponse
from app.research_planning_models import ResearchCoachResponse, ResearchPlanRequest
from app.services.deconstruction import DeconstructionService, PaperNotFoundError
from app.services.document_structure import DocumentStructureService
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


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "mode": "offline-ready"}


@router.post("/tools/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    return DemoSearchService(get_gold_dataset()).search(request.query, request.limit)


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
        return _plot_draft_service().generate(project_id, request)
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
        return _plot_draft_service().execute(project_id, draft_id)
    except PlotDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlotExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
