from uuid import uuid4

from app.agent_tool_models import (
    AgentToolResponse,
    AgentToolSource,
    ComparePapersToolRequest,
    DeconstructPaperToolRequest,
    DiagnoseClaimToolRequest,
    SearchPapersToolRequest,
)
from app.gold_dataset import GoldDataset
from app.project_claim_models import ProjectClaimCreateRequest, ProjectClaimInput
from app.services.project_claims import InMemoryProjectClaimStore, ProjectClaimService
from app.services.search import DemoSearchService


TOOL_VERSION = "astron-agent-tools-v1"


class AgentToolPaperNotFoundError(LookupError):
    pass


class AgentToolService:
    """Stable, evidence-bounded contracts for Astron workflow registration."""

    def __init__(self, dataset: GoldDataset) -> None:
        self.dataset = dataset

    def search_papers(self, request: SearchPapersToolRequest) -> AgentToolResponse:
        search = DemoSearchService(self.dataset).search(request.query, request.limit)
        records = {
            hit.paper_id: self.dataset.get(hit.paper_id) for hit in search.hits
        }
        sources = [
            AgentToolSource(
                source_id=hit.paper_id,
                title=hit.title,
                source_type="paper",
                verification_status=(
                    records[hit.paper_id].status
                    if records[hit.paper_id] is not None
                    else "metadata_only"
                ),
                evidence_ids=(
                    [item.id for item in records[hit.paper_id].evidence]
                    if records[hit.paper_id] is not None
                    else []
                ),
            )
            for hit in search.hits
        ]
        return AgentToolResponse(
            result=search.model_dump(mode="json"),
            sources=sources,
            warnings=[
                "Current retrieval uses the demo registry; it is not the frozen BM25 + BGE-M3 competition index."
            ],
            evidence_status=("partial" if search.hits else "insufficient_evidence"),
            trace_id=_trace_id(),
            tool_version=TOOL_VERSION,
            data_version=_data_version(self.dataset),
        )

    def deconstruct_paper(
        self, request: DeconstructPaperToolRequest
    ) -> AgentToolResponse:
        record = self.dataset.get(request.paper_id)
        if record is None:
            raise AgentToolPaperNotFoundError(request.paper_id)
        payload = record.model_dump(mode="json")
        if request.focus != "full_chain":
            keep = {
                "claims": "claims",
                "experiments": "experiment_intents",
                "artifacts": "artifacts",
                "boundaries": "limitations",
            }[request.focus]
            payload = {
                "paper_id": record.paper_id,
                "title": record.title,
                "status": record.status,
                "focus": request.focus,
                keep: payload[keep],
                "evidence": payload["evidence"],
            }
        status = (
            "verified"
            if record.status == "frozen" and all(item.verified for item in record.evidence)
            else "partial"
        )
        warnings = []
        if status != "verified":
            warnings.append(
                f"{record.paper_id} is {record.status}; semantic annotations are not frozen Gold."
            )
        return AgentToolResponse(
            result=payload,
            sources=[_paper_source(record)],
            warnings=warnings,
            evidence_status=status,
            trace_id=_trace_id(),
            tool_version=TOOL_VERSION,
            data_version=record.dataset_version,
        )

    def compare_papers(
        self, request: ComparePapersToolRequest
    ) -> AgentToolResponse:
        records = [self.dataset.get(paper_id) for paper_id in request.paper_ids]
        found = [record for record in records if record is not None]
        missing = [
            paper_id
            for paper_id, record in zip(request.paper_ids, records, strict=True)
            if record is None
        ]
        if len(found) < 2:
            return AgentToolResponse(
                result={
                    "status": "insufficient_evidence",
                    "requested_paper_ids": request.paper_ids,
                    "available_paper_ids": [record.paper_id for record in found],
                    "comparison_focus": request.comparison_focus,
                    "matrix": [],
                },
                sources=[_paper_source(record) for record in found],
                warnings=[
                    "At least two loadable, evidence-anchored paper records are required.",
                    *([f"Unavailable paper records: {', '.join(missing)}"] if missing else []),
                ],
                evidence_status="insufficient_evidence",
                trace_id=_trace_id(),
                tool_version=TOOL_VERSION,
                data_version=_data_version(self.dataset),
            )
        matrix = [
            {
                "paper_id": record.paper_id,
                "title": record.title,
                "venue": record.venue,
                "year": record.year,
                "annotation_status": record.status,
                "claims": [
                    {
                        "claim_type": claim.claim_type,
                        "statement": claim.statement,
                        "evidence_ids": claim.evidence_ids,
                    }
                    for claim in record.claims
                    if claim.claim_type in request.comparison_focus
                ],
                "experiment_count": len(record.experiment_intents),
                "artifact_count": len(record.artifacts),
                "limitations": record.limitations,
            }
            for record in found
        ]
        all_frozen = all(record.status == "frozen" for record in found)
        return AgentToolResponse(
            result={
                "status": "ready" if all_frozen else "partial",
                "comparison_focus": request.comparison_focus,
                "matrix": matrix,
            },
            sources=[_paper_source(record) for record in found],
            warnings=(
                []
                if all_frozen
                else [
                    "The comparison contains non-frozen records and cannot support a confirmed research opportunity."
                ]
            ),
            evidence_status="verified" if all_frozen else "partial",
            trace_id=_trace_id(),
            tool_version=TOOL_VERSION,
            data_version=_data_version(self.dataset),
        )

    def diagnose_claim(
        self, request: DiagnoseClaimToolRequest
    ) -> AgentToolResponse:
        service = ProjectClaimService(InMemoryProjectClaimStore())
        project_id = f"agent-{uuid4().hex[:16]}"
        envelope = service.create(
            project_id,
            ProjectClaimCreateRequest(
                expected_latest_version=0,
                claim=ProjectClaimInput(**request.model_dump()),
            ),
        )
        return AgentToolResponse(
            result=envelope.model_dump(mode="json"),
            sources=[
                AgentToolSource(
                    source_id=envelope.claim.claim_version_id,
                    title="User-supplied research claim",
                    source_type="user_claim",
                    verification_status="user_supplied_not_verified",
                )
            ],
            warnings=[
                "This diagnosis checks minimum evidence needs; it does not assess novelty or feasibility.",
                "The stateless Agent tool does not persist the claim. Use the research workspace to save revisions.",
            ],
            evidence_status="partial",
            trace_id=_trace_id(),
            tool_version=TOOL_VERSION,
            data_version="project-claim-evidence-rules-v1",
        )


def _paper_source(record) -> AgentToolSource:
    return AgentToolSource(
        source_id=record.paper_id,
        title=record.title,
        source_type="paper",
        verification_status=record.status,
        evidence_ids=[item.id for item in record.evidence],
    )


def _trace_id() -> str:
    return f"tooltrace_{uuid4().hex}"


def _data_version(dataset: GoldDataset) -> str:
    records = dataset.list_records()
    versions = sorted({record.dataset_version for record in records})
    return ",".join(versions) if versions else "no-loadable-records"
