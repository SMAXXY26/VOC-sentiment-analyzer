from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import ExecutiveIntelligence

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a Chief Customer Officer preparing a briefing. "
                "Synthesize all analysis into a concise, decision-ready executive summary. "
                "Be direct, business-focused, and prioritize by impact."
            ),
        ),
        (
            "human",
            (
                "Feedback summary: {summary}\n"
                "Category: {category} > {subcategory}\n"
                "Sentiment: {sentiment} (intensity {intensity}/10)\n"
                "Emotions: {emotions}\n"
                "Risk level: {risk_level} | Escalate: {escalate}\n"
                "Churn risk: {churn_risk} | Upsell opportunity: {upsell}\n"
                "Feature requests: {features}\n"
                "Bug reports: {bugs}\n"
                "Suggested action: {action}\n\n"
                "Produce:\n"
                "- executive_summary: 2-3 sentences for a business audience\n"
                "- key_action_items: concrete immediate actions\n"
                "- priority_recommendations: strategic recommendations by urgency\n"
                "- overall_health_score: CX health score 1-10"
            ),
        ),
    ]
)


def _generate_executive(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(ExecutiveIntelligence)
    result = chain.invoke(
        {
            "summary": ctx["enrichment"].summary,
            "category": ctx["taxonomy"].category,
            "subcategory": ctx["taxonomy"].subcategory,
            "sentiment": ctx["sentiment"].sentiment,
            "intensity": ctx["sentiment"].intensity,
            "emotions": ", ".join(ctx["sentiment"].emotions),
            "risk_level": ctx["risk"].risk_level,
            "escalate": ctx["risk"].escalate,
            "churn_risk": ctx["signals"].churn_risk,
            "upsell": ctx["signals"].upsell_opportunity,
            "features": ", ".join(ctx["signals"].feature_requests) or "none",
            "bugs": ", ".join(ctx["signals"].bug_reports) or "none",
            "action": ctx["risk"].suggested_action,
        }
    )
    return {**ctx, "executive": result}


executive_intelligence_stage = RunnableLambda(_generate_executive)
