from types import SimpleNamespace

from app.gold_dataset import GoldDataset
from app.services.demo_readiness import DemoReadinessService
from app.services.document_structure import DocumentStructureService
from app.services.evidence_graph import GoldEvidenceGraphSource


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "research_gateway_mode": "local",
        "document_structure_backend": "gold",
        "evidence_graph_backend": "gold",
        "private_pdf_preview_enabled": False,
        "assistant_backend": "offline",
        "assistant_session_backend": "memory",
        "astron_agent_api_key": "",
        "astron_agent_api_secret": "",
        "astron_agent_flow_id": "",
        "astron_agent_model_label": "configured-in-workflow",
        "astron_agent_tool_base_url": "",
        "maas_service_id": "",
        "platform_verification_evidence_id": "",
        "agent_tool_api_token": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_offline_readiness_is_complete_without_pdf_neo4j_or_model() -> None:
    dataset = GoldDataset()
    document = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    graph = GoldEvidenceGraphSource(dataset).get("anomaly-transformer-2022")
    assert document is not None

    result = DemoReadinessService(
        dataset,
        _settings(),
        document_loader=lambda _: document,
        graph_loader=lambda _: graph,
        private_pdf_probe=lambda _: None,
    ).get()

    assert result.status == "ready"
    assert result.runtime_mode == "offline_demo"
    assert result.formal_chain_status == "blocked_external_configuration"
    assert "星辰工作流后端未启用" in result.formal_chain_blockers
    assert len(result.tour_steps) == 5
    checks = {item.check_id: item for item in result.checks}
    assert checks["document_structure"].status == "ready"
    assert checks["private_pdf_preview"].status == "not_configured"
    assert checks["private_pdf_preview"].required_for_current_mode is False
    assert checks["assistant_backend"].status == "ready"
    assert checks["assistant_session_storage"].status == "ready"
    assert checks["assistant_session_storage"].required_for_current_mode is False


def test_local_infrastructure_readiness_requires_real_pdf_and_neo4j() -> None:
    dataset = GoldDataset()
    document = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    graph = GoldEvidenceGraphSource(dataset).get("anomaly-transformer-2022")
    assert document is not None
    document = document.model_copy(
        update={
            "source": "parsed_pdf",
            "parser_name": "pymupdf",
            "parser_version": "test",
            "file_sha256": "a" * 64,
            "page_count": 20,
        }
    )
    graph = graph.model_copy(update={"source": "neo4j"})
    probed: list[str] = []

    result = DemoReadinessService(
        dataset,
        _settings(
            document_structure_backend="mysql",
            evidence_graph_backend="neo4j",
            private_pdf_preview_enabled=True,
            assistant_session_backend="mysql",
        ),
        document_loader=lambda _: document,
        graph_loader=lambda _: graph,
        private_pdf_probe=lambda value: probed.append(value.file_sha256 or ""),
    ).get()

    assert result.status == "ready"
    assert result.runtime_mode == "local_infrastructure"
    assert probed == ["a" * 64]
    assert all(
        item.status == "ready"
        for item in result.checks
        if item.required_for_current_mode
    )
    assert next(
        item for item in result.checks if item.check_id == "assistant_session_storage"
    ).status == "ready"
    assert result.formal_chain_status == "blocked_external_configuration"


def test_formal_chain_is_not_verified_by_credentials_alone() -> None:
    dataset = GoldDataset()
    document = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    graph = GoldEvidenceGraphSource(dataset).get("anomaly-transformer-2022")
    assert document is not None

    result = DemoReadinessService(
        dataset,
        _settings(
            assistant_backend="astron",
            research_gateway_mode="hosted",
            astron_agent_api_key="configured",
            astron_agent_api_secret="configured",
            astron_agent_flow_id="flow-id",
            astron_agent_model_label="spark-literature-model-v1",
            astron_agent_tool_base_url="https://example.test",
            maas_service_id="service-id",
            agent_tool_api_token="agent-tool-token",
        ),
        document_loader=lambda _: document,
        graph_loader=lambda _: graph,
        private_pdf_probe=lambda _: None,
    ).get()

    assert result.formal_chain_status == "configured_unverified"
    assert result.formal_chain_blockers == ["缺少正式链路核验证据编号"]


def test_formal_chain_requires_explicit_verification_evidence() -> None:
    dataset = GoldDataset()
    document = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    graph = GoldEvidenceGraphSource(dataset).get("anomaly-transformer-2022")
    assert document is not None

    result = DemoReadinessService(
        dataset,
        _settings(
            assistant_backend="astron",
            research_gateway_mode="hosted",
            astron_agent_api_key="configured",
            astron_agent_api_secret="configured",
            astron_agent_flow_id="flow-id",
            astron_agent_model_label="spark-literature-model-v1",
            astron_agent_tool_base_url="https://example.test",
            maas_service_id="service-id",
            agent_tool_api_token="agent-tool-token",
            platform_verification_evidence_id="platform-proof-001",
        ),
        document_loader=lambda _: document,
        graph_loader=lambda _: graph,
        private_pdf_probe=lambda _: None,
    ).get()

    assert result.formal_chain_status == "verified"
    assert result.formal_chain_blockers == []


def test_local_infrastructure_reports_missing_private_pdf_as_blocked() -> None:
    dataset = GoldDataset()
    document = DocumentStructureService(dataset).get_gold_snapshot(
        "anomaly-transformer-2022"
    )
    graph = GoldEvidenceGraphSource(dataset).get("anomaly-transformer-2022")
    assert document is not None
    document = document.model_copy(
        update={
            "source": "parsed_pdf",
            "file_sha256": "b" * 64,
            "page_count": 20,
        }
    )
    graph = graph.model_copy(update={"source": "neo4j"})

    def fail_probe(_: object) -> None:
        raise RuntimeError("path is deliberately hidden")

    result = DemoReadinessService(
        dataset,
        _settings(
            document_structure_backend="mysql",
            evidence_graph_backend="neo4j",
            private_pdf_preview_enabled=True,
            assistant_session_backend="mysql",
        ),
        document_loader=lambda _: document,
        graph_loader=lambda _: graph,
        private_pdf_probe=fail_probe,
    ).get()

    assert result.status == "blocked"
    preview = next(
        item for item in result.checks if item.check_id == "private_pdf_preview"
    )
    assert preview.status == "blocked"
    assert "path is deliberately hidden" not in preview.detail
