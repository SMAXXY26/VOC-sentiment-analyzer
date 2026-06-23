from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class NormalizedFeedback(BaseModel):
    original: str
    normalized: str
    language: str
    word_count: int


class RedactedFeedback(BaseModel):
    text: str
    pii_types_found: list[str]


class SemanticEnrichment(BaseModel):
    summary: str = Field(description="One sentence summary of the feedback")
    key_topics: list[str] = Field(description="Main topics discussed")
    entities: list[str] = Field(description="Products, features, or services mentioned")
    context: str = Field(description="Brief context e.g. post-purchase, onboarding, support")


TaxonomyCategory = Literal["Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other"]


class TaxonomyClassification(BaseModel):
    # Literal type rejects any value outside this list at parse time —
    # prevents silent LLM drift producing unmapped categories downstream.
    category: TaxonomyCategory = Field(
        description="Top-level category: Billing, Product, Support, Shipping, Account, Onboarding, or Other"
    )
    subcategory: str = Field(description="More specific subcategory")
    confidence: float = Field(description="Confidence score between 0 and 1", ge=0.0, le=1.0)


class SentimentEmotion(BaseModel):
    sentiment: str = Field(description="positive, negative, or neutral")
    # max_length caps the worst-case serialized size: under the merged single-call
    # schema, unbounded lists are what let the AWQ model ramble and blow the
    # max_tokens cap (truncated JSON → .parse() failure). Report only the strongest.
    emotions: list[str] = Field(
        description="Up to 6 specific emotions actually expressed (strongest first)", max_length=6
    )
    intensity: int = Field(description="Emotional intensity from 1 (mild) to 10 (extreme)", ge=1, le=10)


class BusinessSignals(BaseModel):
    churn_risk: bool = Field(description="True if customer shows signs of leaving")
    upsell_opportunity: bool = Field(description="True if customer is open to more services")
    # Lists hard-capped so the combined-classification JSON stays bounded (see SentimentEmotion).
    feature_requests: list[str] = Field(
        description="Up to 6 specific features the customer requested", max_length=6
    )
    bug_reports: list[str] = Field(
        description="Up to 6 bugs or broken functionality mentioned", max_length=6
    )
    competitor_mentions: list[str] = Field(
        description="Up to 5 competitors named", max_length=5
    )


class CombinedClassification(BaseModel):
    """Single LLM call that replaces the taxonomy + sentiment + business_signals trio.

    The merged stage re-splits this into ctx["taxonomy"/"sentiment"/"signals"], so every
    downstream stage and the FeedbackAnalysis assembly keep their existing contract — only
    the *call count* drops from 3 to 1. Nesting (not flattening) is deliberate: it reuses
    the exact field-level constraints and descriptions the separate stages already proved
    out, so the guided-decoding grammar is identical per sub-object.

    VRAM / JSON-truncation budget (8GB AWQ 7B, target --max-model-len 2048):
      input prompt   ~600-900 tok (3 instruction blocks + feedback + topics + history)
      output JSON    ~250-500 tok worst case, bounded by the max_length caps on every list
    Comfortably inside the max_tokens=1024 generation cap, so the object can always close
    before hitting finish_reason="length".
    """

    taxonomy: TaxonomyClassification
    sentiment: SentimentEmotion
    signals: BusinessSignals


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RiskEscalation(BaseModel):
    escalate: bool = Field(description="True if this feedback requires immediate human attention")
    risk_level: RiskLevel
    reason: str = Field(description="Why this risk level was assigned")
    suggested_action: str = Field(description="Recommended next step")


class TrendAggregation(BaseModel):
    common_themes: list[str] = Field(description="Recurring themes across all feedback")
    top_issues: list[str] = Field(description="Most frequently reported problems")
    sentiment_distribution: dict[str, int] = Field(description="Count of positive/negative/neutral")
    escalation_count: int = Field(description="Number of feedbacks flagged for escalation")
    churn_risk_count: int = Field(description="Number of feedbacks with churn risk signals")


class ExecutiveIntelligence(BaseModel):
    executive_summary: str = Field(description="2-3 sentence business-level summary")
    key_action_items: list[str] = Field(description="Concrete actions the business should take")
    priority_recommendations: list[str] = Field(description="Strategic recommendations ranked by urgency")
    overall_health_score: int = Field(description="Customer experience health score 1-10", ge=1, le=10)


class CustomerSatisfactionIndex(BaseModel):
    # Eight equally-weighted dimensions, each scored 1 (very poor) to 6 (excellent).
    product_quality: int = Field(description="Quality of the product itself", ge=1, le=6)
    delivery: int = Field(description="Delivery / fulfilment speed and reliability", ge=1, le=6)
    commercial_process: int = Field(description="Ordering, pricing, billing and purchase process", ge=1, le=6)
    marketing_performance: int = Field(description="Accuracy of marketing vs. actual experience", ge=1, le=6)
    complaint_handling: int = Field(description="How complaints/issues were resolved", ge=1, le=6)
    company_personnel: int = Field(description="Competence and attitude of staff dealt with", ge=1, le=6)
    technical_support: int = Field(description="Quality of technical / product support", ge=1, le=6)
    relation_building: int = Field(description="Ongoing relationship and trust with the customer", ge=1, le=6)


class CustomerExperienceIndex(BaseModel):
    # Four equally-weighted dimensions, each scored 1 (very poor) to 6 (excellent).
    satisfaction: int = Field(description="Overall satisfaction with the experience", ge=1, le=6)
    loyalty: int = Field(description="Likelihood of staying / repurchasing", ge=1, le=6)
    advocacy: int = Field(description="Likelihood of recommending to others", ge=1, le=6)
    value_for_money: int = Field(description="Perceived value relative to price paid", ge=1, le=6)


class ExperienceScores(BaseModel):
    csi: CustomerSatisfactionIndex
    cxi: CustomerExperienceIndex
    # Percentages computed deterministically in experience_scoring_stage: (mean(dims) / 6) * 100.
    csi_percent: float = Field(default=0.0, description="CSI as a percentage (mean of 8 dims / 6 * 100)")
    cxi_percent: float = Field(default=0.0, description="CXI as a percentage (mean of 4 dims / 6 * 100)")


class FeedbackAnalysis(BaseModel):
    normalized: NormalizedFeedback
    redacted: RedactedFeedback
    enrichment: SemanticEnrichment
    taxonomy: TaxonomyClassification
    sentiment: SentimentEmotion
    signals: BusinessSignals
    risk: RiskEscalation
    executive: ExecutiveIntelligence
    # Computed by experience_scoring_stage — None for analyses loaded from cache / pre-feature era
    experience: Optional[ExperienceScores] = None
    # Computed by confidence_stage — None for analyses loaded from cache / pre-confidence era
    pipeline_confidence: Optional[float] = None
    needs_review: Optional[bool] = None
