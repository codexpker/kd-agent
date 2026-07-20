from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.gold_dataset import GoldDataset
from app.main import app
from app.services.evidence_graph import (
    EvidenceGraphUnavailableError,
    GoldEvidenceGraphSource,
    Neo4jEvidenceGraphSource,
)


class FakeQueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def single(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def run(self, query: str, **_: Any) -> FakeQueryResult:
        if self.fail:
            raise self.fail
        if "collect(DISTINCT entity)" in query:
            return FakeQueryResult(
                [
                    {
                        "paper": {
                            "title": "Example paper",
                            "venue": "TestConf",
                            "year": 2026,
                            "annotation_status": "development_seed",
                        },
                        "entities": [
                            {
                                "entity_id": "example:Claim:cl-1",
                                "local_id": "cl-1",
                                "statement": "A user-auditable claim",
                                "claim_type": "method",
                            },
                            {
                                "entity_id": "example:Evidence:ev-1",
                                "local_id": "ev-1",
                                "label": "Evidence 1",
                                "excerpt": "A bounded evidence excerpt",
                                "verified": False,
                            },
                        ],
                    }
                ]
            )
        return FakeQueryResult(
            [
                {
                    "source_id": "paper:example",
                    "target_id": "example:Claim:cl-1",
                    "relationship": "HAS_CLAIM",
                },
                {
                    "source_id": "paper:example",
                    "target_id": "example:Evidence:ev-1",
                    "relationship": "HAS_EVIDENCE",
                },
                {
                    "source_id": "example:Claim:cl-1",
                    "target_id": "example:Evidence:ev-1",
                    "relationship": "SUPPORTED_BY",
                },
            ]
        )


class FakeDriver:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    def session(self) -> FakeSession:
        return FakeSession(self.fail)


def test_gold_evidence_graph_is_closed_and_provenance_bounded() -> None:
    graph = GoldEvidenceGraphSource(GoldDataset()).get("anomaly-transformer-2022")

    assert graph.source == "gold_snapshot"
    assert len(graph.nodes) == 30
    assert len(graph.edges) == 65
    assert {node.node_type for node in graph.nodes} == {
        "paper",
        "claim",
        "experiment",
        "artifact",
        "evidence",
        "narrative_move",
    }
    assert all(
        node.verified is False
        for node in graph.nodes
        if node.node_type == "evidence"
    )
    assert graph.warnings


def test_evidence_graph_api_returns_gold_snapshot_and_unknown_is_404() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/papers/anomaly-transformer-2022/evidence-graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "gold_snapshot"
    assert len(payload["nodes"]) == 30
    assert client.get("/api/v1/papers/unknown/evidence-graph").status_code == 404


def test_neo4j_evidence_graph_maps_nodes_edges_and_source() -> None:
    graph = Neo4jEvidenceGraphSource(FakeDriver()).get("example")

    assert graph.source == "neo4j"
    assert [node.node_type for node in graph.nodes] == ["paper", "claim", "evidence"]
    assert graph.edges[-1].relationship == "SUPPORTED_BY"
    assert graph.nodes[-1].verified is False


def test_neo4j_evidence_graph_reports_unavailable_without_fallback() -> None:
    with pytest.raises(EvidenceGraphUnavailableError, match="unavailable"):
        Neo4jEvidenceGraphSource(FakeDriver(ConnectionError("offline"))).get("example")
