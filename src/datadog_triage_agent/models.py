from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Observability data returned by the MCP tools ---


class LogEntry(BaseModel):
    timestamp: str
    service: str
    level: str
    message: str
    trace_id: str | None = None
    status_code: int | None = None


class Span(BaseModel):
    service: str
    op: str
    duration_ms: float
    error: bool = False
    status: str | None = None


class Trace(BaseModel):
    trace_id: str
    root_service: str
    duration_ms: float
    error: bool = False
    spans: list[Span] = Field(default_factory=list)


class Incident(BaseModel):
    id: str
    title: str
    severity: str
    status: str
    services: list[str]
    started_at: str
    error_signature: str
    summary: str
    # ground_truth is intentionally absent: the mock server strips it before the
    # agent ever sees an incident. It lives only in the fixture files, for the judge.


# --- Agent output (scored by the judge) ---


class Evidence(BaseModel):
    source: Literal["logs", "traces", "incident"]
    detail: str


class TriageResult(BaseModel):
    incident_id: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence]
    reproduction_steps: list[str]
    candidate_fix: str


# --- LLM interface types ---


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, str] = Field(default_factory=dict)  # arg name -> description
