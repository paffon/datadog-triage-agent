"""TriageMCPClient: async context manager over the mock MCP server (stdio subprocess).

The three tools are exposed as awaitable methods returning plain JSON (dicts/lists).
The agent serializes whatever they return, so there's no pydantic re-parse here —
the models stay as shape documentation + the judge/tests' typed view. See LESSONS.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_MOCK_SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "datadog_triage_agent.mock_server"],
)


class TriageMCPClient:
    def __init__(self, server: StdioServerParameters = _MOCK_SERVER) -> None:
        self._server = server
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> TriageMCPClient:
        reader, writer = await self._stack.enter_async_context(stdio_client(self._server))
        self._session = await self._stack.enter_async_context(ClientSession(reader, writer))
        await self._session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._stack.aclose()
        self._session = None

    async def _call(self, name: str, args: dict[str, Any]) -> Any:
        assert self._session is not None, "use `async with TriageMCPClient() as mcp`"
        cleaned = {k: v for k, v in args.items() if v is not None}
        result = await self._session.call_tool(name, cleaned)
        if result.isError:
            detail = next((getattr(c, "text", "") for c in result.content if getattr(c, "text", "")), "")
            raise RuntimeError(detail or f"tool {name} failed")
        return result.structuredContent

    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        data: dict[str, Any] = await self._call("get_incident", {"incident_id": incident_id})
        return data

    async def search_logs(
        self, query: str = "", service: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        data = await self._call("search_logs", {"query": query, "service": service, "limit": limit})
        return list(data["result"])

    async def get_traces(
        self,
        service: str | None = None,
        trace_id: str | None = None,
        min_duration_ms: float | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        data = await self._call(
            "get_traces",
            {"service": service, "trace_id": trace_id, "min_duration_ms": min_duration_ms, "limit": limit},
        )
        return list(data["result"])
