from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.gold_dataset import GoldDataset
from app.models import PaperSource
from app.services.document_structure import DocumentStructureService
from app.storage.ingestion import GoldInfrastructureIngestor
from app.storage.repository import PaperRepository
from app.storage.tables import (
    ArtifactRoleClaimRow,
    ArtifactRoleEvidenceRow,
    ArtifactRoleRow,
    Base,
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


AUTHORITY_TABLES = {
    "papers",
    "paper_sources",
    "gold_dataset_versions",
    "paper_gold_records",
    "narrative_moves",
    "claims",
    "experiment_intents",
    "artifact_roles",
    "evidence_anchors",
    "paper_limitations",
    "narrative_move_evidence",
    "claim_evidence",
    "experiment_intent_claims",
    "experiment_intent_evidence",
    "artifact_role_claims",
    "artifact_role_evidence",
}


class RecordingGraph:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.schema_calls = 0
        self.sync_calls = 0

    def ensure_schema(self) -> None:
        self.schema_calls += 1
        if self.error is not None:
            raise self.error

    def sync(self, record: Any) -> None:
        self.sync_calls += 1


@pytest.fixture
def repository() -> tuple[PaperRepository, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return PaperRepository(factory), factory


def test_reconstructed_migration_upgrades_from_empty_database(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.attributes["database_url"] = f"sqlite:///{database_path.as_posix()}"

    command.upgrade(config, "head")

    inspector = inspect(create_engine(config.attributes["database_url"]))
    tables = set(inspector.get_table_names())
    assert {
        "alembic_version",
        "document_structures",
        "graph_sync_states",
        *AUTHORITY_TABLES,
    } <= tables

    gold_record_foreign_keys = inspector.get_foreign_keys("paper_gold_records")
    assert {tuple(item["referred_columns"]) for item in gold_record_foreign_keys} == {
        ("paper_id",),
        ("dataset_version",),
    }
    claim_evidence_foreign_keys = inspector.get_foreign_keys("claim_evidence")
    assert {item["referred_table"] for item in claim_evidence_foreign_keys} == {
        "claims",
        "evidence_anchors",
    }

    command.downgrade(config, "0001_reconstructed")
    downgraded_tables = set(inspect(create_engine(config.attributes["database_url"])).get_table_names())
    assert not ((AUTHORITY_TABLES - {"papers"}) & downgraded_tables)
    assert {"papers", "document_structures", "graph_sync_states"} <= downgraded_tables

    command.upgrade(config, "head")
    upgraded_again = set(inspect(create_engine(config.attributes["database_url"])).get_table_names())
    assert AUTHORITY_TABLES <= upgraded_again


def test_sqlalchemy_metadata_contains_normalized_authority_entities() -> None:
    assert AUTHORITY_TABLES <= set(Base.metadata.tables)
    assert "uq_paper_gold_records_paper_dataset" in {
        constraint.name
        for constraint in Base.metadata.tables["paper_gold_records"].constraints
    }


def test_gold_import_is_idempotent_and_mysql_read_model_works(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    ingestor = GoldInfrastructureIngestor(paper_repository)

    dry_run = ingestor.ingest_dataset(dataset)
    assert dry_run[0].overall_status == "dry_run"
    assert dry_run[0].database_action == "created"
    assert dry_run[0].committed is False
    assert [item.action for item in dry_run[0].source_actions] == ["created"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 0

    first = ingestor.ingest_dataset(dataset, commit=True)
    with factory() as session:
        first_updated_at = session.scalar(select(PaperGoldRecordRow.updated_at))
    second = ingestor.ingest_dataset(dataset, commit=True)

    assert [item.database_action for item in first] == ["created"]
    assert [item.database_action for item in second] == ["unchanged"]
    assert [item.action for item in first[0].source_actions] == ["created"]
    assert [item.action for item in second[0].source_actions] == ["unchanged"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperSourceRow)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentStructureRow)) == 1
        assert session.scalar(select(func.count()).select_from(GraphSyncStateRow)) == 1
        assert session.scalar(select(func.count()).select_from(GoldDatasetVersionRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperGoldRecordRow)) == 1
        assert session.scalar(select(func.count()).select_from(NarrativeMoveRow)) == 8
        assert session.scalar(select(func.count()).select_from(ClaimRow)) == 4
        assert session.scalar(select(func.count()).select_from(ExperimentIntentRow)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactRoleRow)) == 5
        assert session.scalar(select(func.count()).select_from(EvidenceAnchorRow)) == 10
        assert session.scalar(select(func.count()).select_from(PaperLimitationRow)) == 3
        assert session.scalar(select(func.count()).select_from(NarrativeMoveEvidenceRow)) == 10
        assert session.scalar(select(func.count()).select_from(ClaimEvidenceRow)) == 7
        assert session.scalar(select(func.count()).select_from(ExperimentIntentClaimRow)) == 3
        assert session.scalar(select(func.count()).select_from(ExperimentIntentEvidenceRow)) == 3
        assert session.scalar(select(func.count()).select_from(ArtifactRoleClaimRow)) == 7
        assert session.scalar(select(func.count()).select_from(ArtifactRoleEvidenceRow)) == 6
        assert session.scalar(select(PaperGoldRecordRow.updated_at)) == first_updated_at
        source = session.scalar(select(PaperSourceRow))
        assert source is not None
        assert source.is_primary is True
        assert source.access_policy == "metadata_only"
        assert source.source_metadata["full_text_rights_confirmed"] is False

    structure = DocumentStructureService(dataset, paper_repository).get(
        "anomaly-transformer-2022", "mysql"
    )
    assert structure is not None
    assert structure.source == "gold_snapshot"
    assert all(item.page is None for item in structure.artifacts)


def test_gold_record_identity_includes_dataset_version(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None

    first = paper_repository.upsert(record, structure, dataset.manifest)
    next_version = "tad_v0.2-test"
    second_record = record.model_copy(update={"dataset_version": next_version})
    second_manifest = {**dataset.manifest, "dataset_version": next_version}
    second = paper_repository.upsert(second_record, structure, second_manifest)
    repeated = paper_repository.upsert(second_record, structure, second_manifest)

    assert first.action == "created"
    assert second.action == "created"
    assert repeated.action == "unchanged"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperGoldRecordRow)) == 2
        assert session.scalar(select(func.count()).select_from(ClaimRow)) == 8


def test_changed_gold_record_replaces_derived_entities_transactionally(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None
    paper_repository.upsert(record, structure, dataset.manifest)

    changed_statement = "Changed statement for transactional replacement test."
    changed_claim = record.claims[0].model_copy(update={"statement": changed_statement})
    changed_record = record.model_copy(
        update={"claims": [changed_claim, *record.claims[1:]]}
    )
    result = paper_repository.upsert(changed_record, structure, dataset.manifest)

    assert result.action == "updated"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClaimRow)) == 4
        assert session.scalar(select(func.count()).select_from(ClaimEvidenceRow)) == 7
        assert session.scalar(
            select(ClaimRow.statement).where(ClaimRow.local_id == changed_claim.id)
        ) == changed_statement


