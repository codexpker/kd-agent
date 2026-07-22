import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.gold_dataset import GoldDataset
from app.main import app
from app.services.assistant_sessions import (
    AssistantSessionService,
    InMemoryAssistantSessionStore,
)
from app.services.astron_workflow import (
    AssistantProviderError,
    AstronWorkflowClient,
    ProviderResponse,
)
from app.assistant_models import AssistantMessageRequest


class FakeProvider:
    provider_name = "fake_model"
    model_label = "fake-v1"

    def __init__(self, content: str, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls: list[dict] = []

    def complete(self, *, prompt: str, history: list[dict], chat_id: str) -> ProviderResponse:
        self.calls.append({"prompt": prompt, "history": history, "chat_id": chat_id})
        if self.fail:
            raise AssistantProviderError("provider unavailable")
        return ProviderResponse(content=self.content, request_id="provider-request-1")


def test_offline_session_runs_real_local_tools_and_keeps_history() -> None:
    service = AssistantSessionService(
        InMemoryAssistantSessionStore(), GoldDataset(), backend="offline"
    )
    session = service.create("anomaly-transformer-2022")

    first = service.send(
        session.session_id,
        AssistantMessageRequest(
            content="为什么要做消融实验？", expected_message_count=0
        ),
    )

    assert first.status == "succeeded"
    assert first.assistant_message.origin == "offline_rule"
    assert first.assistant_message.evidence_ids == ["ev-5", "ev-6", "ev-7"]
    assert [item.tool_name for item in first.tool_runs] == ["paper_deconstruct"]
    assert "[ev-7]" in first.assistant_message.content
    assert len(first.session.messages) == 2
    assert first.session.storage == "process_memory"

    second = service.send(
        session.session_id,
        AssistantMessageRequest(
            content="这些证据在PDF第几页？", expected_message_count=2
        ),
    )
    assert [item.tool_name for item in second.tool_runs] == [
        "paper_deconstruct",
        "document_structure",
    ]
    assert "gold_snapshot" in second.assistant_message.content
    assert "不能把这些位置补出来" in second.assistant_message.content
    assert len(service.get(session.session_id).messages) == 4


def test_graph_question_records_graph_tool_without_replacing_evidence_list() -> None:
    service = AssistantSessionService(
        InMemoryAssistantSessionStore(), GoldDataset(), backend="offline"
    )
    session = service.create("anomaly-transformer-2022")
    response = service.send(
        session.session_id,
        AssistantMessageRequest(
            content="显示Claim和证据的关系图", expected_message_count=0
        ),
    )

    assert [item.tool_name for item in response.tool_runs] == [
        "paper_deconstruct",
        "evidence_graph",
    ]
    assert response.tool_runs[-1].source == "gold_snapshot"
    assert "30 个节点和 65 条关系" in response.assistant_message.content


def test_model_provider_receives_tool_context_and_previous_history() -> None:
    provider = FakeProvider("关联差异用于描述关系级异常信号。[ev-3]")
    service = AssistantSessionService(
        InMemoryAssistantSessionStore(),
        GoldDataset(),
        backend="astron",
        provider=provider,
    )
    session = service.create("anomaly-transformer-2022")
    first = service.send(
        session.session_id,
        AssistantMessageRequest(content="解释关联差异", expected_message_count=0),
    )
    second = service.send(
        session.session_id,
        AssistantMessageRequest(content="它支持什么Claim？", expected_message_count=2),
    )

    assert first.status == "succeeded"
    assert first.assistant_message.origin == "model_generated"
    assert first.assistant_message.provider_request_id == "provider-request-1"
    assert first.assistant_message.evidence_ids == ["ev-3"]
    assert "工具结果" in provider.calls[0]["prompt"]
    assert "Anomaly Transformer" in provider.calls[0]["prompt"]
    assert provider.calls[1]["history"] == [
        {"role": "user", "content_type": "text", "content": "解释关联差异"},
        {
            "role": "assistant",
            "content_type": "text",
            "content": "关联差异用于描述关系级异常信号。[ev-3]",
        },
    ]
    assert second.session.trace_id == session.trace_id


def test_bad_or_failed_model_answer_is_explicit_error_without_offline_fallback() -> None:
    for provider in (
        FakeProvider("没有证据引用的模型回答"),
        FakeProvider("引用了不存在的证据。[ev-999]"),
        FakeProvider("unused", fail=True),
    ):
        service = AssistantSessionService(
            InMemoryAssistantSessionStore(),
            GoldDataset(),
            backend="astron",
            provider=provider,
        )
        session = service.create("anomaly-transformer-2022")
        response = service.send(
            session.session_id,
            AssistantMessageRequest(content="解释论文", expected_message_count=0),
        )

        assert response.status == "error"
        assert response.assistant_message.origin == "system_error"
        assert response.assistant_message.evidence_ids == []
        assert "没有展示离线模板冒充模型回答" in response.assistant_message.content
        assert response.warning


def test_requested_astron_without_credentials_is_visible_and_does_not_fallback() -> None:
    service = AssistantSessionService(
        InMemoryAssistantSessionStore(),
        GoldDataset(),
        backend="astron",
        provider_warning="Astron workflow is not configured",
    )
    session = service.create("anomaly-transformer-2022")
    response = service.send(
        session.session_id,
        AssistantMessageRequest(content="解释论文", expected_message_count=0),
    )

    assert session.provider_status == "unavailable"
    assert session.backend == "astron"
    assert session.provider_name == "astron_workflow"
    assert session.model_label == "unavailable"
    assert response.status == "error"
    assert response.assistant_message.origin == "system_error"
    assert response.assistant_message.content == "Astron workflow is not configured"
    assert response.tool_runs[0].tool_name == "paper_deconstruct"


def test_astron_client_uses_official_bearer_shape_and_parses_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "id": "astron-request-1",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "回答 [ev-1]"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = AstronWorkflowClient(
        api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
        api_key="test-key",
        api_secret="test-secret",
        flow_id="test-flow",
        model_label="test-model",
        transport=httpx.MockTransport(handler),
    )
    response = client.complete(
        prompt="bounded prompt",
        history=[{"role": "user", "content_type": "text", "content": "prior"}],
        chat_id="asst_123",
    )

    assert captured["authorization"] == "Bearer test-key:test-secret"
    assert captured["payload"]["flow_id"] == "test-flow"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["parameters"] == {
        "AGENT_USER_INPUT": "bounded prompt"
    }
    assert response == ProviderResponse(
        content="回答 [ev-1]", request_id="astron-request-1"
    )


def test_astron_client_rejects_missing_credentials_and_provider_errors() -> None:
    try:
        AstronWorkflowClient(
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="",
            api_secret="",
            flow_id="",
            model_label="test-model",
        )
    except AssistantProviderError as exc:
        assert "ASTRON_AGENT_API_KEY" in str(exc)
    else:
        raise AssertionError("missing Astron credentials must fail")

    client = AstronWorkflowClient(
        api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
        api_key="test-key",
        api_secret="test-secret",
        flow_id="test-flow",
        model_label="test-model",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"code": 20900, "message": "authorization failed"}
            )
        ),
    )
    try:
        client.complete(prompt="prompt", history=[], chat_id="session")
    except AssistantProviderError as exc:
        assert "20900" in str(exc)
    else:
        raise AssertionError("provider error must not be accepted")


