"""Fault-injection tests — verify the system degrades gracefully (or fails loudly in
the right place) when dependencies break. All mocked; no vLLM / Qdrant / Kafka needed.

Covers the recovery paths documented in the README "Failure Recovery Matrix":
  - Qdrant down during dedup        → analysis still runs (dedup is best-effort)
  - Qdrant down during store        → Kafka retry topic, then local buffer fallback
  - Qdrant back up                  → buffered writes are replayed
  - LLM/vLLM stage failure          → propagates so the consumer can retry → DLT
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from test_pipeline import DUMMY_TEXT, _mock_llm_output  # noqa: E402

from analyzer.pipeline.normalization import normalization_stage  # noqa: E402
from analyzer.pipeline.pii_redaction import pii_redaction_stage  # noqa: E402
from analyzer.schemas import (  # noqa: E402
    BusinessSignals,
    ExecutiveIntelligence,
    RiskEscalation,
    SemanticEnrichment,
    SentimentEmotion,
    TaxonomyClassification,
)


def _full_ctx(text: str = DUMMY_TEXT) -> dict:
    """A complete pipeline context (real normalize+pii, mocked LLM outputs)."""
    ctx = pii_redaction_stage.invoke(normalization_stage.invoke({"raw_text": text, "feedback_id": "fault-test-1"}))
    ctx["enrichment"] = _mock_llm_output(SemanticEnrichment)
    ctx["taxonomy"] = _mock_llm_output(TaxonomyClassification)
    ctx["sentiment"] = _mock_llm_output(SentimentEmotion)
    ctx["signals"] = _mock_llm_output(BusinessSignals)
    ctx["risk"] = _mock_llm_output(RiskEscalation)
    ctx["executive"] = _mock_llm_output(ExecutiveIntelligence)
    ctx["source"] = "test"
    return ctx


# ── Qdrant down during dedup ────────────────────────────────────────────────────


def test_analysis_survives_qdrant_down_during_dedup():
    """find_duplicates blowing up (Qdrant unreachable) must not break analyze_single."""
    import analyzer.main as main

    def boom(*a, **k):
        raise ConnectionError("qdrant unreachable")

    with patch("analyzer.main.pipeline") as mock_pipeline, patch("vectordb.store.find_duplicates", boom):
        mock_pipeline.invoke.side_effect = lambda ctx: _full_ctx(ctx["raw_text"])
        result = main.analyze_single("the food was cold and the waiter was rude")

    assert result.taxonomy.category  # a full analysis came back despite Qdrant being down


# ── Qdrant down during store → retry topic, then buffer ─────────────────────────


def test_store_failure_routes_to_kafka_retry_then_buffer():
    from analyzer.pipeline import store_result as sr

    calls = {"retry": 0, "buffer": 0}

    def store_down(**k):
        raise ConnectionError("qdrant down")

    # Kafka retry unavailable too → must fall back to the local buffer (nothing lost).
    with (
        patch("vectordb.store.store_analysis", store_down),
        patch(
            "analyzer.store_retry.publish_store_retry",
            lambda *a, **k: (calls.__setitem__("retry", calls["retry"] + 1), False)[1],
        ),
        patch(
            "analyzer.pipeline.store_buffer.buffer_failed_store",
            lambda *a, **k: calls.__setitem__("buffer", calls["buffer"] + 1),
        ),
    ):
        out = sr.store_result_stage.invoke(_full_ctx())

    assert out is not None  # pipeline stage never raises
    assert calls["retry"] == 1  # tried the durable Kafka retry first
    assert calls["buffer"] == 1  # then fell back to the local buffer


def test_store_failure_uses_kafka_retry_when_available():
    from analyzer.pipeline import store_result as sr

    calls = {"retry": 0, "buffer": 0}

    def store_down(**k):
        raise ConnectionError("qdrant down")

    # Kafka retry succeeds → the local buffer must NOT be used.
    with (
        patch("vectordb.store.store_analysis", store_down),
        patch(
            "analyzer.store_retry.publish_store_retry",
            lambda *a, **k: (calls.__setitem__("retry", calls["retry"] + 1), True)[1],
        ),
        patch(
            "analyzer.pipeline.store_buffer.buffer_failed_store",
            lambda *a, **k: calls.__setitem__("buffer", calls["buffer"] + 1),
        ),
    ):
        sr.store_result_stage.invoke(_full_ctx())

    assert calls["retry"] == 1
    assert calls["buffer"] == 0


# ── Qdrant recovery → buffered writes replayed ──────────────────────────────────


def test_successful_store_flushes_the_retry_buffer():
    from analyzer.pipeline import store_result as sr

    flushed = {"n": 0}
    with (
        patch("vectordb.store.store_analysis", lambda **k: None),
        patch("analyzer.pipeline.store_buffer.flush_store_buffer", lambda: flushed.__setitem__("n", flushed["n"] + 1)),
    ):
        sr.store_result_stage.invoke(_full_ctx())

    assert flushed["n"] == 1  # a healthy store opportunistically drains the backlog


# ── LLM / vLLM failure propagates (so the consumer can DLT) ─────────────────────


def test_llm_stage_failure_propagates():
    """If an LLM stage fails, analyze_single must raise — that's how the Kafka consumer
    learns to retry and ultimately dead-letter, rather than silently storing garbage."""
    import analyzer.main as main

    def boom(ctx):
        raise RuntimeError("vLLM connection refused")

    with patch("analyzer.main.pipeline") as mock_pipeline, patch("vectordb.store.find_duplicates", lambda *a, **k: []):
        mock_pipeline.invoke.side_effect = boom
        try:
            main.analyze_single("anything")
            raised = False
        except RuntimeError:
            raised = True

    assert raised, "LLM failure must propagate to the caller (consumer → retry → DLT)"
