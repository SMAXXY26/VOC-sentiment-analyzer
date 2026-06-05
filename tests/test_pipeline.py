"""
Pipeline tests — two modes:
  1. Mocked LLM  : validates all schema/logic wiring without needing vLLM running
  2. Live LLM    : runs the real pipeline end-to-end (requires vLLM on localhost:8000)

Run mocked:
    python -m pytest tests/test_pipeline.py -v

Run live (needs vLLM):
    python -m pytest tests/test_pipeline.py -v -m live
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import MagicMock, patch

import pytest

from analyzer.pipeline.normalization import normalization_stage
from analyzer.pipeline.pii_redaction import pii_redaction_stage
from analyzer.schemas import (
    BusinessSignals,
    CustomerExperienceIndex,
    CustomerSatisfactionIndex,
    ExecutiveIntelligence,
    ExperienceScores,
    FeedbackAnalysis,
    NormalizedFeedback,
    RedactedFeedback,
    RiskEscalation,
    RiskLevel,
    SemanticEnrichment,
    SentimentEmotion,
    TaxonomyClassification,
)
from ingestion import CSVIngester, GoogleFormsIngester, NPSIngester

# ── Fixtures ──────────────────────────────────────────────────────────────────

DUMMY_TEXT = (
    "I've been charged twice this month. I called 555-867-5309 and emailed "
    "support@example.com but got no response. If this isn't fixed I'm cancelling "
    "and moving to CompetitorX. Please also add dark mode — my whole team wants it."
)

DUMMY_DIR = os.path.join(os.path.dirname(__file__), "dummy_data")


def _mock_llm_output(model_class):
    """Return a valid instance of model_class with sensible defaults."""
    defaults = {
        SemanticEnrichment: dict(
            summary="Customer experienced double billing and received no support response.",
            key_topics=["billing", "support", "churn risk"],
            entities=["subscription", "CompetitorX"],
            context="post-billing issue",
        ),
        TaxonomyClassification: dict(category="Billing", subcategory="Duplicate Charge", confidence=0.95),
        SentimentEmotion: dict(sentiment="negative", emotions=["frustrated", "angry"], intensity=8),
        BusinessSignals: dict(
            churn_risk=True,
            upsell_opportunity=False,
            feature_requests=["dark mode"],
            bug_reports=[],
            competitor_mentions=["CompetitorX"],
        ),
        RiskEscalation: dict(
            escalate=True,
            risk_level=RiskLevel.high,
            reason="Billing error + no support response + explicit churn threat",
            suggested_action="Priority callback within 2 hours; refund duplicate charge",
        ),
        ExecutiveIntelligence: dict(
            executive_summary="High-risk customer threatening churn due to unresolved billing error.",
            key_action_items=["Issue refund", "Assign dedicated support agent"],
            priority_recommendations=["Fix billing duplication bug", "Improve support SLA"],
            overall_health_score=2,
        ),
    }
    return model_class(**defaults[model_class])


# ── Ingestion tests ───────────────────────────────────────────────────────────


class TestIngestion:
    def test_csv_ingester(self):
        records = CSVIngester().ingest(os.path.join(DUMMY_DIR, "reviews.csv"))
        assert len(records) == 10
        assert all(r.text for r in records)
        assert all(r.source == "csv_upload" for r in records)
        rated = [r for r in records if r.rating is not None]
        assert len(rated) == 10

    def test_nps_ingester(self):
        records = NPSIngester().ingest(os.path.join(DUMMY_DIR, "nps.csv"))
        assert len(records) == 8
        for r in records:
            assert r.metadata.get("nps_segment") in ("promoter", "passive", "detractor")
            assert r.rating is not None and 1.0 <= r.rating <= 5.0

    def test_google_forms_ingester(self):
        records = GoogleFormsIngester(
            feedback_questions=[
                "What was your overall experience with our service?",
                "What could we improve?",
                "Any other comments?",
            ],
            rating_question="How likely are you to recommend us? (1-5)",
        ).ingest(os.path.join(DUMMY_DIR, "google_forms.csv"))
        assert len(records) == 6
        assert all(r.text for r in records)


# ── Normalization tests ───────────────────────────────────────────────────────


class TestNormalization:
    def test_strips_html(self):
        ctx = normalization_stage.invoke({"raw_text": "<p>Hello <b>world</b></p>"})
        assert "<" not in ctx["normalized"].normalized

    def test_normalizes_whitespace(self):
        ctx = normalization_stage.invoke({"raw_text": "hello   world\n\n\n\nbye"})
        assert "   " not in ctx["normalized"].normalized

    def test_word_count(self):
        ctx = normalization_stage.invoke({"raw_text": DUMMY_TEXT})
        assert ctx["normalized"].word_count > 0

    def test_preserves_original(self):
        ctx = normalization_stage.invoke({"raw_text": DUMMY_TEXT})
        assert ctx["normalized"].original == DUMMY_TEXT


# ── PII redaction tests ───────────────────────────────────────────────────────


class TestPIIRedaction:
    def _run(self, text):
        ctx = normalization_stage.invoke({"raw_text": text})
        return pii_redaction_stage.invoke(ctx)

    def test_redacts_email(self):
        ctx = self._run("Contact me at user@example.com please")
        assert "user@example.com" not in ctx["redacted"].text
        assert "[EMAIL]" in ctx["redacted"].text
        assert "EMAIL" in ctx["redacted"].pii_types_found

    def test_redacts_phone(self):
        ctx = self._run("Call me at 555-867-5309")
        assert "555-867-5309" not in ctx["redacted"].text
        assert "PHONE" in ctx["redacted"].pii_types_found

    def test_redacts_credit_card(self):
        ctx = self._run("My card 4111 1111 1111 1111 was charged")
        assert "4111" not in ctx["redacted"].text
        assert "CREDIT_CARD" in ctx["redacted"].pii_types_found

    def test_no_false_positives_on_clean_text(self):
        ctx = self._run("The product works great and I love the new dashboard.")
        assert ctx["redacted"].pii_types_found == []


# ── Full pipeline (mocked LLM) ────────────────────────────────────────────────


class TestFullPipelineMocked:
    def _fake_pipeline_ctx(self, input_ctx: dict) -> dict:
        """Return a fully-populated context dict, bypassing all LLM calls."""
        from analyzer.pipeline.normalization import normalization_stage
        from analyzer.pipeline.pii_redaction import pii_redaction_stage

        ctx = pii_redaction_stage.invoke(normalization_stage.invoke({**input_ctx, "feedback_id": "test-id-123"}))
        ctx["enrichment"] = _mock_llm_output(SemanticEnrichment)
        ctx["taxonomy"] = _mock_llm_output(TaxonomyClassification)
        ctx["sentiment"] = _mock_llm_output(SentimentEmotion)
        ctx["signals"] = _mock_llm_output(BusinessSignals)
        ctx["risk"] = _mock_llm_output(RiskEscalation)
        ctx["executive"] = _mock_llm_output(ExecutiveIntelligence)
        ctx["experience"] = ExperienceScores(
            csi=CustomerSatisfactionIndex(
                product_quality=3, delivery=3, commercial_process=2, marketing_performance=3,
                complaint_handling=1, company_personnel=2, technical_support=1, relation_building=2,
            ),
            cxi=CustomerExperienceIndex(satisfaction=2, loyalty=1, advocacy=1, value_for_money=2),
            csi_percent=43.8,
            cxi_percent=25.0,
        )
        return ctx

    def test_single_feedback_mocked(self):
        with patch("analyzer.main.pipeline") as mock_pipeline:
            mock_pipeline.invoke.side_effect = self._fake_pipeline_ctx

            from analyzer.main import analyze_single

            result = analyze_single(DUMMY_TEXT)

        assert isinstance(result, FeedbackAnalysis)
        assert result.normalized.word_count > 0
        assert result.redacted.pii_types_found  # should have EMAIL and PHONE
        assert result.taxonomy.category == "Billing"
        assert result.sentiment.sentiment == "negative"
        assert result.signals.churn_risk is True
        assert result.risk.escalate is True
        assert result.executive.overall_health_score == 2
        assert result.experience is not None
        assert result.experience.csi_percent == 43.8
        assert result.experience.cxi.satisfaction == 2


# ── Live pipeline test (requires vLLM on localhost:8000) ─────────────────────


@pytest.mark.live
class TestLivePipeline:
    def test_single_feedback_live(self):
        from analyzer.main import analyze_single

        result = analyze_single(DUMMY_TEXT)
        assert isinstance(result, FeedbackAnalysis)
        assert result.sentiment.sentiment in ("positive", "negative", "neutral")
        assert 1 <= result.executive.overall_health_score <= 10
        print("\n--- Live Result ---")
        print(result.model_dump_json(indent=2))
