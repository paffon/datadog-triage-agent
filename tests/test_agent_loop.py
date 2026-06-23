"""Agent loop driven by a scripted FakeLLM + FakeMCP — fully offline, no `claude`.

Covers: happy path drives tools then finalizes; tool errors, unparseable replies,
and schema-invalid finals all recover; turn cap forces a final (success + failure).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from datadog_triage_agent.agent import AgentError, triage
from datadog_triage_agent.models import LLMMessage, ToolSpec, TriageResult

VALID_FINAL = {
    "action": "final",
    "result": {
        "incident_id": "INC-1001",
        "root_cause": "payment-gateway upstream timeout cascaded into checkout 5xx",
        "confidence": "high",
        "evidence": [{"source": "logs", "detail": "504 from payment-gateway"}],
        "reproduction_steps": ["POST /checkout while the processor stalls"],
        "candidate_fix": "bound the upstream timeout and add a circuit breaker",
    },
}


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.seen: list[list[LLMMessage]] = []

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str:
        self.seen.append(list(messages))
        assert self.responses, "FakeLLM ran out of scripted responses"
        return self.responses.pop(0)


class FakeMCP:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail = fail or set()

    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        self.calls.append("get_incident")
        if "get_incident" in self.fail:
            raise ValueError("incident store offline")
        return {"id": incident_id, "services": ["checkout-service", "payment-gateway"]}

    async def search_logs(
        self, query: str = "", service: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        self.calls.append("search_logs")
        return [{"service": "payment-gateway", "message": "upstream timeout 30000ms"}]

    async def get_traces(
        self, service: str | None = None, trace_id: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        self.calls.append("get_traces")
        return [{"trace_id": "t1", "root_service": "checkout-service", "duration_ms": 30500}]


def j(obj: Any) -> str:
    return json.dumps(obj)


def test_happy_path_drives_tools_then_finalizes() -> None:
    llm = FakeLLM([
        j({"action": "call_tool", "tool": "get_incident", "arguments": {"incident_id": "INC-1001"}}),
        j({"action": "call_tool", "tool": "search_logs", "arguments": {"query": "timeout"}}),
        j(VALID_FINAL),
    ])
    mcp = FakeMCP()
    result = asyncio.run(triage("INC-1001", mcp, llm, max_turns=6))
    assert isinstance(result, TriageResult)
    assert result.incident_id == "INC-1001"
    assert mcp.calls == ["get_incident", "search_logs"]


def test_tool_error_is_fed_back_and_agent_recovers() -> None:
    llm = FakeLLM([
        j({"action": "call_tool", "tool": "get_incident", "arguments": {"incident_id": "INC-1001"}}),
        j(VALID_FINAL),
    ])
    result = asyncio.run(triage("INC-1001", FakeMCP(fail={"get_incident"}), llm, max_turns=6))
    assert result.confidence == "high"
    last_user = llm.seen[-1][-1]
    assert "ERROR" in last_user.content and "offline" in last_user.content


def test_unknown_tool_is_rejected_then_recovers() -> None:
    llm = FakeLLM([
        j({"action": "call_tool", "tool": "delete_prod", "arguments": {}}),
        j(VALID_FINAL),
    ])
    mcp = FakeMCP()
    result = asyncio.run(triage("INC-1001", mcp, llm, max_turns=6))
    assert result.incident_id == "INC-1001"
    assert mcp.calls == []  # bogus tool never dispatched
    assert any("Unknown tool" in m.content for m in llm.seen[-1])


def test_unparseable_reply_gets_nudge_then_recovers() -> None:
    llm = FakeLLM(["no json here, sorry", j(VALID_FINAL)])
    result = asyncio.run(triage("INC-1001", FakeMCP(), llm, max_turns=6))
    assert result.root_cause.startswith("payment-gateway")
    assert any("valid JSON" in m.content for m in llm.seen[-1])


def test_invalid_final_is_rejected_then_corrected() -> None:
    bad = {"action": "final", "result": {"incident_id": "INC-1001"}}  # missing required fields
    llm = FakeLLM([j(bad), j(VALID_FINAL)])
    result = asyncio.run(triage("INC-1001", FakeMCP(), llm, max_turns=6))
    assert result.candidate_fix
    assert any("schema" in m.content for m in llm.seen[-1])


def test_turn_cap_then_forced_final_succeeds() -> None:
    call = j({"action": "call_tool", "tool": "get_incident", "arguments": {"incident_id": "INC-1001"}})
    llm = FakeLLM([call, j(VALID_FINAL)])  # 1 loop turn, then the forced final lands
    result = asyncio.run(triage("INC-1001", FakeMCP(), llm, max_turns=1))
    assert result.incident_id == "INC-1001"
    assert any("out of investigation budget" in m.content.lower() for m in llm.seen[-1])


def test_turn_cap_then_forced_final_failure_raises() -> None:
    call = j({"action": "call_tool", "tool": "get_incident", "arguments": {"incident_id": "INC-1001"}})
    llm = FakeLLM([call, call, call])  # never finalizes, even when forced
    with pytest.raises(AgentError):
        asyncio.run(triage("INC-1001", FakeMCP(), llm, max_turns=2))
