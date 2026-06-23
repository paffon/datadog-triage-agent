"""The judge rubric and prompt — kept here, separate from the call logic, so the
scoring criteria are easy to read and tweak."""

from __future__ import annotations

DIMENSIONS = ("root_cause", "reproduction", "grounding")
MAX_PER_DIM = 2

RUBRIC = """Score each dimension as 0, 1, or 2.

root_cause - does the agent's root cause match the ground-truth root cause?
  0 = wrong or missing
  1 = partially right (right symptom, but wrong or incomplete underlying cause)
  2 = correctly identifies the true (often upstream) cause

reproduction - are the reproduction steps concrete and actionable?
  0 = absent or useless
  1 = vague but on the right track
  2 = specific, ordered steps someone could actually follow to reproduce

grounding - is every claim backed by evidence the agent retrieved, matching the
ground-truth key evidence (no fabrication)?
  0 = invented or unsupported
  1 = partially grounded
  2 = well grounded in the real logs/traces, no fabrication"""

JUDGE_PROMPT = f"""You are a strict grader for an incident-triage agent. You are given the
observable incident, the private ground truth, and the agent's triage result. Grade the
agent's result against the ground truth using this rubric.

{RUBRIC}

Respond with EXACTLY ONE JSON object and nothing else - no prose, no markdown fences:
{{"scores": {{"root_cause": 0, "reproduction": 0, "grounding": 0}},
"justification": "<2-3 sentences. If the agent missed something, 
be explicit on whether it didn't call the right tool with the right parameters, 
or it called the right tool but misinterpreted the evidence.>"}}
"""
