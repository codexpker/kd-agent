from typing import Any

from app.gold_dataset import GoldDataset
from app.storage.neo4j_sync import Neo4jSynchronizer


class FakeResult:
    def consume(self) -> None:
        return None


class RecordingTransaction:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, **parameters: Any) -> FakeResult:
        self.calls.append((query, parameters))
        return FakeResult()


def test_graph_write_replaces_managed_subgraph_with_stable_entity_ids() -> None:
    record = GoldDataset().get("anomaly-transformer-2022")
    assert record is not None
    transaction = RecordingTransaction()

    Neo4jSynchronizer._sync_record(transaction, record)

    assert "DETACH DELETE managed" in transaction.calls[0][0]
    entity_rows = [
        row
        for query, parameters in transaction.calls
        if "SET entity += row" in query
        for row in parameters["rows"]
    ]
    entity_ids = [row["entity_id"] for row in entity_rows]
    assert len(entity_ids) == 29
    assert len(entity_ids) == len(set(entity_ids))
    assert "anomaly-transformer-2022:Evidence:ev-1" in entity_ids
    assert "anomaly-transformer-2022:Claim:cl-1" in entity_ids
