"""Judge parsing + harness aggregation, fully offline (scripted FakeLLM/FakeMCP)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from datadog_triage_agent.evals.harness import run_cases
from datadog_triage_agent.evals.judge import JudgeError, judge
from datadog_triage_agent.models import LLMMessage, ToolSpec, TriageResult


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> str:
        return self.responses.pop(0)


class FakeMCP:
    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        return {"id": incident_id}


def _result(iid: str) -> TriageResult:
    return TriageResult(
        incident_id=iid,
        root_cause="upstream timeout cascade",
        confidence="high",
        evidence=[{"source": "logs", "detail": "504"}],
        reproduction_steps=["call the endpoint while upstream stalls"],
        candidate_fix="bound the timeout",
    )


def _final(iid: str) -> str:
    return json.dumps({"action": "final", "result": _result(iid).model_dump()})


def _verdict(rc: int = 2, repro: int = 2, grnd: int = 2) -> str:
    return json.dumps(
        {"scores": {"root_cause": rc, "reproduction": repro, "grounding": grnd}, "justification": "ok"}
    )


def test_judge_parses_scores_and_totals() -> None:
    llm = FakeLLM([_verdict(2, 1, 2)])
    v = judge(llm, {"id": "INC-1001"}, {"root_cause": "x"}, _result("INC-1001"))
    assert v["scores"] == {"root_cause": 2, "reproduction": 1, "grounding": 2}
    assert v["total"] == 5 and v["max"] == 6


def test_judge_rejects_out_of_range_score() -> None:
    bad = json.dumps({"scores": {"root_cause": 5, "reproduction": 1, "grounding": 0}})
    with pytest.raises(JudgeError):
        judge(FakeLLM([bad]), {}, {}, _result("INC-1001"))


def test_judge_rejects_non_json() -> None:
    with pytest.raises(JudgeError):
        judge(FakeLLM(["sorry, no json"]), {}, {}, _result("INC-1001"))


def test_run_cases_aggregates_over_real_fixtures() -> None:
    ids = ["INC-1001", "INC-1002"]
    agent_llm = FakeLLM([_final(i) for i in ids])
    judge_llm = FakeLLM([_verdict(2, 2, 2), _verdict(1, 1, 0)])
    report = asyncio.run(run_cases(ids, FakeMCP(), agent_llm, judge_llm, max_turns=3))

    assert [c["incident_id"] for c in report["cases"]] == ids
    assert all("error" not in c for c in report["cases"])
    agg = report["aggregate"]
    assert agg["n"] == 2
    assert agg["total_mean"] == 4.0  # (6 + 2) / 2
    assert agg["by_dimension"]["grounding"] == 1.0  # (2 + 0) / 2
