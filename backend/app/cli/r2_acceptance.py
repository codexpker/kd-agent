import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from neo4j import GraphDatabase

from app.config import get_settings
from app.gold_dataset import GoldDataset
from app.storage.ingestion import GoldInfrastructureIngestor
from app.storage.neo4j_sync import Neo4jSynchronizer
from app.storage.runtime import get_paper_repository


def main() -> int:
    settings = get_settings()
    backend_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(backend_root / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    driver.verify_connectivity()
    graph = Neo4jSynchronizer(driver)
    dataset = GoldDataset()
    ingestor = GoldInfrastructureIngestor(get_paper_repository(settings.mysql_url), graph)
    try:
        first = ingestor.ingest_dataset(
            dataset, commit=True, synchronize_graph=True, force_graph=True
        )
        second = ingestor.ingest_dataset(
            dataset, commit=True, synchronize_graph=True, force_graph=True
        )
        checks = []
        for record, result in zip(dataset.list_records(), second, strict=True):
            counts = graph.count_managed(record.paper_id)
            expected_entities = (
                len(record.evidence)
                + len(record.claims)
                + len(record.experiment_intents)
                + len(record.artifacts)
                + len(record.narrative_moves)
            )
            checks.append(
                {
                    "paper_id": record.paper_id,
                    "second_database_action": result.database_action,
                    "graph_status": result.graph_status,
                    "graph_papers": counts.papers,
                    "graph_entities": counts.managed_entities,
                    "expected_graph_entities": expected_entities,
                }
            )
            if result.database_action != "unchanged":
                raise RuntimeError(f"second import changed MySQL row for {record.paper_id}")
            if result.graph_status != "synced":
                raise RuntimeError(f"Neo4j synchronization failed for {record.paper_id}")
            if counts.papers != 1 or counts.managed_entities != expected_entities:
                raise RuntimeError(f"Neo4j is not idempotent for {record.paper_id}")
    finally:
        driver.close()

    print(
        json.dumps(
            {
                "status": "ok",
                "first_import": [item.database_action for item in first],
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
