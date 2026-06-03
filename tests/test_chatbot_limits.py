"""Tests for chatbot tool guards — per-turn call budget and per-tool timeout.
Mocked: exercises the _guarded decorator directly, no LLM / network."""

import time

from analyzer.chatbot.tools import _guarded, reset_tool_budget


def test_call_budget_caps_repeated_calls():
    reset_tool_budget()

    @_guarded(max_calls=1)
    def expensive():
        return "ran"

    assert expensive() == "ran"
    second = expensive()
    assert "already used" in second  # capped, body not run again


def test_reset_clears_budget_between_turns():
    @_guarded(max_calls=1)
    def expensive():
        return "ran"

    reset_tool_budget()
    assert expensive() == "ran"
    assert "already used" in expensive()
    # New turn → budget refreshed, tool callable again.
    reset_tool_budget()
    assert expensive() == "ran"


def test_timeout_returns_graceful_message():
    reset_tool_budget()

    @_guarded(timeout=0.2)
    def hangs():
        time.sleep(2)
        return "done"

    out = hangs()
    assert "timed out" in out


def test_unbudgeted_tool_runs_every_time():
    reset_tool_budget()

    @_guarded()  # no max_calls
    def cheap():
        return "ok"

    assert cheap() == "ok"
    assert cheap() == "ok"
    assert cheap() == "ok"


def test_recursion_limit_is_configured():
    from analyzer.chatbot import agent

    assert agent._RECURSION_LIMIT >= 2
