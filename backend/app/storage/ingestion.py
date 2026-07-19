from dataclasses import dataclass
from typing import Literal

from app.gold_dataset import GoldDataset
from app.models import PaperDeconstruction
from app.services.document_structure import DocumentStructureService
from app.storage.neo4j_sync import Neo4jSynchronizer
from app.storage.repository import (
    DatabaseIngestResult,
    GraphSyncStatus,
    PaperRepository,
    PaperSourceIngestResult,
)


@dataclass(frozen=True)
class IngestionResult:
    paper_id: str
    database_action: str
    graph_status: GraphSyncStatus | Literal["not_requested"]
    committed: bool
    source_actions: tuple[PaperSourceIngestResult, ...] = ()
    error: str | None = None

    @property
    def overall_status(self) -> str:
        if not self.committed:
            return "dry_run"
        return "partial" if self.graph_status == "failed" else "ok"


class GoldInfrastructureIngestor:
    def __init__(
        self,
        repository: PaperRepository,
        graph: Neo4jSynchronizer | None = None,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._graph_schema_ready = False

    def ingest_dataset(
        self,
        dataset: GoldDataset,
        *,
        commit: bool = False,
        synchronize_graph: bool = False,
        force_graph: bool = False,
    ) -> list[IngestionResult]:
        if synchronize_graph and not commit:
            raise ValueError("Neo4j synchronization requires an explicit MySQL commit")
        if synchronize_graph and self._graph is None:
            raise ValueError("Neo4j synchronization was requested without a graph driver")
        return [
            self.ingest_record(
                record,
                dataset,
                commit=commit,
                synchronize_graph=synchronize_graph,
                force_graph=force_graph,
            )
            for record in dataset.list_records()
        ]

    def ingest_record(
        self,
        record: PaperDeconstruction,
        dataset: GoldDataset,
        *,
        commit: bool = False,
        synchronize_graph: bool = False,
        force_graph: bool = False,
    ) -> IngestionResult:
        structure = DocumentStructureService(dataset).get_gold_snapshot(record.paper_id)
        if structure is None:
            raise ValueError(f"missing document structure for {record.paper_id}")

        if not commit:
            database_result = self._repository.plan(
                record,
                structure,
                dataset.manifest,
                dataset.sources_for(record.paper_id),
            )
            return IngestionResult(
                paper_id=record.paper_id,
                database_action=database_result.action,
                graph_status="not_requested",
                committed=False,
                source_actions=database_result.source_actions,
            )

        database_result: DatabaseIngestResult = self._repository.upsert(
            record,
            structure,
            dataset.manifest,
            dataset.sources_for(record.paper_id),
        )
        should_sync = synchronize_graph and (
            force_graph
            or database_result.graph_status != "synced"
        )
        if not should_sync:
            return IngestionResult(
                paper_id=record.paper_id,
                database_action=database_result.action,
                graph_status=database_result.graph_status,
                committed=True,
                source_actions=database_result.source_actions,
            )

        assert self._graph is not None
        try:
            if not self._graph_schema_ready:
                self._graph.ensure_schema()
                self._graph_schema_ready = True
            self._graph.sync(record)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._repository.mark_graph_failed(
                record.paper_id, database_result.content_sha256, error
            )
            return IngestionResult(
                paper_id=record.paper_id,
                database_action=database_result.action,
                graph_status="failed",
                committed=True,
                source_actions=database_result.source_actions,
                error=error,
            )

        if not self._repository.mark_graph_synced(record.paper_id, database_result.content_sha256):
            error = "record changed while Neo4j synchronization was running"
            return IngestionResult(
                paper_id=record.paper_id,
                database_action=database_result.action,
                graph_status="failed",
                committed=True,
                source_actions=database_result.source_actions,
                error=error,
            )
        return IngestionResult(
            paper_id=record.paper_id,
            database_action=database_result.action,
            graph_status="synced",
            committed=True,
            source_actions=database_result.source_actions,
        )
