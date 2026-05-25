from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum


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


TaxonomyCategory = Literal[
    "Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other"
]


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
    emotions: list[str] = Field(description="Detected emotions e.g. frustrated, happy, confused")
    intensity: int = Field(description="Emotional intensity from 1 (mild) to 10 (extreme)", ge=1, le=10)


class BusinessSignals(BaseModel):
    churn_risk: bool = Field(description="True if customer shows signs of leaving")
    upsell_opportunity: bool = Field(description="True if customer is open to more services")
    feature_requests: list[str] = Field(description="Specific features the customer requested")
    bug_reports: list[str] = Field(description="Bugs or broken functionality mentioned")
    competitor_mentions: list[str] = Field(description="Any competitors named")


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


class FeedbackAnalysis(BaseModel):
    normalized: NormalizedFeedback
    redacted: RedactedFeedback
    enrichment: SemanticEnrichment
    taxonomy: TaxonomyClassification
    sentiment: SentimentEmotion
    signals: BusinessSignals
    risk: RiskEscalation
    executive: ExecutiveIntelligence
