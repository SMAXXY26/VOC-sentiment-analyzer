"""Tests for the research-facing metrics — token extraction + calls-saved bookkeeping.
Mocked: no LLM / network (the live token capture is verified separately)."""

from types import SimpleNamespace

from analyzer.llm import _UsageCallback


def test_extracts_tokens_from_openai_llm_output():
    resp = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 120, "completion_tokens": 30}},
        generations=[],
    )
    assert _UsageCallback._extract_tokens(resp) == (120, 30)


def test_extracts_tokens_from_usage_metadata_fallback():
    msg = SimpleNamespace(usage_metadata={"input_tokens": 50, "output_tokens": 12})
    gen = SimpleNamespace(message=msg)
    resp = SimpleNamespace(llm_output=None, generations=[[gen]])
    assert _UsageCallback._extract_tokens(resp) == (50, 12)


def test_extract_tokens_is_zero_when_absent():
    resp = SimpleNamespace(llm_output={}, generations=[])
    assert _UsageCallback._extract_tokens(resp) == (0, 0)


def test_calls_saved_increments_by_llm_stage_count():
    from analyzer.metrics import LLM_CALLS_SAVED_TOTAL, LLM_STAGES

    def total():
        return next(
            s.value for m in LLM_CALLS_SAVED_TOTAL.collect() for s in m.samples if s.name == "llm_calls_saved_total"
        )

    before = total()
    LLM_CALLS_SAVED_TOTAL.inc(LLM_STAGES)
    assert total() - before == LLM_STAGES
