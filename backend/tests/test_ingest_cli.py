import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.cli.ingest_gold import parse_args
from app.storage.tables import PaperGoldRecordRow, PaperRow, PaperSourceRow


def test_cli_defaults_to_dry_run() -> None:
    args = parse_args([])
    assert args.commit is False
    assert args.sync_neo4j is False


def test_cli_requires_commit_before_graph_sync() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--sync-neo4j"])
    assert parse_args(["--commit", "--sync-neo4j"]).commit is True


def test_cli_dry_run_then_explicit_commit_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "cli-integration.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

    environment = {**os.environ, "MYSQL_URL": database_url}
    dry_run = subprocess.run(
        [sys.executable, "-m", "app.cli.ingest_gold"],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    dry_run_payload = json.loads(dry_run.stdout)
    assert dry_run_payload[0]["overall_status"] == "dry_run"
    assert dry_run_payload[0]["committed"] is False
    assert dry_run_payload[0]["source_actions"][0]["action"] == "created"

    engine = create_engine(database_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 0
        assert session.scalar(select(func.count()).select_from(PaperSourceRow)) == 0

    first_commit = subprocess.run(
        [sys.executable, "-m", "app.cli.ingest_gold", "--commit"],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    second_commit = subprocess.run(
        [sys.executable, "-m", "app.cli.ingest_gold", "--commit"],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    first_payload = json.loads(first_commit.stdout)[0]
    second_payload = json.loads(second_commit.stdout)[0]
    assert first_payload["database_action"] == "created"
    assert first_payload["source_actions"][0]["action"] == "created"
    assert second_payload["database_action"] == "unchanged"
    assert second_payload["source_actions"][0]["action"] == "unchanged"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PaperGoldRecordRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperSourceRow)) == 1
