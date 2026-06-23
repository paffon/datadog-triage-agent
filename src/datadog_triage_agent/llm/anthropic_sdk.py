"""Swappable LLM provider: the Anthropic SDK (`anthropic` package).

Same `complete(messages, tools) -> str` contract as the default `claude -p`
provider. Tools are rendered into the system prompt (the in-prompt JSON
protocol) rather than via native tool use, so the agent loop is identical
across providers.

Needs `ANTHROPIC_API_KEY` — a Claude *subscription* does NOT include one (see
docs/LESSONS.md), so this path can't be exercised in the default environment.
Install with `uv sync --extra anthropic`; select with `TRIAGE_LLM=anthropic`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import TRACE
from ..models import LLMMessage, ToolSpec
from .base import LLMError
from .claude_cli import _render_tools  # identical tool→prompt rendering for both providers

log = logging.getLogger("triage.llm")  # TRACE = level 3: raw transport

# The `claude -p` CLI accepts bare aliases (haiku/sonnet/opus); the SDK needs
# real model IDs. Anything not in the map is passed through (already a full id).
_MODEL_IDS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}


@dataclass
class AnthropicSDK:
    model: str = "haiku"
    max_tokens: int = 4096  # TriageResult/action JSON is small; well above what's emitted

    def _request(
        self, messages: list[LLMMessage], tools: list[ToolSpec]
    ) -> tuple[str, list[dict[str, str]]]:
        system_parts = [m.content for m in messages if m.role == "system"]
        if tools:
            system_parts.append(_render_tools(tools))
        system = "\n\n".join(system_parts)
        convo = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        return system, convo

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("`anthropic` not installed — run `uv sync --extra anthropic`") from e

        system, convo = self._request(messages, tools)
        log.log(TRACE, "anthropic request: system=%r convo=%r", system, convo)
        try:
            resp = anthropic.Anthropic().messages.create(  # reads ANTHROPIC_API_KEY
                model=_MODEL_IDS.get(self.model, self.model),
                max_tokens=self.max_tokens,
                system=system,
                messages=convo,
            )
        except anthropic.AnthropicError as e:
            raise LLMError(f"Anthropic SDK call failed: {e}") from e

        log.log(TRACE, "anthropic response: %r", resp)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        if not text:
            raise LLMError(f"Anthropic SDK returned no text content: {resp!r}")
        return text
