from fastapi import APIRouter, HTTPException

from app.gold_dataset import get_gold_dataset
from app.models import DocumentStructure, PaperDeconstruction, SearchRequest, SearchResponse
from app.services.deconstruction import DeconstructionService, PaperNotFoundError
from app.services.document_structure import DocumentStructureService
from app.services.search import DemoSearchService

router = APIRouter(prefix="/api/v1")


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "mode": "offline-ready"}


@router.post("/tools/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    return DemoSearchService(get_gold_dataset()).search(request.query, request.limit)


@router.post("/tools/paper-deconstruct/{paper_id}", response_model=PaperDeconstruction)
def deconstruct(paper_id: str) -> PaperDeconstruction:
    try:
        return DeconstructionService(get_gold_dataset()).get(paper_id)
    except PaperNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No reviewed Gold record for this paper") from exc


@router.get("/papers/{paper_id}/document-structure", response_model=DocumentStructure)
def document_structure(paper_id: str) -> DocumentStructure:
    result = DocumentStructureService(get_gold_dataset()).get_gold_snapshot(paper_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No document structure for this paper")
    return result

