from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import RiskEscalation

_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a customer risk analyst. Assess whether feedback requires escalation "
        "and assign a risk level. Escalate when: legal threats, safety concerns, "
        "high-value customer churn risk, repeated failures, or extreme dissatisfaction."
    )),
    ("human", (
        "Past cases that were escalated (for calibration):\n{escalation_precedents}\n\n"
        "Feedback: {text}\n"
        "Sentiment: {sentiment}, Intensity: {intensity}/10\n"
        "Churn risk: {churn_risk}\n"
        "Emotions: {emotions}\n"
        "Category: {category}\n\n"
        "Assess:\n"
        "- escalate: true/false\n"
        "- risk_level: low, medium, high, or critical\n"
        "- reason: why this risk level was assigned\n"
        "- suggested_action: specific next step for the support/ops team"
    )),
])


def _build_escalation_precedents() -> str:
    try:
        from vectordb.store import get_escalation_precedents
        precedents = get_escalation_precedents(k=3)
        if not precedents:
            return "No escalation precedents yet."
        return "\n".join(
            f"- [{p.get('category', 'unknown')}] {p.get('summary', '')}"
            for p in precedents
        )
    except Exception:
        return "No escalation precedents yet."


def _assess_risk(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(RiskEscalation)
    result = chain.invoke({
        "text": ctx["redacted"].text,
        "sentiment": ctx["sentiment"].sentiment,
        "intensity": ctx["sentiment"].intensity,
        "churn_risk": ctx["signals"].churn_risk,
        "emotions": ", ".join(ctx["sentiment"].emotions),
        "category": ctx["taxonomy"].category,
        "escalation_precedents": _build_escalation_precedents(),
    })
    return {**ctx, "risk": result}


risk_escalation_stage = RunnableLambda(_assess_risk)
