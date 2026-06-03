"""Tests for model-tier routing precedence (analyzer/routing.py).
Mocked: the LLM router call is monkeypatched, so no vLLM is needed."""

import analyzer.routing as R


def test_off_mode_honours_hint(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "off")
    assert R.resolve_model_tier("anything", hint="small") == "small"
    assert R.resolve_model_tier("anything", hint="big") == "big"
    assert R.resolve_model_tier("anything", hint=None) == "big"


def test_keyword_mode_prefers_hint(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "keyword")
    # Hint present → used directly, no classification.
    assert R.resolve_model_tier("I want a refund", hint="small") == "small"


def test_keyword_mode_without_hint_classifies(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "keyword")
    # "refund" is a complex signal → big; a plain greeting → small.
    assert R.resolve_model_tier("I want a refund now", hint=None) == "big"
    assert R.resolve_model_tier("hello there", hint=None) == "small"


def test_model_mode_uses_model_decision(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "model")
    monkeypatch.setattr(R, "_route_with_model", lambda _t: "big")
    # Model overrides even a "small" hint — the model is authoritative.
    assert R.resolve_model_tier("I'm fine, just want to cancel", hint="small") == "big"


def test_model_mode_falls_back_when_model_unavailable(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER", "model")
    monkeypatch.setattr(R, "_route_with_model", lambda _t: None)
    # Model returned nothing → fall back to the hint, then to keywords.
    assert R.resolve_model_tier("whatever", hint="big") == "big"
    assert R.resolve_model_tier("I want a refund now", hint=None) == "big"
