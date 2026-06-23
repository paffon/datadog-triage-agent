"""Settings + shared paths. Reads env once (`.env` loaded if present, real env wins)
so the demo/eval have a single source of truth for the TRIAGE_* knobs.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op if there's no .env; real environment variables take precedence

TRACE = 5  # custom log level below DEBUG: raw LLM transport (level-3 trace)


def force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; LLM output routinely contains unicode
    (arrows, smart quotes), so printing the result would crash. Make stdout UTF-8."""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")


def trace_level(argv: list[str]) -> int:
    """Verbosity level (0-3) from CLI flags + env. `-v`/`-vv`/`-vvv` (or repeated
    `--verbose`) count up; `TRIAGE_TRACE` is honored too and the higher wins."""
    level = sum(
        (len(a) - 1) if (len(a) > 1 and a[0] == "-" and set(a[1:]) == {"v"})
        else (1 if a == "--verbose" else 0)
        for a in argv
    )
    env = os.getenv("TRIAGE_TRACE")
    if env and env.isdigit():
        level = max(level, int(env))
    return min(level, 3)


def setup_trace(level: int) -> None:
    """Route the `triage.*` loggers to stderr at the level's threshold. Only the
    `triage` tree is turned up, so third-party libs (httpx/anthropic) stay quiet."""
    if level <= 0:
        return
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")  # same cp1252 reason as force_utf8_stdout
    logging.basicConfig(stream=sys.stderr, format="%(message)s")
    logging.getLogger("triage").setLevel({1: logging.INFO, 2: logging.DEBUG, 3: TRACE}[level])


@dataclass(frozen=True)
class Settings:
    backend: str = "mock"       # mock | datadog
    llm: str = "cli"            # cli | anthropic
    model: str = "haiku"        # agent model
    judge_model: str = "sonnet"  # eval judge model
    max_turns: int = 6

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            backend=os.getenv("TRIAGE_BACKEND", "mock"),
            llm=os.getenv("TRIAGE_LLM", "cli"),
            model=os.getenv("TRIAGE_MODEL", "haiku"),
            judge_model=os.getenv("TRIAGE_JUDGE_MODEL", "sonnet"),
            max_turns=int(os.getenv("TRIAGE_MAX_TURNS", "6")),
        )


def fixtures_dir() -> Path:
    """Where the ground-truth fixtures live. The judge/harness read these directly
    (the mock *server* has its own copy of this lookup — it runs as a subprocess)."""
    override = os.getenv("TRIAGE_FIXTURES_DIR")
    if override:
        return Path(override)
    # config.py -> datadog_triage_agent -> src -> repo root
    return Path(__file__).resolve().parents[2] / "fixtures"