def test_paper_source_quality_precedes_freshness(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None
    trusted = PaperSource(
        source_key="metadata:test-provider",
        source_type="crossref",
        source_uri="https://trusted.example/record",
        external_id="trusted-id",
        license_name=None,
        access_policy="metadata_only",
        source_metadata={"title": "Trusted title"},
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    lower_quality = trusted.model_copy(
        update={
            "source_type": "model_extracted",
            "source_uri": "https://lower-quality.example/record",
            "source_metadata": {"title": "Unverified replacement"},
            "retrieved_at": datetime(2026, 2, 1, tzinfo=UTC),
        }
    )
    higher_quality = trusted.model_copy(
        update={
            "source_type": "official_publication",
            "source_uri": "https://official.example/record",
            "source_metadata": {"title": "Official title"},
            "retrieved_at": datetime(2025, 12, 1, tzinfo=UTC),
        }
    )

    created = paper_repository.upsert(
        record, structure, dataset.manifest, [trusted]
    )
    protected = paper_repository.upsert(
        record, structure, dataset.manifest, [lower_quality]
    )

    assert [item.action for item in created.source_actions] == ["created"]
    assert [item.action for item in protected.source_actions] == ["protected"]
    with factory() as session:
        row = session.scalar(
            select(PaperSourceRow).where(
                PaperSourceRow.source_key == trusted.source_key
            )
        )
        assert row is not None
        assert row.source_type == "crossref"
        assert row.source_uri == trusted.source_uri
        assert row.source_metadata == trusted.source_metadata
        assert row.retrieved_at == trusted.retrieved_at.replace(tzinfo=None)

    upgraded = paper_repository.upsert(
        record, structure, dataset.manifest, [higher_quality]
    )
    assert [item.action for item in upgraded.source_actions] == ["updated"]
    with factory() as session:
        row = session.scalar(
            select(PaperSourceRow).where(
                PaperSourceRow.source_key == trusted.source_key
            )
        )
        assert row is not None
        assert row.source_type == "official_publication"
        assert row.source_uri == higher_quality.source_uri
        assert row.source_metadata == higher_quality.source_metadata


def test_paper_source_updates_at_equal_quality_only_when_strictly_newer(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None
    original = PaperSource(
        source_key="metadata:crossref-test",
        source_type="crossref",
        source_uri="https://example.invalid/v1",
        external_id="test-id",
        license_name=None,
        access_policy="metadata_only",
        source_metadata={"version": 1},
        retrieved_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    older = original.model_copy(
        update={
            "source_uri": "https://example.invalid/older",
            "source_metadata": {"version": 0},
            "retrieved_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    newer = original.model_copy(
        update={
            "source_uri": "https://example.invalid/v2",
            "source_metadata": {"version": 2},
            "retrieved_at": datetime(2026, 3, 1, tzinfo=UTC),
        }
    )

    paper_repository.upsert(record, structure, dataset.manifest, [original])
    protected = paper_repository.upsert(record, structure, dataset.manifest, [older])
    updated = paper_repository.upsert(record, structure, dataset.manifest, [newer])

    assert [item.action for item in protected.source_actions] == ["protected"]
    assert [item.action for item in updated.source_actions] == ["updated"]
    with factory() as session:
        row = session.scalar(
            select(PaperSourceRow).where(
                PaperSourceRow.source_key == original.source_key
            )
        )
        assert row is not None
        assert row.source_uri == newer.source_uri
        assert row.source_metadata == newer.source_metadata


def test_highest_quality_paper_source_is_primary_without_deleting_alternatives(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None
    aggregator = PaperSource(
        source_key="metadata:openalex-test",
        source_type="openalex",
        source_uri="https://example.invalid/openalex",
        external_id="openalex-id",
        license_name=None,
        access_policy="metadata_only",
        source_metadata={},
        retrieved_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    official = PaperSource(
        source_key="metadata:official-test",
        source_type="official_publication",
        source_uri="https://example.invalid/official",
        external_id="official-id",
        license_name=None,
        access_policy="metadata_only",
        source_metadata={},
        retrieved_at=datetime(2025, 6, 1, tzinfo=UTC),
    )

    paper_repository.upsert(record, structure, dataset.manifest, [aggregator])
    result = paper_repository.upsert(
        record, structure, dataset.manifest, [aggregator, official]
    )

    assert [item.action for item in result.source_actions] == ["unchanged", "created"]
    with factory() as session:
        rows = session.scalars(
            select(PaperSourceRow).order_by(PaperSourceRow.source_key)
        ).all()
        assert len(rows) == 2
        assert [row.source_key for row in rows if row.is_primary] == [
            official.source_key
        ]


def test_successful_graph_sync_is_skipped_when_content_is_unchanged(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, _ = repository
    graph = RecordingGraph()
    dataset = GoldDataset()
    ingestor = GoldInfrastructureIngestor(paper_repository, graph)  # type: ignore[arg-type]

    first = ingestor.ingest_dataset(dataset, commit=True, synchronize_graph=True)
    second = ingestor.ingest_dataset(dataset, commit=True, synchronize_graph=True)

    assert first[0].graph_status == "synced"
    assert second[0].database_action == "unchanged"
    assert second[0].graph_status == "synced"
    assert graph.schema_calls == 1
    assert graph.sync_calls == 1


def test_graph_failure_is_partial_after_mysql_commit(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, factory = repository
    graph = RecordingGraph(ConnectionError("neo4j unavailable"))
    result = GoldInfrastructureIngestor(  # type: ignore[arg-type]
        paper_repository, graph
    ).ingest_dataset(GoldDataset(), commit=True, synchronize_graph=True)[0]

    assert result.overall_status == "partial"
    assert result.graph_status == "failed"
    assert "neo4j unavailable" in (result.error or "")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperGoldRecordRow)) == 1
        graph_state = session.get(GraphSyncStateRow, "anomaly-transformer-2022")
        assert graph_state is not None
        assert graph_state.status == "failed"


def test_mysql_transaction_failure_rolls_back_and_prevents_graph_synchronization(
    repository: tuple[PaperRepository, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_repository, factory = repository

    def fail_entity_write(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("mysql transaction failed")

    monkeypatch.setattr(
        PaperRepository,
        "_replace_authority_entities",
        staticmethod(fail_entity_write),
    )
    graph = RecordingGraph()
    ingestor = GoldInfrastructureIngestor(paper_repository, graph)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="mysql transaction failed"):
        ingestor.ingest_dataset(GoldDataset(), commit=True, synchronize_graph=True)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 0
        assert session.scalar(select(func.count()).select_from(PaperSourceRow)) == 0
        assert session.scalar(select(func.count()).select_from(PaperGoldRecordRow)) == 0
        assert session.scalar(select(func.count()).select_from(GoldDatasetVersionRow)) == 0
    assert graph.schema_calls == 0
    assert graph.sync_calls == 0


def test_dry_run_rejects_graph_synchronization(
    repository: tuple[PaperRepository, sessionmaker[Session]],
) -> None:
    paper_repository, _ = repository
    graph = RecordingGraph()
    ingestor = GoldInfrastructureIngestor(  # type: ignore[arg-type]
        paper_repository, graph
    )

    with pytest.raises(ValueError, match="requires an explicit MySQL commit"):
        ingestor.ingest_dataset(GoldDataset(), synchronize_graph=True)

    assert graph.schema_calls == 0
    assert graph.sync_calls == 0
