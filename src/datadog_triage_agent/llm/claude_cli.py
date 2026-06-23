"""Default LLM provider: the `claude -p` CLI, driven as a pure text engine.

Uses the user's Claude Code subscription (no API key). Built-in tools are
disabled (`--tools ""`) so the model only follows our in-prompt JSON protocol.
Flag spellings verified against CLI v2.1.47 — see docs/LESSONS.md.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from ..models import LLMMessage, ToolSpec
from .base import LLMError

# `claude -p` refuses to launch from inside a Claude Code session (these are set);
# scrubbing them lets the demo/eval run when invoked under CC. See LESSONS.
_SCRUB_ENV = ("CLAUDECODE", "CLAUDE_CODE_SSE_PORT")


def _render_tools(tools: list[ToolSpec]) -> str:
    lines = ["Available tools:"]
    for t in tools:
        lines.append(f"- {t.name}: {t.description}")
        for arg, desc in t.parameters.items():
            lines.append(f"    - {arg}: {desc}")
    return "\n".join(lines)


@dataclass
class ClaudeCLI:
    model: str = "haiku"
    binary: str = "claude"
    timeout: float = 120.0

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str:
        system_parts = [m.content for m in messages if m.role == "system"]
        if tools:
            system_parts.append(_render_tools(tools))
        system = "\n\n".join(system_parts)
        transcript = "\n\n".join(
            f"[{m.role}]\n{m.content}" for m in messages if m.role != "system"
        )

        cmd = [
            self.binary, "-p", transcript,
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",               # pure text engine: no built-in tools
            "--strict-mcp-config",       # ignore the cwd's MCP servers (else it hangs loading them)
            "--setting-sources", "",     # skip project/local settings -> no hooks, faster, deterministic
            "--no-session-persistence",  # don't write a session file per call
        ]
        if system:
            cmd += ["--append-system-prompt", system]

        env = {k: v for k, v in os.environ.items() if k not in _SCRUB_ENV}

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                stdin=subprocess.DEVNULL,  # don't block reading inherited stdin
                timeout=self.timeout, env=env,
            )
        except FileNotFoundError as e:
            raise LLMError(f"`{self.binary}` not found on PATH") from e
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"`claude -p` timed out after {self.timeout}s") from e

        if proc.returncode != 0:
            raise LLMError(f"`claude -p` exited {proc.returncode}: {proc.stderr.strip()}")

        try:
            obj = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"`claude -p` returned non-JSON: {proc.stdout[:200]!r}") from e

        if obj.get("is_error"):
            raise LLMError(f"`claude -p` reported an error: {obj.get('result')!r}")
        result = obj.get("result")
        if not isinstance(result, str):
            raise LLMError(f"`claude -p` response had no 'result' string: {obj!r}")
        return result
