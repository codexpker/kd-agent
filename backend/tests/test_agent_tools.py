from fastapi.testclient import TestClient
from types import SimpleNamespace

import pytest

from app import api as api_module
from app.main import app


client = TestClient(app)


def test_agent_search_uses_stable_envelope_and_discloses_demo_backend() -> None:
    response = client.post(
        "/api/v1/agent-tools/search-papers",
        json={"query": "Transformer anomaly detection", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "agent-tool-response-v1"
    assert payload["evidence_status"] == "partial"
    assert payload["trace_id"].startswith("tooltrace_")
    assert payload["tool_version"] == "astron-agent-tools-v1"
    assert payload["result"]["backend"] == "demo"
    assert payload["sources"][0]["verification_status"] == "development_seed"
    assert "demo registry" in payload["warnings"][0]


def test_agent_deconstruction_never_promotes_development_seed_to_verified() -> None:
    response = client.post(
        "/api/v1/agent-tools/deconstruct-paper",
        json={"paper_id": "anomaly-transformer-2022", "focus": "experiments"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_status"] == "partial"
    assert payload["result"]["status"] == "development_seed"
    assert len(payload["result"]["experiment_intents"]) == 2
    assert len(payload["result"]["evidence"]) == 10
    assert "not frozen Gold" in payload["warnings"][0]


def test_agent_comparison_stops_when_two_records_are_not_available() -> None:
    response = client.post(
        "/api/v1/agent-tools/compare-papers",
        json={
            "paper_ids": ["anomaly-transformer-2022", "tranad-2022"],
            "comparison_focus": ["method", "experiment", "boundary"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_status"] == "insufficient_evidence"
    assert payload["result"]["matrix"] == []
    assert payload["result"]["available_paper_ids"] == [
        "anomaly-transformer-2022"
    ]


def test_agent_claim_diagnosis_is_stateless_and_does_not_claim_novelty() -> None:
    response = client.post(
        "/api/v1/agent-tools/diagnose-claim",
        json={
            "research_question": "Does robust scaling improve TAD under injected noise?",
            "hypothesis": "Robust scaling improves F1 under controlled noise corruption.",
            "proposed_method": "Robust normalization before the detector",
            "target_scenario": "Multivariate telemetry with injected noise",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_status"] == "partial"
    assert payload["sources"][0]["verification_status"] == (
        "user_supplied_not_verified"
    )
    assert len(payload["result"]["diagnosis"]["requirements"]) == 8
    assert payload["result"]["diagnosis"]["innovation_assessment"] == "not_assessed"
    assert any("does not persist" in warning for warning in payload["warnings"])


def test_agent_tool_operation_ids_are_importable_from_openapi() -> None:
    schema = client.get("/openapi.json").json()
    operation_ids = {
        schema["paths"][path]["post"]["operationId"]
        for path in (
            "/api/v1/agent-tools/search-papers",
            "/api/v1/agent-tools/deconstruct-paper",
            "/api/v1/agent-tools/compare-papers",
            "/api/v1/agent-tools/diagnose-claim",
        )
    }
    assert operation_ids == {
        "search_papers",
        "deconstruct_paper",
        "compare_papers",
        "diagnose_claim",
    }


def test_hosted_agent_tools_require_a_server_side_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            research_gateway_mode="hosted",
            agent_tool_api_token="expected-token",
        ),
    )

    missing = client.post(
        "/api/v1/agent-tools/search-papers",
        json={"query": "Transformer anomaly detection", "limit": 1},
    )
    accepted = client.post(
        "/api/v1/agent-tools/search-papers",
        headers={"Authorization": "Bearer expected-token"},
        json={"query": "Transformer anomaly detection", "limit": 1},
    )

    assert missing.status_code == 401
    assert accepted.status_code == 200
