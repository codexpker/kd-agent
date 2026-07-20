import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module
from app.cli import ingest_pdf as ingest_pdf_cli
from app.gold_dataset import GoldDataset
from app.main import app
from app.models import DocumentArtifact, DocumentStructure
from app.pdf.contracts import (
    ParsedArtifact,
    ParsedDocument,
    ParsedReference,
    ParsedSection,
    PersistenceRight,
)
from app.pdf.persistence import PersistenceDeniedError, require_persistence_right
from app.pdf.service import PdfLayoutService
from app.storage.ingestion import GoldInfrastructureIngestor
from app.storage.pdf_repository import PaperNotRegisteredError, PdfRepository
from app.storage.repository import PaperRepository
from app.storage.tables import (
    Base,
    PdfArtifactRow,
    PdfBodyReferenceRow,
    PdfParseRunRow,
    PdfSectionRow,
    PdfSourceRow,
)


class FakeParser:
    name = "fixture-parser"
    version = "1.0"

    def __init__(self, parsed: ParsedDocument) -> None:
        self.parsed = parsed

    def parse(self, path: Path) -> ParsedDocument:
        return self.parsed


class RecordingRepository:
    def __init__(self) -> None:
        self.calls = 0

    def persist(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "authorized-local-fixture.pdf"
    path.write_bytes(b"%PDF-1.7\nobjective layout fixture\n%%EOF\n")
    return path


def parsed_fixture(path: Path, *, parser_version: str = "1.0") -> ParsedDocument:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ParsedDocument(
        parser_name="fixture-parser",
        parser_version=parser_version,
        file_sha256=digest,
        page_count=3,
        sections=[
            ParsedSection(
                id="sec-1",
                title="Introduction",
                level=1,
                page_start=1,
                page_end=1,
                heading_bbox=[10.0, 20.0, 150.0, 40.0],
            ),
            ParsedSection(
                id="sec-2",
                title="Experiments",
                level=1,
                page_start=2,
                page_end=3,
                heading_bbox=[10.0, 20.0, 160.0, 40.0],
            ),
        ],
        artifacts=[
            ParsedArtifact(
                id="art-1",
                artifact_type="figure",
                label="Figure 1",
                caption="Objective architecture caption.",
                page=2,
                bbox=[40.0, 100.0, 500.0, 350.0],
                caption_bbox=[40.0, 360.0, 500.0, 390.0],
            ),
            ParsedArtifact(
                id="art-2",
                artifact_type="table",
                label="Table 1",
                caption="Objective result table caption.",
                page=3,
                bbox=[50.0, 120.0, 520.0, 300.0],
                caption_bbox=[50.0, 310.0, 520.0, 340.0],
                markdown="| Method | Score |\n| --- | --- |\n| Fixture | 1.0 |",
                table_data=[["Method", "Score"], ["Fixture", "1.0"]],
            ),
        ],
        references=[
            ParsedReference(
                id="ref-1",
                artifact_id="art-1",
                text="The pipeline is shown in Figure 1.",
                page=2,
                bbox=[60.0, 70.0, 300.0, 85.0],
            ),
            ParsedReference(
                id="ref-2",
                artifact_id="art-2",
                text="Results are listed in Table 1.",
                page=3,
                bbox=[60.0, 80.0, 300.0, 95.0],
            ),
        ],
        warnings=["Synthetic fixture for persistence tests; not evaluation Gold."],
    )


@pytest.fixture
def pdf_repository() -> tuple[PdfRepository, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    GoldInfrastructureIngestor(PaperRepository(factory)).ingest_dataset(
        GoldDataset(), commit=True
    )
    return PdfRepository(factory), factory


def test_pdf_preview_is_objective_and_does_not_write_mysql(
    pdf_repository: tuple[PdfRepository, sessionmaker[Session]], pdf_path: Path
) -> None:
    _, factory = pdf_repository
    parsed = parsed_fixture(pdf_path)
    preview = PdfLayoutService().preview(
        "anomaly-transformer-2022", pdf_path, FakeParser(parsed)
    )

    assert preview.structure.source == "parsed_pdf"
    assert preview.structure.evidence == []
    assert preview.structure.artifacts[1].table_data == [
        ["Method", "Score"],
        ["Fixture", "1.0"],
    ]
    assert preview.structure.references[0].bbox == [60.0, 70.0, 300.0, 85.0]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 0
        assert session.scalar(select(func.count()).select_from(PdfParseRunRow)) == 0


def test_pdf_commit_without_right_is_blocked_before_repository_call(
    pdf_path: Path,
) -> None:
    service = PdfLayoutService()
    preview = service.preview(
        "anomaly-transformer-2022", pdf_path, FakeParser(parsed_fixture(pdf_path))
    )
    repository = RecordingRepository()

    with pytest.raises(PersistenceDeniedError):
        service.persist(preview, None, repository)  # type: ignore[arg-type]

    assert repository.calls == 0


@pytest.mark.parametrize(
    "basis",
    ["open_full_text", "user_private_copy", "institution_authorized"],
)
def test_all_allowed_pdf_right_bases_pass_the_gate(basis: str) -> None:
    right = PersistenceRight(basis=basis, confirmed_by="test-reviewer")  # type: ignore[arg-type]
    assert require_persistence_right(right) is right


def test_authorized_pdf_persistence_is_normalized_idempotent_and_queryable(
    pdf_repository: tuple[PdfRepository, sessionmaker[Session]], pdf_path: Path
) -> None:
    repository, factory = pdf_repository
    service = PdfLayoutService()
    preview = service.preview(
        "anomaly-transformer-2022", pdf_path, FakeParser(parsed_fixture(pdf_path))
    )
    right = PersistenceRight(
        basis="user_private_copy",
        confirmed_by="local-test-user",
        note="Synthetic fixture only; no real PDF is committed.",
    )

    first = service.persist(preview, right, repository)
    second = service.persist(preview, right, repository)

    assert first.action == "created"
    assert second.action == "unchanged"
    assert first.parse_run_id == second.parse_run_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 1
        assert session.scalar(select(func.count()).select_from(PdfParseRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(PdfSectionRow)) == 2
        assert session.scalar(select(func.count()).select_from(PdfArtifactRow)) == 2
        assert (
            session.scalar(select(func.count()).select_from(PdfBodyReferenceRow)) == 2
        )
        source = session.scalar(select(PdfSourceRow))
        assert source is not None
        assert source.file_sha256 == preview.file_sha256
        assert source.file_size_bytes == pdf_path.stat().st_size
        assert source.rights_basis == "user_private_copy"
        assert source.rights_confirmed_by == "local-test-user"

    structure = repository.get_document_structure("anomaly-transformer-2022")
    assert structure is not None
    assert structure.source == "parsed_pdf"
    assert structure.page_count == 3
    assert structure.sections[0].heading_bbox == [10.0, 20.0, 150.0, 40.0]
    assert structure.artifacts[0].caption == "Objective architecture caption."
    assert structure.artifacts[1].table_data[1] == ["Fixture", "1.0"]
    assert structure.references[1].artifact_id == "art-2"
    assert structure.evidence == []


def test_pdf_persistence_requires_registered_authoritative_paper(
    pdf_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = PdfRepository(factory)
    service = PdfLayoutService()
    preview = service.preview("unknown-paper", pdf_path, FakeParser(parsed_fixture(pdf_path)))

    with pytest.raises(PaperNotRegisteredError):
        service.persist(
            preview,
            PersistenceRight(
                basis="open_full_text", confirmed_by="test-reviewer"
            ),
            repository,
        )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 0


def test_parsed_document_rejects_unknown_artifact_reference(pdf_path: Path) -> None:
    parsed = parsed_fixture(pdf_path)
    payload = parsed.model_dump()
    payload["references"][0]["artifact_id"] = "missing-artifact"

    with pytest.raises(ValidationError, match="unknown parsed artifact"):
        ParsedDocument.model_validate(payload)


def test_gold_snapshot_contract_rejects_fabricated_layout_fact() -> None:
    with pytest.raises(ValidationError, match="cannot claim artifact layout facts"):
        DocumentStructure(
            paper_id="paper",
            source="gold_snapshot",
            sections=[],
            artifacts=[
                DocumentArtifact(
                    id="art-1",
                    artifact_type="figure",
                    label="Figure 1",
                    page=1,
                )
            ],
            references=[],
            evidence=[],
        )


def test_pdf_cli_defaults_to_dry_run_and_requires_right_for_commit(
    pdf_repository: tuple[PdfRepository, sessionmaker[Session]],
    pdf_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository, factory = pdf_repository
    parser = FakeParser(parsed_fixture(pdf_path))
    monkeypatch.setattr(ingest_pdf_cli, "create_pdf_parser", lambda _: parser)

    dry_run_exit = ingest_pdf_cli.main(
        ["anomaly-transformer-2022", str(pdf_path)]
    )
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run_exit == 0
    assert dry_run["overall_status"] == "dry_run"
    assert dry_run["database_action"] == "planned"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 0

    blocked_exit = ingest_pdf_cli.main(
        ["anomaly-transformer-2022", str(pdf_path), "--commit"]
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked_exit == 3
    assert blocked["overall_status"] == "blocked"

    from app.storage import runtime

    monkeypatch.setattr(runtime, "get_pdf_repository", lambda _: repository)
    monkeypatch.setattr(
        ingest_pdf_cli, "get_settings", lambda: SimpleNamespace(mysql_url="unused")
    )
    commit_args = [
        "anomaly-transformer-2022",
        str(pdf_path),
        "--commit",
        "--rights-basis",
        "institution_authorized",
        "--confirmed-by",
        "test-institution",
    ]
    first_exit = ingest_pdf_cli.main(commit_args)
    first = json.loads(capsys.readouterr().out)
    second_exit = ingest_pdf_cli.main(commit_args)
    second = json.loads(capsys.readouterr().out)
    assert first_exit == second_exit == 0
    assert first["database_action"] == "created"
    assert second["database_action"] == "unchanged"


def test_pdf_cli_subprocess_dry_run_then_explicit_commit_is_idempotent(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    database_path = tmp_path / "pdf-cli.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    environment = {**os.environ, "MYSQL_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "app.cli.ingest_gold", "--commit"],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    path = tmp_path / "cli-subprocess-fixture.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "1 Introduction")
    page.insert_text((72, 110), "Table 1: Fixture results")
    page.insert_text((72, 150), "See Table 1 for results.")
    document.save(path)
    document.close()
    base_command = [
        sys.executable,
        "-m",
        "app.cli.ingest_pdf",
        "anomaly-transformer-2022",
        str(path),
    ]

    dry_run = subprocess.run(
        base_command,
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(dry_run.stdout)["overall_status"] == "dry_run"
    engine = create_engine(database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 0

    commit_command = [
        *base_command,
        "--commit",
        "--rights-basis",
        "user_private_copy",
        "--confirmed-by",
        "subprocess-test-user",
    ]
    first = subprocess.run(
        commit_command,
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        commit_command,
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(first.stdout)["database_action"] == "created"
    assert json.loads(second.stdout)["database_action"] == "unchanged"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PdfSourceRow)) == 1
        assert session.scalar(select(func.count()).select_from(PdfParseRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(PdfArtifactRow)) == 1
        assert session.scalar(select(func.count()).select_from(PdfBodyReferenceRow)) == 1
    assert b"%PDF" not in database_path.read_bytes()


def test_document_structure_api_prefers_parsed_pdf(
    pdf_repository: tuple[PdfRepository, sessionmaker[Session]],
    pdf_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = pdf_repository
    service = PdfLayoutService()
    preview = service.preview(
        "anomaly-transformer-2022", pdf_path, FakeParser(parsed_fixture(pdf_path))
    )
    service.persist(
        preview,
        PersistenceRight(basis="open_full_text", confirmed_by="test-reviewer"),
        repository,
    )
    from app.storage import runtime

    monkeypatch.setattr(runtime, "get_pdf_repository", lambda _: repository)
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            document_structure_backend="mysql", mysql_url="unused"
        ),
    )

    response = TestClient(app).get(
        "/api/v1/papers/anomaly-transformer-2022/document-structure"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "parsed_pdf"
    assert payload["page_count"] == 3
    assert payload["artifacts"][1]["table_data"][1] == ["Fixture", "1.0"]
    assert payload["references"][0]["bbox"] == [60.0, 70.0, 300.0, 85.0]
    assert payload["evidence"] == []


def test_document_structure_api_falls_back_to_fact_free_gold_snapshot(
    pdf_repository: tuple[PdfRepository, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _ = pdf_repository
    from app.storage import runtime

    monkeypatch.setattr(runtime, "get_pdf_repository", lambda _: repository)
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            document_structure_backend="mysql", mysql_url="unused"
        ),
    )

    response = TestClient(app).get(
        "/api/v1/papers/anomaly-transformer-2022/document-structure"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "gold_snapshot"
    assert payload["parser_name"] is None
    assert payload["references"] == []
    assert payload["evidence"] == []
    assert all(item["page"] is None for item in payload["artifacts"])
    assert all(item["bbox"] is None for item in payload["artifacts"])
    assert all(item["caption"] is None for item in payload["artifacts"])


def test_private_pdf_preview_api_is_local_hash_bound_and_never_returns_raw_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "private-copy.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Table 1: private preview fixture")
    document.save(pdf_path)
    document.close()
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    structure = DocumentStructure(
        paper_id="paper-1",
        source="parsed_pdf",
        parser_name="pymupdf",
        parser_version="test",
        file_sha256=digest,
        page_count=1,
        sections=[],
        artifacts=[
            DocumentArtifact(
                id="art-1",
                artifact_type="table",
                label="Table 1",
                caption="private preview fixture",
                page=1,
                bbox=[65.0, 50.0, 310.0, 90.0],
            )
        ],
        references=[],
    )
    monkeypatch.setattr(api_module, "document_structure", lambda _: structure)
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            private_pdf_preview_enabled=True,
            private_pdf_preview_root=str(tmp_path),
            research_gateway_mode="local",
        ),
    )

    response = TestClient(app).get(
        "/api/v1/papers/paper-1/document-preview/artifacts/art-1"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-kd-preview"] == "local-private-copy"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert not response.content.startswith(b"%PDF")


def test_private_pdf_preview_api_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            private_pdf_preview_enabled=False,
            private_pdf_preview_root="",
            research_gateway_mode="local",
        ),
    )

    response = TestClient(app).get(
        "/api/v1/papers/paper-1/document-preview/pages/1"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Private PDF preview is disabled"
