"""Backend factory. Both backends expose the same three tools, so the agent is
backend-agnostic — only this factory and the client differ."""

from __future__ import annotations

from .client import TriageMCPClient


def get_mcp_client(backend: str = "mock") -> TriageMCPClient:
    if backend == "mock":
        return TriageMCPClient()
    if backend == "datadog":
        raise NotImplementedError(
            "Datadog backend not wired yet (Phase 5). Use TRIAGE_BACKEND=mock."
        )
    raise ValueError(f"unknown TRIAGE_BACKEND: {backend!r} (use mock | datadog)")
