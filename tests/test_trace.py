"""The only non-trivial bit of the trace feature is parsing the verbosity level
from argv + env. Pin it here; the logging seams themselves are just emit calls."""

from __future__ import annotations

import logging

import pytest

from datadog_triage_agent.config import setup_trace, trace_level


def test_trace_level_from_flags() -> None:
    assert trace_level([]) == 0
    assert trace_level(["-v"]) == 1
    assert trace_level(["-vv"]) == 2
    assert trace_level(["-vvv"]) == 3
    assert trace_level(["-v", "-v"]) == 2
    assert trace_level(["--verbose"]) == 1
    assert trace_level(["INC-1003", "-v"]) == 1  # positional id is not a flag
    assert trace_level(["-vvvv"]) == 3  # capped at 3


def test_trace_level_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_TRACE", "2")
    assert trace_level([]) == 2
    assert trace_level(["-vvv"]) == 3  # the higher of flag vs env wins


def test_setup_trace_sets_logger_level() -> None:
    triage = logging.getLogger("triage")
    try:
        setup_trace(2)
        assert triage.level == logging.DEBUG
    finally:
        triage.setLevel(logging.NOTSET)  # don't leak state into other tests