def test_assistant_api_exposes_history_conflict_and_unknown_paper() -> None:
    client = TestClient(app)
    unknown = client.post(
        "/api/v1/assistant/sessions", json={"paper_id": "unknown"}
    )
    assert unknown.status_code == 404

    created = client.post(
        "/api/v1/assistant/sessions",
        json={"paper_id": "anomaly-transformer-2022"},
    )
    assert created.status_code == 200
    session = created.json()
    assert session["backend"] == "offline"
    assert session["provider_status"] == "ready"
    assert session["trace_id"].startswith("trace_")

    turn = client.post(
        f"/api/v1/assistant/sessions/{session['session_id']}/messages",
        json={"content": "为什么要设计这些实验？", "expected_message_count": 0},
    )
    assert turn.status_code == 200
    assert turn.json()["assistant_message"]["origin"] == "offline_rule"
    history = client.get(
        f"/api/v1/assistant/sessions/{session['session_id']}"
    ).json()
    assert len(history["messages"]) == 2
    assert history["messages"][-1]["tool_run_ids"]

    conflict = client.post(
        f"/api/v1/assistant/sessions/{session['session_id']}/messages",
        json={"content": "重复旧版本", "expected_message_count": 0},
    )
    assert conflict.status_code == 409


def test_mysql_session_backend_failure_returns_503_without_memory_fallback(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ASSISTANT_SESSION_BACKEND", "mysql")
    monkeypatch.setenv(
        "MYSQL_URL", f"sqlite:///{(tmp_path / 'missing-schema.sqlite3').as_posix()}"
    )
    get_settings.cache_clear()
    try:
        response = TestClient(app).post(
            "/api/v1/assistant/sessions",
            json={"paper_id": "anomaly-transformer-2022"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Assistant backend unavailable"
    finally:
        get_settings.cache_clear()
