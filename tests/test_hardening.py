"""Regression tests for the hardening pass — model routing, the Qdrant store
failsafe, and Rust/Python classifier parity. All mocked; no vLLM/Qdrant/Kafka."""

import importlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── Model routing (analyzer/llm.py) ─────────────────────────────────────────────


def test_get_llm_defaults_to_big():
    os.environ.pop("DRAFT_LLM_URL", None)
    import analyzer.llm as L

    importlib.reload(L)
    assert "7B" in L.get_llm(model="big").model_name


def test_get_llm_small_falls_back_to_big_without_draft_url():
    os.environ.pop("DRAFT_LLM_URL", None)
    import analyzer.llm as L

    importlib.reload(L)
    # No draft endpoint configured → "small" must not break, just use the big model.
    assert "7B" in L.get_llm(model="small").model_name


def test_get_llm_small_routes_to_draft_when_configured():
    os.environ["DRAFT_LLM_URL"] = "http://localhost:8001"
    import analyzer.llm as L

    importlib.reload(L)
    try:
        assert "1.5B" in L.get_llm(model="small").model_name
        # The per-request ContextVar should drive selection too.
        tok = L.set_target_model("small")
        try:
            assert "1.5B" in L.get_llm().model_name
        finally:
            L.reset_target_model(tok)
        assert "7B" in L.get_llm().model_name
    finally:
        os.environ.pop("DRAFT_LLM_URL", None)
        importlib.reload(L)


# ── Local store buffer (analyzer/pipeline/store_buffer.py) ───────────────────────


class _FakeAnalysis:
    """Stands in for FeedbackAnalysis — only model_dump_json is exercised."""

    def __init__(self, n):
        self.n = n

    def model_dump_json(self):
        return json.dumps({"n": self.n})


def test_store_buffer_buffers_while_down_and_flushes_on_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BUFFER_PATH", str(tmp_path / "buf.jsonl"))
    import analyzer.pipeline.store_buffer as sb

    importlib.reload(sb)

    for i in range(3):
        sb.buffer_failed_store(f"id{i}", f"text{i}", _FakeAnalysis(i), "csv")
    assert sb.pending_count() == 3

    # Patch deserialize + the Qdrant store. First: Qdrant down → nothing flushes.
    import analyzer.schemas as S

    monkeypatch.setattr(S.FeedbackAnalysis, "model_validate_json", staticmethod(json.loads), raising=False)
    import vectordb.store as VS

    monkeypatch.setattr(VS, "store_analysis", lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert sb.flush_store_buffer() == 0
    assert sb.pending_count() == 3

    # Qdrant back → all flush and the file is removed.
    calls = []
    monkeypatch.setattr(VS, "store_analysis", lambda **k: calls.append(k["feedback_id"]))
    assert sb.flush_store_buffer() == 3
    assert sb.pending_count() == 0
    assert len(calls) == 3


# ── Kafka store-retry lane (analyzer/store_retry.py) ─────────────────────────────


def test_store_retry_is_noop_without_kafka(monkeypatch):
    monkeypatch.delenv("KAFKA_BROKERS", raising=False)
    import analyzer.store_retry as R

    importlib.reload(R)
    assert R._kafka_enabled() is False
    assert R.start_retry_consumer() is False
    assert R.publish_store_retry("id", "txt", _FakeAnalysis(1), "csv") is False


# ── Classifier parity: Rust producer must match Python cascade ──────────────────


def _rust_complex_signals() -> set[str]:
    src = (REPO / "kafka_queue/src/bin/producer.rs").read_text()
    m = re.search(r"COMPLEX_SIGNALS:\s*&\[&str\]\s*=\s*&\[(.*?)\];", src, re.S)
    assert m, "COMPLEX_SIGNALS array not found in producer.rs"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


@pytest.mark.skipif(
    not (REPO / "kafka_queue/src/bin/producer.rs").exists(),
    reason="Rust gateway source not present",
)
def test_classifier_keyword_parity():
    from analyzer.chatbot.cascade_llm import _COMPLEX_SIGNALS

    rust = _rust_complex_signals()
    # Two sources of truth across a language boundary — keep them identical or the
    # producer and chatbot will route the same query to different models.
    assert rust == set(_COMPLEX_SIGNALS), (
        f"Rust∖Py={rust - set(_COMPLEX_SIGNALS)}  Py∖Rust={set(_COMPLEX_SIGNALS) - rust}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
