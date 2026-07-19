import argparse
import json
from collections.abc import Sequence

from app.config import get_settings
from app.gold_dataset import GoldDataset
from app.storage.ingestion import GoldInfrastructureIngestor
from app.storage.neo4j_sync import Neo4jSynchronizer
from app.storage.runtime import get_paper_repository


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Idempotently import reviewed Gold records")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write the planned changes to MySQL; omitted means read-only dry-run",
    )
    parser.add_argument(
        "--sync-neo4j",
        action="store_true",
        help="Synchronize changed or previously failed records after the MySQL commit",
    )
    parser.add_argument(
        "--force-graph-sync",
        action="store_true",
        help="Synchronize every graph record even when MySQL content is unchanged",
    )
    args = parser.parse_args(argv)
    if (args.sync_neo4j or args.force_graph_sync) and not args.commit:
        parser.error("--sync-neo4j and --force-graph-sync require --commit")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    graph_driver = None
    graph = None
    if args.sync_neo4j or args.force_graph_sync:
        from neo4j import GraphDatabase

        graph_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        graph_driver.verify_connectivity()
        graph = Neo4jSynchronizer(graph_driver)

    try:
        results = GoldInfrastructureIngestor(
            get_paper_repository(settings.mysql_url), graph
        ).ingest_dataset(
            GoldDataset(),
            commit=args.commit,
            synchronize_graph=graph is not None,
            force_graph=args.force_graph_sync,
        )
    finally:
        if graph_driver is not None:
            graph_driver.close()

    print(
        json.dumps(
            [
                {
                    "paper_id": item.paper_id,
                    "database_action": item.database_action,
                    "committed": item.committed,
                    "graph_status": item.graph_status,
                    "overall_status": item.overall_status,
                    "error": item.error,
                }
                for item in results
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if any(item.overall_status == "partial" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
