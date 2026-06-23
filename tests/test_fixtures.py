"""Validate every fixture parses into its model and each incident carries a
well-formed ground_truth (the eval is meaningless without it). Offline."""

from __future__ import annotations

import json
from pathlib import Path

from datadog_triage_agent.models import Incident, LogEntry, Trace

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
GT_KEYS = {"root_cause", "key_evidence", "expected_fix_themes"}


def test_incidents_parse_and_have_ground_truth() -> None:
    incident_files = sorted((FIXTURES / "incidents").glob("*.json"))
    assert len(incident_files) >= 6, "expected the 6 planned incidents"
    for path in incident_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        gt = raw.pop("ground_truth", None)
        assert isinstance(gt, dict) and GT_KEYS <= gt.keys(), f"{path.name} bad ground_truth"
        assert gt["key_evidence"] and gt["expected_fix_themes"], f"{path.name} empty gt lists"
        incident = Incident.model_validate(raw)
        assert incident.id == path.stem


def test_logs_and_traces_parse() -> None:
    for path in sorted((FIXTURES / "logs").glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert rows, f"{path.name} is empty"
        [LogEntry.model_validate(r) for r in rows]
    for path in sorted((FIXTURES / "traces").glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert rows, f"{path.name} is empty"
        [Trace.model_validate(r) for r in rows]
