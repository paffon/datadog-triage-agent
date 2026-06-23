"""LLM provider factory. Default is the `claude -p` CLI; the Anthropic SDK is a
swappable alternative (Phase 5)."""

from __future__ import annotations

from .base import LLMClient, LLMError
from .claude_cli import ClaudeCLI


def get_llm(provider: str = "cli", model: str = "haiku") -> LLMClient:
    if provider == "cli":
        return ClaudeCLI(model=model)
    if provider == "anthropic":
        raise LLMError(
            "Anthropic SDK provider not wired yet (Phase 5). Use TRIAGE_LLM=cli."
        )
    raise LLMError(f"unknown TRIAGE_LLM provider: {provider!r} (use cli | anthropic)")
