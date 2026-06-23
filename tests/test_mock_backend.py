"""Exercise the real mock MCP server over stdio (offline, no `claude` needed).

The load-bearing test here is `test_get_incident_redacts_ground_truth`: if the
agent could ever see `ground_truth`, the eval is meaningless. See CLAUDE.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "datadog_triage_agent.mock_server"],
)
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "incidents" / "INC-1001.json"


async def _session(work: Any) -> Any:
    async with stdio_client(SERVER) as (reader, writer), ClientSession(reader, writer) as s:
        await s.initialize()
        return await work(s)


def _list(result: CallToolResult) -> list[dict[str, Any]]:
    assert result.structuredContent is not None
    return result.structuredContent["result"]


def test_tools_and_filters() -> None:
    async def work(s: ClientSession) -> dict[str, Any]:
        tools = {t.name for t in (await s.list_tools()).tools}
        logs = await s.call_tool("search_logs", {"query": "timeout", "service": "payment-gateway"})
        traces = await s.call_tool("get_traces", {"service": "payment-gateway"})
        unknown = await s.call_tool("get_incident", {"incident_id": "NOPE"})
        return {"tools": tools, "logs": logs, "traces": traces, "unknown": unknown}

    out = asyncio.run(_session(work))

    assert out["tools"] == {"search_logs", "get_traces", "get_incident"}

    logs = _list(out["logs"])
    assert logs, "expected timeout logs for payment-gateway"
    assert all(e["service"] == "payment-gateway" for e in logs)
    assert all("timeout" in e["message"].lower() for e in logs)

    traces = _list(out["traces"])
    assert traces
    for t in traces:
        involved = t["root_service"] == "payment-gateway" or any(
            sp["service"] == "payment-gateway" for sp in t["spans"]
        )
        assert involved

    assert out["unknown"].isError is True


def test_get_incident_redacts_ground_truth() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "ground_truth" in raw, "fixture must contain ground_truth, or the test proves nothing"

    async def work(s: ClientSession) -> CallToolResult:
        return await s.call_tool("get_incident", {"incident_id": "INC-1001"})

    result = asyncio.run(_session(work))

    assert result.isError is False
    data = result.structuredContent
    assert data is not None and data["id"] == "INC-1001"
    assert "ground_truth" not in data
    # belt and suspenders: it must not leak through the serialized text either.
    assert all("ground_truth" not in c.text for c in result.content)
