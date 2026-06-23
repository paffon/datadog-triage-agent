"""Default LLM provider: the `claude -p` CLI, driven as a pure text engine.

Authenticates via the local Claude Code CLI login (no API key needed). Built-in
tools are disabled (`--tools ""`) so the model only follows our in-prompt JSON
protocol. Flag spellings verified against CLI v2.1.47 — see docs/DECISIONS.md.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass

from ..config import TRACE
from ..models import LLMMessage, ToolSpec
from .base import LLMError

log = logging.getLogger("triage.llm")  # TRACE = level 3: raw transport

# `claude -p` refuses to launch from inside a Claude Code session (these are set);
# scrubbing them lets the demo/eval run when invoked under CC. See docs/DECISIONS.md.
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

    def _random_wording(self) -> str:
        wording_options = [
            "And then {} said: {}",
            "Then the {} remarked: {}",
            "So then {} stated: {}",
            "After that, {} chimed in: {}",
            "Next, {} added: {}",
            "Following that, {} declared: {}",
            "In return, {} responded: {}",
        ]

        random_index = os.urandom(1)[0] % len(wording_options)
        return wording_options[random_index]

    # Per-call wording variation: each message is framed as narrative prose with a
    # randomly chosen connective. This is a deliberate U-turn on the earlier
    # "deterministic, no gratuitous noise" transcript design — empirically it cuts
    # the agent's hallucination rate, the result of many trials. The cost is lost
    # prompt-cache hits (identical turns no longer render identically). See DECISIONS.md.
    def _construct_transcript(self, messages: list[LLMMessage]) -> str:
        transcript = "\n\n".join(
            self._random_wording().format(m.role, m.content)
            for m in messages
            if m.role != "system"
        )
        end_with = (
            "Now write only the next assistant message: a single JSON object and nothing else — "
            'either {"action":"call_tool",...} to gather more evidence, or {"action":"final",...} '
            "if the evidence already points to a root cause. Don't keep investigating once the answer is clear."
        )
        return transcript + "\n\n" + end_with

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str:
        system_parts = [m.content for m in messages if m.role == "system"]
        if tools:
            system_parts.append(_render_tools(tools))
        system = "\n\n".join(system_parts)

        transcript = self._construct_transcript(messages)

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

        log.log(TRACE, "claude -p argv: %s", cmd)
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

        log.log(TRACE, "claude -p stdout: %s", proc.stdout)

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
