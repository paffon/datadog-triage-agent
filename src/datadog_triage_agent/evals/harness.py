"""Eval harness: run the agent over every ground-truth incident, judge each result,
print a scoreboard, and save JSON to eval_results/ (gitignored).

`run_cases` is the testable core (inject your own llm/mcp). `main` wires it from env.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent import triage
from ..config import Settings, fixtures_dir, force_utf8_stdout, setup_trace, trace_level
from ..llm import get_llm
from ..llm.base import LLMClient
from ..mcp_backends import get_mcp_client
from .judge import judge
from .rubric import DIMENSIONS, MAX_PER_DIM

MAX_TOTAL = len(DIMENSIONS) * MAX_PER_DIM

log = logging.getLogger("triage.harness")  # info = trace level 1


def discover_incident_ids() -> list[str]:
    return sorted(p.stem for p in (fixtures_dir() / "incidents").glob("*.json"))


def _load_fixture(incident_id: str) -> dict[str, Any]:
    path = fixtures_dir() / "incidents" / f"{incident_id}.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def run_cases(
    incident_ids: list[str],
    mcp: Any,
    agent_llm: LLMClient,
    judge_llm: LLMClient,
    max_turns: int = 6,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for iid in incident_ids:
        log.info("══ %s ══", iid)
        try:
            fixture = _load_fixture(iid)
            ground_truth = fixture["ground_truth"]
            observable = {k: v for k, v in fixture.items() if k != "ground_truth"}
            result = await triage(iid, mcp, agent_llm, max_turns=max_turns)
            verdict = judge(judge_llm, observable, ground_truth, result)
            cases.append({
                "incident_id": iid,
                "confidence": result.confidence,
                "scores": verdict["scores"],
                "total": verdict["total"],
                "justification": verdict["justification"],
                "result": result.model_dump(),
            })
        except Exception as e:  # one bad case shouldn't sink the whole scoreboard
            cases.append({
                "incident_id": iid,
                "error": f"{type(e).__name__}: {e}",
                "scores": {d: 0 for d in DIMENSIONS},
                "total": 0,
            })
    return {"cases": cases, "aggregate": _aggregate(cases)}


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(cases)
    if n == 0:
        return {"n": 0}
    by_dim = {d: round(sum(c["scores"][d] for c in cases) / n, 2) for d in DIMENSIONS}
    return {
        "n": n,
        "by_dimension": by_dim,
        "total_mean": round(sum(c["total"] for c in cases) / n, 2),
        "max_total": MAX_TOTAL,
    }


def _print_scoreboard(report: dict[str, Any]) -> None:
    print(f"\n{'incident':<12} {'rc':>3} {'repro':>6} {'grnd':>5} {'total':>7}  note")
    print("-" * 60)
    for c in report["cases"]:
        s = c["scores"]
        note = c.get("error") or c.get("confidence") or ""
        print(
            f"{c['incident_id']:<12} {s['root_cause']:>3} {s['reproduction']:>6} "
            f"{s['grounding']:>5} {c['total']:>4}/{MAX_TOTAL}  {note}"
        )
    agg = report["aggregate"]
    print("-" * 60)
    print(
        f"means: root_cause={agg['by_dimension']['root_cause']} "
        f"reproduction={agg['by_dimension']['reproduction']} "
        f"grounding={agg['by_dimension']['grounding']}  "
        f"total={agg['total_mean']}/{agg['max_total']} over {agg['n']} incidents\n"
    )


def _save(report: dict[str, Any]) -> Path:
    out_dir = Path("eval_results")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    stamped = out_dir / f"{stamp}.json"
    stamped.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return stamped


def main() -> None:
    force_utf8_stdout()
    setup_trace(trace_level(sys.argv[1:]))
    s = Settings.from_env()
    ids = discover_incident_ids()

    async def _go() -> dict[str, Any]:
        async with get_mcp_client(s.backend) as mcp:
            return await run_cases(
                ids, mcp, get_llm(s.llm, s.model), get_llm(s.llm, s.judge_model), s.max_turns
            )

    report = asyncio.run(_go())
    _print_scoreboard(report)
    saved = _save(report)
    print(f"saved {saved}")


if __name__ == "__main__":
    main()
