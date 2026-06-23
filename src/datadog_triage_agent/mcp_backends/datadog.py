"""DatadogMCPClient: the same three-tool surface as the mock, backed by Datadog's
remote MCP server over streamable HTTP.

Opt-in (`TRIAGE_BACKEND=datadog`) and **not exercisable in this environment** —
the user has no Datadog account. The transport + tool-name mapping are written
and typed, but every spot that needs confirmation against a live server is
marked `TODO(datadog-creds)`. See docs/DECISIONS.md for the researched tool names.

Connection config (URL + auth) is read from env here — same as the mock client
owns its `StdioServerParameters` — rather than threaded through `Settings`.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Our tight tool surface -> Datadog's actual remote-MCP tool names (researched, see DECISIONS).
# get_traces maps to two Datadog tools depending on whether a trace_id is supplied.
_DD_SEARCH_LOGS = "search_datadog_logs"
_DD_SEARCH_SPANS = "search_datadog_spans"
_DD_GET_TRACE = "get_datadog_trace"
_DD_GET_INCIDENT = "get_datadog_incident"


def _connection() -> tuple[str, dict[str, str]]:
    """(url, auth headers) from env. Raises if the URL isn't set."""
    url = os.getenv("DATADOG_MCP_URL")
    if not url:
        raise RuntimeError(
            "TRIAGE_BACKEND=datadog requires DATADOG_MCP_URL (+ DD_API_KEY / "
            "DD_APPLICATION_KEY). See .env.example. Use TRIAGE_BACKEND=mock to run offline."
        )
    # TODO(datadog-creds): confirm the real auth scheme. Datadog's remote MCP prefers
    # OAuth; API-key + app-key headers are the documented fallback. Header *names* and
    # whether DD_SITE belongs in the URL or a header are unverified (no account to test).
    headers = {
        "DD-API-KEY": os.getenv("DD_API_KEY", ""),
        "DD-APPLICATION-KEY": os.getenv("DD_APPLICATION_KEY", ""),
    }
    return url, headers


class DatadogMCPClient:
    def __init__(self) -> None:
        self._url, self._headers = _connection()
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self) -> DatadogMCPClient:
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(self._url, headers=self._headers)
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
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
        assert self._session is not None, "use `async with DatadogMCPClient() as mcp`"
        cleaned = {k: v for k, v in args.items() if v is not None}
        result = await self._session.call_tool(name, cleaned)
        if result.isError:
            detail = next(
                (getattr(c, "text", "") for c in result.content if getattr(c, "text", "")), ""
            )
            raise RuntimeError(detail or f"tool {name} failed")
        # TODO(datadog-creds): Datadog's result shape differs from the mock's
        # `{"result": [...]}` wrapping and our LogEntry/Trace/Incident schema. A real
        # impl normalizes structuredContent into our models so the agent prompt stays
        # consistent across backends. Returned raw for now.
        return result.structuredContent

    async def get_incident(self, incident_id: str) -> Any:
        # TODO(datadog-creds): confirm get_datadog_incident's arg name (incident_id vs id).
        return await self._call(_DD_GET_INCIDENT, {"incident_id": incident_id})

    async def search_logs(
        self, query: str = "", service: str | None = None, limit: int = 20
    ) -> Any:
        # TODO(datadog-creds): Datadog logs use a single query DSL string, e.g.
        # "service:checkout-service timeout". Build it from our (query, service).
        dd_query = " ".join(p for p in (f"service:{service}" if service else "", query) if p)
        return await self._call(_DD_SEARCH_LOGS, {"query": dd_query, "limit": limit})

    async def get_traces(
        self,
        service: str | None = None,
        trace_id: str | None = None,
        min_duration_ms: float | None = None,
        limit: int = 10,
    ) -> Any:
        if trace_id is not None:
            return await self._call(_DD_GET_TRACE, {"trace_id": trace_id})
        # TODO(datadog-creds): confirm search_datadog_spans' query/filter arg names.
        dd_query = f"service:{service}" if service else ""
        return await self._call(
            _DD_SEARCH_SPANS,
            {"query": dd_query, "min_duration_ms": min_duration_ms, "limit": limit},
        )
