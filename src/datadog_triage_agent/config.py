"""Settings + shared paths. Reads env once (`.env` loaded if present, real env wins)
so the demo/eval have a single source of truth for the TRIAGE_* knobs.
"""

from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op if there's no .env; real environment variables take precedence


def force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; LLM output routinely contains unicode
    (arrows, smart quotes), so printing the result would crash. Make stdout UTF-8."""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")


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
