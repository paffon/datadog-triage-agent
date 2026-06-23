"""Offline checks for the Anthropic SDK provider's request builder + model map.

The `anthropic` package isn't installed in the default env; `complete()` imports
it lazily, so `_request` and `_MODEL_IDS` are importable and testable without it.
"""

from __future__ import annotations

from datadog_triage_agent.llm.anthropic_sdk import _MODEL_IDS, AnthropicSDK
from datadog_triage_agent.models import LLMMessage, ToolSpec


def test_request_splits_system_and_renders_tools() -> None:
    messages = [
        LLMMessage(role="system", content="You are a triage agent."),
        LLMMessage(role="user", content="Triage INC-1001."),
        LLMMessage(role="assistant", content='{"action": "call_tool"}'),
    ]
    tools = [ToolSpec(name="get_incident", description="Fetch incident detail.")]

    system, convo = AnthropicSDK()._request(messages, tools)

    assert "You are a triage agent." in system
    assert "get_incident" in system  # tool catalog rendered into the system prompt
    assert convo == [
        {"role": "user", "content": "Triage INC-1001."},
        {"role": "assistant", "content": '{"action": "call_tool"}'},
    ]


def test_model_aliases_map_to_real_ids() -> None:
    # Bare aliases must resolve to full IDs or the SDK 404s; pin them.
    assert _MODEL_IDS["haiku"] == "claude-haiku-4-5"
    assert _MODEL_IDS["sonnet"] == "claude-sonnet-4-6"
    assert _MODEL_IDS["opus"] == "claude-opus-4-8"
