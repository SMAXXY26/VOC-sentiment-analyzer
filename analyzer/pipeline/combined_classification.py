from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import CombinedClassification

# Same category list the standalone taxonomy stage uses — kept verbatim so the merged
# path classifies identically.
_CATEGORIES = (
    "Billing, Product Quality, Customer Support, Shipping & Delivery, "
    "Account Management, Technical Issue, Onboarding, Returns & Refunds, Other"
)

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a customer-feedback analysis engine. In a SINGLE pass, produce the "
                "taxonomy, the sentiment/emotion read, and the business signals for one piece of "
                "feedback. Reason about all three jointly and keep them mutually consistent.\n"
                "Rules:\n"
                "- taxonomy: choose the single dominant category (not a passing mention) plus a "
                f"specific subcategory. Categories: {_CATEGORIES}. Set confidence to genuine "
                "certainty — above 0.8 only when the category is unambiguous.\n"
                "- sentiment: overall positive/negative/neutral, the specific emotions actually "
                "expressed (never projected), and intensity 1 (mild) to 10 (extreme).\n"
                "- signals: only what the wording supports — leave lists empty rather than "
                "guessing, and do not mark churn or upsell unless the customer's words support it.\n"
                "Be terse: every list is hard-capped to a few items, so report only the strongest. "
                "Never pad lists or repeat — extra output will be truncated."
            ),
        ),
        (
            "human",
            (
                "Known feature requests from similar past feedback (do not duplicate these unless "
                "the customer explicitly re-requests them):\n{feature_history}\n\n"
                "Feedback: {text}\n"
                "Topics: {topics}\n\n"
                "Return one object with:\n"
                "- taxonomy: category, subcategory, confidence (0-1)\n"
                "- sentiment: sentiment, emotions, intensity (1-10)\n"
                "- signals: churn_risk, upsell_opportunity, feature_requests, bug_reports, "
                "competitor_mentions"
            ),
        ),
    ]
)


def _build_feature_history() -> str:
    # Identical helper to business_signals.py so the merged path sees the same RAG context.
    try:
        from vectordb.store import get_feature_history

        features = get_feature_history(k=20)
        if not features:
            return "No feature history yet."
        return "\n".join(f"- {f}" for f in features)
    except Exception:
        return "No feature history yet."


def _classify_combined(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(CombinedClassification)
    result = chain.invoke(
        {
            "text": ctx["redacted"].text,
            "topics": ", ".join(ctx["enrichment"].key_topics),
            "feature_history": _build_feature_history(),
        }
    )
    # Re-split into the three ctx keys the downstream stages already expect, so merging the
    # call changes nothing about the pipeline contract (risk_escalation, confidence,
    # experience_scoring, store_result and the FeedbackAnalysis assembly all read these).
    return {
        **ctx,
        "taxonomy": result.taxonomy,
        "sentiment": result.sentiment,
        "signals": result.signals,
    }


combined_classification_stage = RunnableLambda(_classify_combined)
