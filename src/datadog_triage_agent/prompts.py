"""System prompt, tool catalog, and the corrective nudges the agent loop uses.

The tool-use protocol is in-prompt JSON (not native tool use) so the LLM
interface stays a single text function across providers. See docs/LESSONS.md.
"""

from __future__ import annotations

from .models import ToolSpec

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_incident",
        description=(
            "Fetch incident detail: title, severity, affected services, "
            "error_signature, summary. Call this first."
        ),
        parameters={"incident_id": "incident id, e.g. INC-1001"},
    ),
    ToolSpec(
        name="search_logs",
        description=(
            "Search logs across services by message substring. Returns timestamped "
            "lines with level, service, message, optional trace_id and status_code."
        ),
        parameters={
            "query": 'case-insensitive substring of the message ("" matches everything)',
            "service": "(optional) restrict to one service",
            "limit": "(optional) max rows (default 20)",
        },
    ),
    ToolSpec(
        name="get_traces",
        description=(
            "Fetch distributed traces: trace_id, root_service, duration_ms, error, "
            "and spans (service/op/duration_ms/error/status)."
        ),
        parameters={
            "service": "(optional) traces where this service is the root or in any span",
            "trace_id": "(optional) a specific trace id",
            "min_duration_ms": "(optional) only traces at least this slow",
            "limit": "(optional) max rows (default 10)",
        },
    ),
]

SYSTEM_PROMPT = """You are an incident-triage agent for a production observability stack.
Given an incident, you investigate its logs and traces through tools, find the root cause,
and produce a structured, evidence-grounded triage result.

You work one step at a time. On each step respond with EXACTLY ONE JSON object and nothing
else — no prose, no markdown code fences.

To call a tool:
{"action": "call_tool", "tool": "<tool name>", "arguments": {<args>}}

When you have enough evidence to conclude, finish with:
{"action": "final", "result": {
  "incident_id": "<the incident id>",
  "root_cause": "<concise root-cause explanation>",
  "confidence": "low" | "medium" | "high",
  "evidence": [{"source": "logs" | "traces" | "incident", "detail": "<what you saw>"}],
  "reproduction_steps": ["<step>", "..."],
  "candidate_fix": "<the single most promising fix>"
}}

How to investigate:
- Call get_incident first to learn the affected services and error signature.
- Then use search_logs and get_traces to trace the failure to its origin.
- Distinguish the service that is failing from the upstream cause of the failure.
- Ground every claim in evidence you actually retrieved; never invent log lines.
- Be efficient: a few well-chosen tool calls beat many.
"""

NUDGE_UNPARSEABLE = (
    "Your last message was not a single valid JSON object. Respond with EXACTLY one JSON "
    'object: either {"action": "call_tool", ...} or {"action": "final", ...}. No prose, '
    "no code fences."
)

FORCE_FINAL = (
    "You are out of investigation budget. Respond NOW with your best "
    '{"action": "final", "result": {...}} based on the evidence gathered so far.'
)
