from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import BusinessSignals

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a business intelligence analyst. "
                "Extract actionable business signals from customer feedback. "
                "Focus on signals that directly impact revenue, retention, and product direction."
            ),
        ),
        (
            "human",
            (
                "Known feature requests from similar past feedback:\n{feature_history}\n\n"
                "Feedback: {text}\n"
                "Sentiment: {sentiment} (intensity {intensity}/10)\n"
                "Category: {category}\n\n"
                "Extract business signals:\n"
                "- churn_risk: true if customer shows intent to leave or cancel\n"
                "- upsell_opportunity: true if customer expresses interest in more features or plans\n"
                "- feature_requests: specific features or improvements requested (avoid duplicating already-known requests above unless the customer is explicitly asking for them)\n"
                "- bug_reports: broken functionality or errors described\n"
                "- competitor_mentions: any competitor names mentioned"
            ),
        ),
    ]
)


def _build_feature_history() -> str:
    try:
        from vectordb.store import get_feature_history

        features = get_feature_history(k=20)
        if not features:
            return "No feature history yet."
        return "\n".join(f"- {f}" for f in features)
    except Exception:
        return "No feature history yet."


def _extract_signals(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(BusinessSignals)
    result = chain.invoke(
        {
            "text": ctx["redacted"].text,
            "sentiment": ctx["sentiment"].sentiment,
            "intensity": ctx["sentiment"].intensity,
            "category": ctx["taxonomy"].category,
            "feature_history": _build_feature_history(),
        }
    )
    return {**ctx, "signals": result}


business_signals_stage = RunnableLambda(_extract_signals)
