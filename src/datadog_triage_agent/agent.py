"""Hand-rolled async triage loop. No agent framework — just a capped turn loop
over an LLM text engine and an MCP tool surface, with recovery for malformed
replies, bad tool calls, and schema-invalid finals.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .llm.base import LLMClient
from .models import LLMMessage, TriageResult
from .prompts import FORCE_FINAL, NUDGE_UNPARSEABLE, SYSTEM_PROMPT, TOOLS

TOOL_NAMES = {t.name for t in TOOLS}


class AgentError(RuntimeError):
    """The agent could not produce a valid TriageResult within its turn budget."""


def parse_action(text: str) -> dict[str, Any] | None:
    """Extract the single JSON action object from an LLM reply.

    Decodes from the first `{`, so leading/trailing prose and ``` fences are
    tolerated. ponytail: assumes the first `{` opens the real object — true for
    our JSON-only protocol; revisit if the model emits decoy braces before it.
    """
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and obj.get("action") in ("call_tool", "final"):
        return obj
    return None


async def triage(
    incident_id: str,
    mcp: Any,  # any object exposing async get_incident/search_logs/get_traces
    llm: LLMClient,
    max_turns: int = 6,
) -> TriageResult:
    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=f"Triage incident {incident_id}. Begin your investigation."),
    ]

    for _ in range(max_turns):
        reply = llm.complete(messages, TOOLS)
        messages.append(LLMMessage(role="assistant", content=reply))
        action = parse_action(reply)

        if action is None:
            messages.append(LLMMessage(role="user", content=NUDGE_UNPARSEABLE))
            continue

        if action["action"] == "final":
            result = _validate_final(action)
            if result is not None:
                return result
            messages.append(LLMMessage(
                role="user",
                content="That result did not match the required schema. "
                        "Resend a corrected final object with all fields.",
            ))
            continue

        tool = action.get("tool")
        if tool not in TOOL_NAMES:
            messages.append(LLMMessage(
                role="user",
                content=f"Unknown tool {tool!r}. Available tools: {sorted(TOOL_NAMES)}.",
            ))
            continue

        args = action.get("arguments")
        observation = await _call_tool(mcp, tool, args if isinstance(args, dict) else {})
        messages.append(LLMMessage(role="user", content=f"Observation from {tool}:\n{observation}"))

    # Out of budget: one forced synthesis attempt.
    messages.append(LLMMessage(role="user", content=FORCE_FINAL))
    action = parse_action(llm.complete(messages, TOOLS))
    if action is not None and action["action"] == "final":
        result = _validate_final(action)
        if result is not None:
            return result
    raise AgentError(f"no valid TriageResult after {max_turns} turns")


def _validate_final(action: dict[str, Any]) -> TriageResult | None:
    try:
        return TriageResult.model_validate(action.get("result"))
    except ValidationError:
        return None


async def _call_tool(mcp: Any, tool: str, args: dict[str, Any]) -> str:
    """Dispatch a tool call and return a JSON observation. Any tool failure is
    returned as text so the model can read the error and recover next turn."""
    try:
        result = await getattr(mcp, tool)(**args)
    except Exception as e:  # broad on purpose: feed every tool error back to the model
        return f"ERROR: {type(e).__name__}: {e}"
    return json.dumps(result, default=str)
