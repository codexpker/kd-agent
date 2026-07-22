from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.assistant_models import AssistantMessageRequest
from app.gold_dataset import GoldDataset
from app.services.assistant_sessions import (
    AssistantSessionConflictError,
    AssistantSessionService,
)
from app.services.document_structure import DocumentStructureService
from app.storage.assistant_session_repository import AssistantSessionRepository
from app.storage.repository import PaperRepository
from app.storage.tables import (
    AssistantMessageEvidenceRow,
    AssistantMessageRow,
    AssistantMessageToolRunRow,
    AssistantSessionRow,
    AssistantToolRunEvidenceRow,
    AssistantToolRunRow,
    Base,
)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    structure = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    assert record is not None
    assert structure is not None
    PaperRepository(factory).upsert(record, structure, dataset.manifest)
    return factory


def test_mysql_repository_restores_messages_tool_runs_and_evidence_links() -> None:
    factory = _factory()
    first_service = AssistantSessionService(
        AssistantSessionRepository(factory), GoldDataset(), backend="offline"
    )
    created = first_service.create("anomaly-transformer-2022")
    turn = first_service.send(
        created.session_id,
        AssistantMessageRequest(
            content="显示Claim和证据的关系图", expected_message_count=0
        ),
    )

    assert turn.session.storage == "mysql"
    assert "persisted in MySQL" in turn.session.warnings[0]
    assert [item.tool_name for item in turn.tool_runs] == [
        "paper_deconstruct",
        "evidence_graph",
    ]

    restarted_service = AssistantSessionService(
        AssistantSessionRepository(factory), GoldDataset(), backend="offline"
    )
    restored = restarted_service.get(created.session_id)
    assert restored.trace_id == created.trace_id
    assert [item.content for item in restored.messages] == [
        "显示Claim和证据的关系图",
        turn.assistant_message.content,
    ]
    assert restored.messages[-1].tool_run_ids == [
        item.run_id for item in turn.tool_runs
    ]
    assert restored.messages[-1].evidence_ids == turn.assistant_message.evidence_ids
    assert restored.tool_runs[-1].evidence_ids == turn.tool_runs[-1].evidence_ids

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AssistantSessionRow)) == 1
        assert db.scalar(select(func.count()).select_from(AssistantMessageRow)) == 2
        assert db.scalar(select(func.count()).select_from(AssistantToolRunRow)) == 2
        assert (
            db.scalar(select(func.count()).select_from(AssistantMessageToolRunRow))
            == 2
        )
        assert (
            db.scalar(select(func.count()).select_from(AssistantMessageEvidenceRow))
            == len(turn.assistant_message.evidence_ids)
        )
        assert (
            db.scalar(select(func.count()).select_from(AssistantToolRunEvidenceRow))
            > 0
        )


def test_mysql_repository_preserves_optimistic_conflict_guard() -> None:
    factory = _factory()
    repository = AssistantSessionRepository(factory)
    service = AssistantSessionService(repository, GoldDataset(), backend="offline")
    created = service.create("anomaly-transformer-2022")
    stale = repository.get(created.session_id)
    assert stale is not None

    service.send(
        created.session_id,
        AssistantMessageRequest(content="解释论文证据", expected_message_count=0),
    )

    try:
        repository.save(stale, expected_message_count=0)
    except AssistantSessionConflictError as exc:
        assert "reload history" in str(exc)
    else:
        raise AssertionError("a stale assistant session write must be rejected")
