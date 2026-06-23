"""The JSON action extractor: tolerates fences and stray prose, rejects junk."""

from __future__ import annotations

from datadog_triage_agent.agent import parse_action


def test_plain_json() -> None:
    a = parse_action('{"action": "final", "result": {"x": 1}}')
    assert a is not None and a["action"] == "final"


def test_fenced_json() -> None:
    text = '```json\n{"action": "call_tool", "tool": "search_logs", "arguments": {"query": "x"}}\n```'
    a = parse_action(text)
    assert a is not None and a["tool"] == "search_logs"


def test_prose_around_json() -> None:
    text = 'Sure, next step:\n{"action": "call_tool", "tool": "get_incident", "arguments": {}}\nThanks!'
    a = parse_action(text)
    assert a is not None and a["action"] == "call_tool"


def test_garbage_returns_none() -> None:
    assert parse_action("no json today, friend") is None


def test_non_action_dict_returns_none() -> None:
    assert parse_action('{"foo": "bar"}') is None


def test_broken_json_returns_none() -> None:
    assert parse_action('{"action": "final", "result": ') is None
