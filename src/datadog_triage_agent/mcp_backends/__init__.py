"""Backend factory. Both backends expose the same three tools, so the agent is
backend-agnostic — only this factory and the client differ."""

from __future__ import annotations

from .client import TriageMCPClient
from .datadog import DatadogMCPClient


def get_mcp_client(backend: str = "mock") -> TriageMCPClient | DatadogMCPClient:
    if backend == "mock":
        return TriageMCPClient()
    if backend == "datadog":
        return DatadogMCPClient()  # opt-in, needs creds; not exercisable here — see datadog.py
    raise ValueError(f"unknown TRIAGE_BACKEND: {backend!r} (use mock | datadog)")
