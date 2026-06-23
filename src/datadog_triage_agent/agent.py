"""Hand-rolled async triage loop. No agent framework — just a capped turn loop
over an LLM text engine and an MCP tool surface, with recovery for malformed
replies, bad tool calls, and schema-invalid finals.
"""

from __future__ import annotations

import json
import logging
from textwrap import indent
from typing import Any

from pydantic import ValidationError

from .llm.base import LLMClient
from .models import LLMMessage, TriageResult
from .prompts import FORCE_FINAL, NUDGE_UNPARSEABLE, SYSTEM_PROMPT, TOOLS

TOOL_NAMES = {t.name for t in TOOLS}

log = logging.getLogger("triage.agent")  # info = trace level 1, debug = level 2


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

    for turn in range(1, max_turns + 1):
        log.info("── turn %d/%d ──\n", turn, max_turns)
        reply = llm.complete(messages, TOOLS)
        messages.append(LLMMessage(role="assistant", content=reply))
        log.debug("assistant:\n%s", indent(reply, "  "))
        action = parse_action(reply)

        if action is None:
            log.info("· unparseable reply — nudging")
            messages.append(LLMMessage(role="user", content=NUDGE_UNPARSEABLE))
            continue

        if action["action"] == "final":
            result = _validate_final(action)
            if result is not None:
                log.info("✓ final (confidence=%s)", result.confidence)
                return result
            log.info("· final failed schema — asking for a corrected object")
            messages.append(LLMMessage(
                role="user",
                content="That result did not match the required schema. "
                        "Resend a corrected final object with all fields.",
            ))
            continue

        tool = action.get("tool")
        if tool not in TOOL_NAMES:
            log.info("· unknown tool %r — listing available tools", tool)
            messages.append(LLMMessage(
                role="user",
                content=f"Unknown tool {tool!r}. Available tools: {sorted(TOOL_NAMES)}.",
            ))
            continue

        args = action.get("arguments")
        log.info("→ call_tool %s %s\n", tool, args if isinstance(args, dict) else {})
        observation = await _call_tool(mcp, tool, args if isinstance(args, dict) else {})
        log.info("← %s:\n\n%s\n", tool, indent(observation, "  "))
        messages.append(LLMMessage(role="user", content=f"Observation from {tool}:\n{observation}"))

    # Out of budget: one forced synthesis attempt.
    log.info("· out of budget after %d turns — forcing synthesis", max_turns)
    messages.append(LLMMessage(role="user", content=FORCE_FINAL))
    reply = llm.complete(messages, TOOLS)
    log.debug("assistant:\n%s", indent(reply, "  "))
    action = parse_action(reply)
    if action is not None and action["action"] == "final":
        result = _validate_final(action)
        if result is not None:
            log.info("✓ final (confidence=%s)", result.confidence)
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
