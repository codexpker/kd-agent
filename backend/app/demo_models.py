from typing import Literal

from pydantic import BaseModel


class DemoReadinessCheck(BaseModel):
    check_id: str
    label: str
    status: Literal["ready", "warning", "blocked", "not_configured"]
    required_for_current_mode: bool
    detail: str
    action: str | None = None


class DemoTourStep(BaseModel):
    step_id: str
    label: str
    route: str
    instruction: str
    success_signal: str


class DemoReadinessResponse(BaseModel):
    schema_version: Literal["demo-readiness-v1"] = "demo-readiness-v1"
    status: Literal["ready", "degraded", "blocked"]
    runtime_mode: Literal["offline_demo", "local_infrastructure"]
    formal_chain_status: Literal[
        "blocked_external_configuration", "configured_unverified", "verified"
    ]
    formal_chain_detail: str
    formal_chain_blockers: list[str]
    paper_id: str
    checks: list[DemoReadinessCheck]
    tour_steps: list[DemoTourStep]
