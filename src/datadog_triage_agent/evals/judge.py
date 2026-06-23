"""LLM-as-judge: score one triage result against ground truth."""

from __future__ import annotations

import json
from typing import Any

from ..llm.base import LLMClient
from ..models import LLMMessage, TriageResult
from .rubric import DIMENSIONS, JUDGE_PROMPT, MAX_PER_DIM


class JudgeError(RuntimeError):
    """The judge did not return a usable, schema-valid verdict."""


def judge(
    llm: LLMClient,
    incident: dict[str, Any],       # observable incident (ground_truth already stripped)
    ground_truth: dict[str, Any],
    result: TriageResult,
) -> dict[str, Any]:
    payload = {
        "incident": incident,
        "ground_truth": ground_truth,
        "agent_result": result.model_dump(),
    }
    messages = [
        LLMMessage(role="system", content=JUDGE_PROMPT),
        LLMMessage(role="user", content=json.dumps(payload, indent=2)),
    ]
    obj = _extract_obj(llm.complete(messages, []))
    if obj is None:
        raise JudgeError("judge did not return a JSON object")
    scores = _validate_scores(obj.get("scores"))
    return {
        "scores": scores,
        "total": sum(scores.values()),
        "max": len(DIMENSIONS) * MAX_PER_DIM,
        "justification": str(obj.get("justification", "")),
    }


def _extract_obj(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _validate_scores(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise JudgeError(f"missing 'scores' object, got {raw!r}")
    scores: dict[str, int] = {}
    for dim in DIMENSIONS:
        v = raw.get(dim)
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= MAX_PER_DIM:
            raise JudgeError(f"score for {dim!r} must be an int 0..{MAX_PER_DIM}, got {v!r}")
        scores[dim] = v
    return scores
