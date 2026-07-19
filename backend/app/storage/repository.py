import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import DocumentStructure, PaperDeconstruction, PaperSource
from app.storage.tables import (
    ArtifactRoleClaimRow,
    ArtifactRoleEvidenceRow,
    ArtifactRoleRow,
    ClaimEvidenceRow,
    ClaimRow,
    DocumentStructureRow,
    EvidenceAnchorRow,
    ExperimentIntentClaimRow,
    ExperimentIntentEvidenceRow,
    ExperimentIntentRow,
    GoldDatasetVersionRow,
    GraphSyncStateRow,
    NarrativeMoveEvidenceRow,
    NarrativeMoveRow,
    PaperGoldRecordRow,
    PaperLimitationRow,
    PaperRow,
    PaperSourceRow,
)


IngestAction = Literal["created", "updated", "unchanged"]
GraphSyncStatus = Literal["pending", "synced", "failed"]
SourceIngestAction = Literal["created", "updated", "unchanged", "protected"]

SOURCE_QUALITY_RANK = {
    "official_publication": 600,
    "curated_registry": 500,
    "openreview": 450,
    "crossref": 400,
    "arxiv": 300,
    "openalex": 250,
    "model_extracted": 100,
}


def _canonical_dict(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return payload, hashlib.sha256(encoded).hexdigest()


def canonical_payload(model: PaperDeconstruction | DocumentStructure) -> tuple[dict, str]:
    return _canonical_dict(model.model_dump(mode="json"))


@dataclass(frozen=True)
class PaperSourceIngestResult:
    source_key: str
    action: SourceIngestAction


@dataclass(frozen=True)
class DatabaseIngestResult:
    paper_id: str
    action: IngestAction
    content_sha256: str
    graph_status: GraphSyncStatus
    source_actions: tuple[PaperSourceIngestResult, ...]


class PaperRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def plan(
        self,
        record: PaperDeconstruction,
        structure: DocumentStructure,
        manifest: dict[str, Any],
        sources: Sequence[PaperSource] = (),
    ) -> DatabaseIngestResult:
        self._validate_source_keys(sources)
        _, record_hash = canonical_payload(record)
        _, structure_hash = canonical_payload(structure)
        _, manifest_hash = _canonical_dict(manifest)

        with self._session_factory() as session:
            source_actions = self._plan_paper_sources(session, record.paper_id, sources)
            gold_record = self._find_gold_record(
                session, record.paper_id, record.dataset_version
            )
            if gold_record is None:
                action: IngestAction = "created"
            elif gold_record.content_sha256 != record_hash:
                action = "updated"
            else:
                action = "unchanged"

            document = session.get(DocumentStructureRow, record.paper_id)
            dataset_version = session.get(GoldDatasetVersionRow, record.dataset_version)
            paper = session.get(PaperRow, record.paper_id)
            if action == "unchanged" and (
                paper is None
                or paper.content_sha256 != record_hash
                or document is None
                or document.content_sha256 != structure_hash
                or dataset_version is None
                or dataset_version.manifest_sha256 != manifest_hash
                or any(
                    item.action in {"created", "updated"} for item in source_actions
                )
            ):
                action = "updated"

            graph_state = session.get(GraphSyncStateRow, record.paper_id)
            graph_status: GraphSyncStatus = (
                graph_state.status
                if graph_state is not None and graph_state.content_sha256 == record_hash
                else "pending"
            )
            return DatabaseIngestResult(
                paper_id=record.paper_id,
                action=action,
                content_sha256=record_hash,
                graph_status=graph_status,
                source_actions=source_actions,
            )

    def upsert(
        self,
        record: PaperDeconstruction,
        structure: DocumentStructure,
        manifest: dict[str, Any],
        sources: Sequence[PaperSource] = (),
    ) -> DatabaseIngestResult:
        self._validate_source_keys(sources)
        record_payload, record_hash = canonical_payload(record)
        structure_payload, structure_hash = canonical_payload(structure)
        manifest_payload, manifest_hash = _canonical_dict(manifest)
        now = datetime.now(UTC)

        with self._session_factory.begin() as session:
            dataset_version = session.get(GoldDatasetVersionRow, record.dataset_version)
            manifest_changed = (
                dataset_version is None or dataset_version.manifest_sha256 != manifest_hash
            )
            if dataset_version is None:
                dataset_version = GoldDatasetVersionRow(
                    dataset_version=record.dataset_version,
                    description=str(manifest_payload.get("description", "")),
                    lifecycle_status=self._dataset_lifecycle(manifest_payload),
                    manifest_sha256=manifest_hash,
                    created_at=now,
                    updated_at=now,
                    frozen_at=None,
                )
                session.add(dataset_version)
            elif manifest_changed:
                dataset_version.description = str(manifest_payload.get("description", ""))
                dataset_version.lifecycle_status = self._dataset_lifecycle(manifest_payload)
                dataset_version.manifest_sha256 = manifest_hash
                dataset_version.updated_at = now

            paper = session.get(PaperRow, record.paper_id)
            paper_changed = paper is None or paper.content_sha256 != record_hash
            if paper is None:
                paper = PaperRow(
                    paper_id=record.paper_id,
                    dataset_version=record.dataset_version,
                    title=record.title,
                    venue=record.venue,
                    year=record.year,
                    annotation_status=record.status,
                    content_sha256=record_hash,
                    deconstruction=record_payload,
                    created_at=now,
                    updated_at=now,
                )
                session.add(paper)
            elif paper.content_sha256 != record_hash:
                paper.dataset_version = record.dataset_version
                paper.title = record.title
                paper.venue = record.venue
                paper.year = record.year
                paper.annotation_status = record.status
                paper.content_sha256 = record_hash
                paper.deconstruction = record_payload
                paper.updated_at = now

            session.flush()
            source_actions = self._upsert_paper_sources(
                session, record.paper_id, sources, now
            )
            gold_record = self._find_gold_record(
                session, record.paper_id, record.dataset_version
            )
            record_changed = gold_record is None or gold_record.content_sha256 != record_hash
            if gold_record is None:
                gold_record = PaperGoldRecordRow(
                    paper_id=record.paper_id,
                    dataset_version=record.dataset_version,
                    annotation_status=record.status,
                    content_sha256=record_hash,
                    source_snapshot=record_payload,
                    created_at=now,
                    updated_at=now,
                )
                session.add(gold_record)
                session.flush()
                action: IngestAction = "created"
            elif record_changed:
                gold_record.annotation_status = record.status
                gold_record.content_sha256 = record_hash
                gold_record.source_snapshot = record_payload
                gold_record.updated_at = now
                action = "updated"
            else:
                action = "unchanged"

            if record_changed:
                self._replace_authority_entities(session, gold_record.id, record)

            document = session.get(DocumentStructureRow, record.paper_id)
            document_changed = document is None or document.content_sha256 != structure_hash
            if document is None:
                session.add(
                    DocumentStructureRow(
                        paper_id=record.paper_id,
                        source=structure.source,
                        parser_name=structure.parser_name,
                        parser_version=structure.parser_version,
                        file_sha256=structure.file_sha256,
                        content_sha256=structure_hash,
                        structure=structure_payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif document_changed:
                document.source = structure.source
                document.parser_name = structure.parser_name
                document.parser_version = structure.parser_version
                document.file_sha256 = structure.file_sha256
                document.content_sha256 = structure_hash
                document.structure = structure_payload
                document.updated_at = now

            if action == "unchanged" and (
                paper_changed
                or document_changed
                or manifest_changed
                or any(
                    item.action in {"created", "updated"} for item in source_actions
                )
            ):
                action = "updated"

            graph_state = session.get(GraphSyncStateRow, record.paper_id)
            if graph_state is None:
                graph_state = GraphSyncStateRow(
                    paper_id=record.paper_id,
                    content_sha256=record_hash,
                    status="pending",
                    last_error=None,
                    synced_at=None,
                    updated_at=now,
                )
                session.add(graph_state)
            elif graph_state.content_sha256 != record_hash:
                graph_state.content_sha256 = record_hash
                graph_state.status = "pending"
                graph_state.last_error = None
                graph_state.synced_at = None
                graph_state.updated_at = now

            return DatabaseIngestResult(
                paper_id=record.paper_id,
                action=action,
                content_sha256=record_hash,
                graph_status=graph_state.status,
                source_actions=source_actions,
            )

    @staticmethod
    def _find_gold_record(
        session: Session, paper_id: str, dataset_version: str
    ) -> PaperGoldRecordRow | None:
        return session.scalar(
            select(PaperGoldRecordRow).where(
                PaperGoldRecordRow.paper_id == paper_id,
                PaperGoldRecordRow.dataset_version == dataset_version,
            )
        )

    @staticmethod
    def _dataset_lifecycle(manifest: dict[str, Any]) -> str:
        statuses = {str(item.get("status", "")) for item in manifest.get("papers", [])}
        return "frozen" if statuses == {"frozen"} else "development"

    @staticmethod
    def _validate_source_keys(sources: Sequence[PaperSource]) -> None:
        source_keys = [source.source_key for source in sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("paper sources must have unique source_key values")

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.min.replace(tzinfo=UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _source_action(
        cls, existing: PaperSourceRow | None, incoming: PaperSource
    ) -> SourceIngestAction:
        if existing is None:
            return "created"
        if (
            existing.source_type == incoming.source_type
            and existing.source_uri == incoming.source_uri
            and existing.external_id == incoming.external_id
            and existing.license_name == incoming.license_name
            and existing.access_policy == incoming.access_policy
            and (existing.source_metadata or {}) == incoming.source_metadata
            and cls._as_utc(existing.retrieved_at)
            == cls._as_utc(incoming.retrieved_at)
        ):
            return "unchanged"

        existing_quality = SOURCE_QUALITY_RANK.get(existing.source_type, 0)
        incoming_quality = SOURCE_QUALITY_RANK[incoming.source_type]
        if incoming_quality > existing_quality:
            return "updated"
        if (
            incoming_quality == existing_quality
            and cls._as_utc(incoming.retrieved_at)
            > cls._as_utc(existing.retrieved_at)
        ):
            return "updated"
        return "protected"

    @classmethod
    def _plan_paper_sources(
        cls,
        session: Session,
        paper_id: str,
        sources: Sequence[PaperSource],
    ) -> tuple[PaperSourceIngestResult, ...]:
        return tuple(
            PaperSourceIngestResult(
                source_key=source.source_key,
                action=cls._source_action(
                    session.scalar(
                        select(PaperSourceRow).where(
                            PaperSourceRow.paper_id == paper_id,
                            PaperSourceRow.source_key == source.source_key,
                        )
                    ),
                    source,
                ),
            )
            for source in sources
        )

    @classmethod
    def _upsert_paper_sources(
        cls,
        session: Session,
        paper_id: str,
        sources: Sequence[PaperSource],
        now: datetime,
    ) -> tuple[PaperSourceIngestResult, ...]:
        results: list[PaperSourceIngestResult] = []
        for source in sources:
            existing = session.scalar(
                select(PaperSourceRow).where(
                    PaperSourceRow.paper_id == paper_id,
                    PaperSourceRow.source_key == source.source_key,
                )
            )
            action = cls._source_action(existing, source)
            results.append(
                PaperSourceIngestResult(source_key=source.source_key, action=action)
            )
            if action == "created":
                session.add(
                    PaperSourceRow(
                        paper_id=paper_id,
                        source_key=source.source_key,
                        source_type=source.source_type,
                        source_uri=source.source_uri,
                        external_id=source.external_id,
                        license_name=source.license_name,
                        access_policy=source.access_policy,
                        is_primary=False,
                        source_metadata=source.source_metadata,
                        retrieved_at=source.retrieved_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif action == "updated":
                assert existing is not None
                existing.source_type = source.source_type
                existing.source_uri = source.source_uri
                existing.external_id = source.external_id
                existing.license_name = source.license_name
                existing.access_policy = source.access_policy
                existing.source_metadata = source.source_metadata
                existing.retrieved_at = source.retrieved_at
                existing.updated_at = now

        if sources:
            session.flush()
            cls._select_primary_source(session, paper_id, now)
        return tuple(results)

    @classmethod
    def _select_primary_source(
        cls, session: Session, paper_id: str, now: datetime
    ) -> None:
        rows = session.scalars(
            select(PaperSourceRow).where(PaperSourceRow.paper_id == paper_id)
        ).all()
        if not rows:
            return
        primary = max(
            rows,
            key=lambda row: (
                SOURCE_QUALITY_RANK.get(row.source_type, 0),
                cls._as_utc(row.retrieved_at),
                row.source_key,
            ),
        )
        for row in rows:
            should_be_primary = row.id == primary.id
            if row.is_primary != should_be_primary:
                row.is_primary = should_be_primary
                row.updated_at = now

    @staticmethod
    def _replace_authority_entities(
        session: Session, gold_record_id: int, record: PaperDeconstruction
    ) -> None:
        narrative_ids = select(NarrativeMoveRow.id).where(
            NarrativeMoveRow.gold_record_id == gold_record_id
        )
        claim_ids = select(ClaimRow.id).where(ClaimRow.gold_record_id == gold_record_id)
        experiment_ids = select(ExperimentIntentRow.id).where(
            ExperimentIntentRow.gold_record_id == gold_record_id
        )
        artifact_ids = select(ArtifactRoleRow.id).where(
            ArtifactRoleRow.gold_record_id == gold_record_id
        )
        session.execute(
            delete(NarrativeMoveEvidenceRow).where(
                NarrativeMoveEvidenceRow.narrative_move_id.in_(narrative_ids)
            )
        )
        session.execute(
            delete(ClaimEvidenceRow).where(ClaimEvidenceRow.claim_id.in_(claim_ids))
        )
        session.execute(
            delete(ExperimentIntentClaimRow).where(
                ExperimentIntentClaimRow.experiment_intent_id.in_(experiment_ids)
            )
        )
        session.execute(
            delete(ExperimentIntentEvidenceRow).where(
                ExperimentIntentEvidenceRow.experiment_intent_id.in_(experiment_ids)
            )
        )
        session.execute(
            delete(ArtifactRoleClaimRow).where(
                ArtifactRoleClaimRow.artifact_role_id.in_(artifact_ids)
            )
        )
        session.execute(
            delete(ArtifactRoleEvidenceRow).where(
                ArtifactRoleEvidenceRow.artifact_role_id.in_(artifact_ids)
            )
        )
        for row_type in (
            NarrativeMoveRow,
            ClaimRow,
            ExperimentIntentRow,
            ArtifactRoleRow,
            EvidenceAnchorRow,
            PaperLimitationRow,
        ):
            session.execute(delete(row_type).where(row_type.gold_record_id == gold_record_id))

        evidence_rows = {
            item.id: EvidenceAnchorRow(
                gold_record_id=gold_record_id,
                local_id=item.id,
                kind=item.kind,
                label=item.label,
                excerpt=item.excerpt,
                page=item.page,
                verified=item.verified,
            )
            for item in record.evidence
        }
        claim_rows = {
            item.id: ClaimRow(
                gold_record_id=gold_record_id,
                local_id=item.id,
                claim_type=item.claim_type,
                statement=item.statement,
            )
            for item in record.claims
        }
        narrative_rows = {
            item.id: NarrativeMoveRow(
                gold_record_id=gold_record_id,
                local_id=item.id,
                move_order=item.order,
                move=item.move,
                purpose=item.purpose,
            )
            for item in record.narrative_moves
        }
        experiment_rows = {
            item.id: ExperimentIntentRow(
                gold_record_id=gold_record_id,
                local_id=item.id,
                title=item.title,
                question=item.question,
                design_reason=item.design_reason,
                variables=item.variables,
            )
            for item in record.experiment_intents
        }
        artifact_rows = {
            item.id: ArtifactRoleRow(
                gold_record_id=gold_record_id,
                local_id=item.id,
                artifact_type=item.artifact_type,
                label=item.label,
                role=item.role,
                why_here=item.why_here,
            )
            for item in record.artifacts
        }
        session.add_all(
            [
                *evidence_rows.values(),
                *claim_rows.values(),
                *narrative_rows.values(),
                *experiment_rows.values(),
                *artifact_rows.values(),
                *(
                    PaperLimitationRow(
                        gold_record_id=gold_record_id,
                        limitation_order=index,
                        statement=statement,
                    )
                    for index, statement in enumerate(record.limitations, start=1)
                ),
            ]
        )
        session.flush()

        for item in record.narrative_moves:
            session.add_all(
                NarrativeMoveEvidenceRow(
                    narrative_move_id=narrative_rows[item.id].id,
                    evidence_anchor_id=evidence_rows[evidence_id].id,
                )
                for evidence_id in item.evidence_ids
            )
        for item in record.claims:
            session.add_all(
                ClaimEvidenceRow(
                    claim_id=claim_rows[item.id].id,
                    evidence_anchor_id=evidence_rows[evidence_id].id,
                )
                for evidence_id in item.evidence_ids
            )
        for item in record.experiment_intents:
            session.add_all(
                ExperimentIntentClaimRow(
                    experiment_intent_id=experiment_rows[item.id].id,
                    claim_id=claim_rows[claim_id].id,
                )
                for claim_id in item.supports_claim_ids
            )
            session.add_all(
                ExperimentIntentEvidenceRow(
                    experiment_intent_id=experiment_rows[item.id].id,
                    evidence_anchor_id=evidence_rows[evidence_id].id,
                )
                for evidence_id in item.evidence_ids
            )
        for item in record.artifacts:
            session.add_all(
                ArtifactRoleClaimRow(
                    artifact_role_id=artifact_rows[item.id].id,
                    claim_id=claim_rows[claim_id].id,
                )
                for claim_id in item.supports_claim_ids
            )
            session.add_all(
                ArtifactRoleEvidenceRow(
                    artifact_role_id=artifact_rows[item.id].id,
                    evidence_anchor_id=evidence_rows[evidence_id].id,
                )
                for evidence_id in item.evidence_ids
            )

    def get_document_structure(self, paper_id: str) -> DocumentStructure | None:
        with self._session_factory() as session:
            row = session.get(DocumentStructureRow, paper_id)
            if row is None or row.source != "parsed_pdf":
                return None
            payload = dict(row.structure)
            payload["evidence"] = []
            if payload.get("page_count") is None:
                pages = [
                    *(item.get("page_end") for item in payload.get("sections", [])),
                    *(item.get("page") for item in payload.get("artifacts", [])),
                    *(item.get("page") for item in payload.get("references", [])),
                ]
                payload["page_count"] = max((page for page in pages if page), default=1)
            return DocumentStructure.model_validate(payload)

    def get_paper(self, paper_id: str) -> PaperDeconstruction | None:
        with self._session_factory() as session:
            row = session.get(PaperRow, paper_id)
            return PaperDeconstruction.model_validate(row.deconstruction) if row is not None else None

    def list_papers(self) -> list[PaperDeconstruction]:
        with self._session_factory() as session:
            rows = session.scalars(select(PaperRow).order_by(PaperRow.paper_id)).all()
            return [PaperDeconstruction.model_validate(row.deconstruction) for row in rows]

    def graph_status(self, paper_id: str) -> GraphSyncStatus | None:
        with self._session_factory() as session:
            row = session.get(GraphSyncStateRow, paper_id)
            return row.status if row is not None else None

    def mark_graph_synced(self, paper_id: str, content_sha256: str) -> bool:
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            row = session.get(GraphSyncStateRow, paper_id)
            if row is None or row.content_sha256 != content_sha256:
                return False
            row.status = "synced"
            row.last_error = None
            row.synced_at = now
            row.updated_at = now
            return True

    def mark_graph_failed(self, paper_id: str, content_sha256: str, error: str) -> bool:
        with self._session_factory.begin() as session:
            row = session.get(GraphSyncStateRow, paper_id)
            if row is None or row.content_sha256 != content_sha256:
                return False
            row.status = "failed"
            row.last_error = error[:4000]
            row.updated_at = datetime.now(UTC)
            return True
