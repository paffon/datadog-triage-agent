"""Tiny ANSI color helper for the demo/eval/trace output. Stdlib only.

Color is gated on a real TTY (honoring the NO_COLOR / FORCE_COLOR conventions), so
redirected or piped output stays clean — `eval > out.txt` has no escape codes in it.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

_STYLES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "gray": "90",
}
_RESET = "\033[0m"


def _enable_windows_vt() -> None:
    """Turn on ANSI VT processing on the Windows console. No-op elsewhere, on older
    Windows without the API, or when the handles are redirected."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return
        kernel32 = windll.kernel32
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
    except Exception:
        pass  # color is cosmetic — never let enabling it break a run


_enable_windows_vt()


def supports_color(stream: TextIO) -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, *styles: str, enabled: bool = True) -> str:
    """Wrap `text` in the given ANSI styles. Returns it unchanged if color is off."""
    if not enabled or not styles:
        return text
    codes = ";".join(_STYLES[s] for s in styles)
    return f"\033[{codes}m{text}{_RESET}"


class TraceFormatter(logging.Formatter):
    """Colorize trace lines by their leading glyph (turn headers, tool calls,
    observations, finals). Emits plain text when color is disabled."""

    def __init__(self, enabled: bool) -> None:
        super().__init__("%(message)s")
        self.enabled = enabled

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        styles = _trace_styles(msg) if self.enabled else ()
        return paint(msg, *styles) if styles else msg


def _trace_styles(msg: str) -> tuple[str, ...]:
    s = msg.lstrip()
    if s.startswith("══") or s.startswith("── turn"):
        return ("bold", "cyan")  # incident / turn header
    if s.startswith("→"):
        return ("yellow",)  # tool call
    if s.startswith("←"):
        return ("gray",)  # tool observation
    if s.startswith("✓"):
        return ("bold", "green")  # final result
    if s.startswith(("·", "assistant:")):
        return ("dim",)  # loop notes / raw replies
    return ()
