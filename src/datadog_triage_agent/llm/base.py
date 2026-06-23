from __future__ import annotations

from typing import Protocol

from ..models import LLMMessage, ToolSpec


class LLMError(RuntimeError):
    """An LLM provider failed to return a usable completion."""


class LLMClient(Protocol):
    """A text engine. Given the transcript and a tool catalog, return the
    assistant's next reply as text. The agent parses tool calls out of it, so the
    interface stays tiny and provider-agnostic (``claude -p`` is text-only)."""

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str: ...
