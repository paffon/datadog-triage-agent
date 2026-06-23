"""End-to-end triage demo on one mock incident.

Usage: ./run.ps1 demo [INC-1001] [-v|-vv|-vvv]   (default INC-1001; -v traces to stderr)
First real end-to-end path: real `claude -p` + the mock MCP server over stdio.
"""

from __future__ import annotations

import asyncio
import sys

from .agent import triage
from .config import Settings, force_utf8_stdout, setup_trace, trace_level
from .llm import get_llm
from .mcp_backends import get_mcp_client
from .models import TriageResult


def _render(r: TriageResult) -> str:
    lines = [
        f"Incident:    {r.incident_id}",
        f"Confidence:  {r.confidence}",
        "",
        "Root cause:",
        f"  {r.root_cause}",
        "",
        "Evidence:",
        *(f"  [{e.source}] {e.detail}" for e in r.evidence),
        "",
        "Reproduction steps:",
        *(f"  {i}. {step}" for i, step in enumerate(r.reproduction_steps, 1)),
        "",
        "Candidate fix:",
        f"  {r.candidate_fix}",
    ]
    return "\n".join(lines)


async def _run(incident_id: str) -> TriageResult:
    s = Settings.from_env()
    llm = get_llm(s.llm, s.model)
    async with get_mcp_client(s.backend) as mcp:
        return await triage(incident_id, mcp, llm, max_turns=s.max_turns)


def main() -> None:
    force_utf8_stdout()
    setup_trace(trace_level(sys.argv[1:]))
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    incident_id = positional[0] if positional else "INC-1001"
    print(_render(asyncio.run(_run(incident_id))))


if __name__ == "__main__":
    main()
