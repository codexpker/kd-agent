from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.gold_dataset import get_gold_dataset
from app.models import DocumentStructure, PaperDeconstruction, SearchRequest, SearchResponse
from app.research_models import ResearchOpportunityRequest, ResearchOpportunityResponse
from app.research_planning_models import ResearchCoachResponse, ResearchPlanRequest
from app.services.deconstruction import DeconstructionService, PaperNotFoundError
from app.services.document_structure import DocumentStructureService
from app.services.research_opportunities import ResearchOpportunityService
from app.services.research_planning import (
    CandidateNotFoundError,
    ResearchPlanningService,
)
from app.services.search import DemoSearchService

router = APIRouter(prefix="/api/v1")


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
