from fastapi.testclient import TestClient
import pytest
from types import SimpleNamespace

from app import api as api_module
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_readiness_explains_offline_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: SimpleNamespace(
            document_structure_backend="gold",
            evidence_graph_backend="gold",
            private_pdf_preview_enabled=False,
            private_pdf_preview_root="",
            assistant_backend="offline",
            astron_agent_api_key="",
            astron_agent_api_secret="",
            astron_agent_flow_id="",
        ),
    )

    response = client.get("/api/v1/demo/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "demo-readiness-v1"
    assert payload["status"] == "ready"
    assert payload["runtime_mode"] == "offline_demo"
    assert len(payload["tour_steps"]) == 5
    checks = {item["check_id"]: item for item in payload["checks"]}
    assert checks["document_structure"]["status"] == "ready"
    assert checks["private_pdf_preview"]["status"] == "not_configured"
    assert checks["assistant_backend"]["required_for_current_mode"] is False


def test_search_includes_gold_seed() -> None:
    response = client.post("/api/v1/tools/search", json={"query": "Transformer anomaly detection", "limit": 5})
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert any(item["paper_id"] == "anomaly-transformer-2022" and item["has_gold"] for item in hits)


def test_deconstruction_has_closed_links() -> None:
    response = client.post("/api/v1/tools/paper-deconstruct/anomaly-transformer-2022")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["narrative_moves"]) == 8
    assert len(payload["claims"]) == 4
    assert len(payload["experiment_intents"]) == 2
    assert len(payload["artifacts"]) == 5
    assert len(payload["evidence"]) == 10


def test_unknown_paper_is_404() -> None:
    response = client.post("/api/v1/tools/paper-deconstruct/unknown")
    assert response.status_code == 404


def test_structure_does_not_fake_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: type("Settings", (), {"document_structure_backend": "gold"})(),
    )
    response = client.get("/api/v1/papers/anomaly-transformer-2022/document-structure")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "gold_snapshot"
    assert all(item["page"] is None for item in payload["artifacts"])
    assert payload["warnings"]
