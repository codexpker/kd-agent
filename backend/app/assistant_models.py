from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AssistantBackend = Literal["offline", "astron"]
AssistantMessageOrigin = Literal[
    "user_supplied", "offline_rule", "model_generated", "system_error"
]


class AssistantSessionCreateRequest(BaseModel):
    paper_id: str = Field(min_length=1, max_length=191)


class AssistantMessageRequest(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    expected_message_count: int = Field(ge=0)


class AssistantToolRun(BaseModel):
    run_id: str
    tool_name: Literal[
        "paper_deconstruct", "document_structure", "evidence_graph"
    ]
    status: Literal["succeeded", "failed"]
    source: str
    input_summary: str
    result_summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime


class AssistantMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    origin: AssistantMessageOrigin
    content: str
    evidence_ids: list[str] = Field(default_factory=list)
    tool_run_ids: list[str] = Field(default_factory=list)
    provider_request_id: str | None = None
    created_at: datetime


class AssistantSession(BaseModel):
    session_id: str
    trace_id: str
    paper_id: str
    backend: AssistantBackend
    provider_status: Literal["ready", "unavailable"]
    provider_name: str
    model_label: str
    prompt_version: str
    storage: Literal["process_memory", "mysql"] = "process_memory"
    created_at: datetime
    updated_at: datetime
    messages: list[AssistantMessage] = Field(default_factory=list)
    tool_runs: list[AssistantToolRun] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_links(self) -> "AssistantSession":
        run_ids = {item.run_id for item in self.tool_runs}
        if len(run_ids) != len(self.tool_runs):
            raise ValueError("assistant tool run ids must be unique")
        message_ids = {item.message_id for item in self.messages}
        if len(message_ids) != len(self.messages):
            raise ValueError("assistant message ids must be unique")
        for message in self.messages:
            unknown = set(message.tool_run_ids) - run_ids
            if unknown:
                raise ValueError(f"assistant message links unknown tool runs: {unknown}")
        return self


class AssistantTurnResponse(BaseModel):
    status: Literal["succeeded", "error"]
    session: AssistantSession
    assistant_message: AssistantMessage
    tool_runs: list[AssistantToolRun]
    warning: str | None = None
