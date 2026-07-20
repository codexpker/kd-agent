from dataclasses import dataclass
from typing import Any

import httpx


class AssistantProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    request_id: str | None


class AstronWorkflowClient:
    provider_name = "astron_workflow"

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        api_secret: str,
        flow_id: str,
        model_label: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("ASTRON_AGENT_API_KEY", api_key),
                ("ASTRON_AGENT_API_SECRET", api_secret),
                ("ASTRON_AGENT_FLOW_ID", flow_id),
            )
            if not value.strip()
        ]
        if missing:
            raise AssistantProviderError(
                f"Astron workflow is not configured: {', '.join(missing)}"
            )
        if not api_url.startswith("https://"):
            raise AssistantProviderError("Astron workflow URL must use HTTPS")
        self.api_url = api_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.flow_id = flow_id
        self.model_label = model_label or "configured-in-workflow"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def complete(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        chat_id: str,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "flow_id": self.flow_id,
            "uid": "kd-agent-local",
            "parameters": {"AGENT_USER_INPUT": prompt},
            "stream": False,
            "chat_id": chat_id[:32],
            "history": history,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}:{self.api_secret}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AssistantProviderError(
                "Astron workflow request failed; no model answer was accepted"
            ) from exc

        if data.get("code") != 0:
            code = data.get("code", "unknown")
            message = str(data.get("message") or "unknown provider error")
            raise AssistantProviderError(f"Astron workflow error {code}: {message}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AssistantProviderError("Astron workflow returned no choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise AssistantProviderError("Astron workflow returned an invalid choice")
        if choice.get("finish_reason") == "interrupt":
            raise AssistantProviderError(
                "Astron workflow requested an interrupt/resume step, which is not enabled in this paper-only loop"
            )
        delta = choice.get("delta")
        content = delta.get("content") if isinstance(delta, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AssistantProviderError("Astron workflow returned an empty answer")
        return ProviderResponse(
            content=content.strip(),
            request_id=str(data.get("id")) if data.get("id") else None,
        )
