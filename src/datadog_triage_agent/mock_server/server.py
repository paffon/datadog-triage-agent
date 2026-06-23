"""Offline mock MCP server: serves synthetic incident fixtures over stdio.

Exposes the same three tools as the real Datadog backend (`search_logs`,
`get_traces`, `get_incident`) so the agent code is backend-agnostic.

stdout is the JSON-RPC channel — never print to it. Logs go to stderr.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("triage-mock")


def _fixtures_dir() -> Path:
    override = os.getenv("TRIAGE_FIXTURES_DIR")
    if override:
        return Path(override)
    # server.py -> mock_server -> datadog_triage_agent -> src -> repo root
    return Path(__file__).resolve().parents[3] / "fixtures"


def _load_all(subdir: str) -> list[dict[str, Any]]:
    """Concatenate every fixture file in fixtures/<subdir> into one pool."""
    out: list[dict[str, Any]] = []
    for path in sorted((_fixtures_dir() / subdir).glob("*.json")):
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


@mcp.tool()
def search_logs(
    query: str = "",
    service: str | None = None,
    since_minutes: int = 60,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search logs by substring `query` and optional `service`, newest pool wins."""
    # ponytail: since_minutes accepted for API parity with Datadog, but the mock
    # fixtures are a fixed point-in-time snapshot so it's a no-op here. Wire real
    # time-windowing only against the live Datadog backend.
    q = query.lower()

    def matches(e: dict[str, Any]) -> bool:
        hay = e["message"].lower()
        if e.get("status_code") is not None:
            hay += f" {e['status_code']}"  # so "504" finds logs that record it as a code
        return not q or q in hay

    hits = [
        e
        for e in _load_all("logs")
        if matches(e) and (service is None or e["service"] == service)
    ]
    return hits[:limit]


@mcp.tool()
def get_traces(
    service: str | None = None,
    trace_id: str | None = None,
    min_duration_ms: float | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch traces, optionally filtered by service (root or any span), id, or duration."""

    def involves(trace: dict[str, Any], svc: str) -> bool:
        return trace["root_service"] == svc or any(
            s["service"] == svc for s in trace["spans"]
        )

    hits = [
        t
        for t in _load_all("traces")
        if (service is None or involves(t, service))
        and (trace_id is None or t["trace_id"] == trace_id)
        and (min_duration_ms is None or t["duration_ms"] >= min_duration_ms)
    ]
    return hits[:limit]


@mcp.tool()
def get_incident(incident_id: str) -> dict[str, Any]:
    """Fetch incident detail. Strips the private `ground_truth` field — the agent
    must never see it, or the eval is meaningless."""
    path = _fixtures_dir() / "incidents" / f"{incident_id}.json"
    if not path.exists():
        raise ValueError(f"unknown incident: {incident_id}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data.pop("ground_truth", None)  # CRITICAL: redact ground truth before returning
    return data
