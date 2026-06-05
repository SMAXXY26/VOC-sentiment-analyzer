from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import ExperienceScores

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a customer-experience measurement specialist. "
                "Score each listed dimension on an integer scale from 1 (very poor) to 6 (excellent), "
                "using ONLY evidence present in the feedback and the analysis context provided. "
                "When a dimension is not explicitly mentioned, infer a measured score from the overall "
                "tone, sentiment and emotions rather than defaulting everything to the middle. "
                "Do not invent facts the customer did not express."
            ),
        ),
        (
            "human",
            (
                "Feedback: {text}\n"
                "Summary: {summary}\n"
                "Category: {category}\n"
                "Sentiment: {sentiment} (intensity {intensity}/10)\n"
                "Emotions: {emotions}\n"
                "Churn risk: {churn_risk} | Escalated: {escalate}\n\n"
                "Score the Customer Satisfaction Index dimensions (1-6 each):\n"
                "- product_quality, delivery, commercial_process, marketing_performance,\n"
                "  complaint_handling, company_personnel, technical_support, relation_building\n\n"
                "Score the Customer Experience Index dimensions (1-6 each):\n"
                "- satisfaction, loyalty, advocacy, value_for_money"
            ),
        ),
    ]
)


def _to_percent(values: list[int]) -> float:
    # Equal weighting: mean of the 1-6 scores, expressed out of 100 via (mean / 6) * 100.
    return round(sum(values) / len(values) / 6 * 100, 1)


def _score_experience(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(ExperienceScores)
    result = chain.invoke(
        {
            "text": ctx["redacted"].text,
            "summary": ctx["enrichment"].summary,
            "category": ctx["taxonomy"].category,
            "sentiment": ctx["sentiment"].sentiment,
            "intensity": ctx["sentiment"].intensity,
            "emotions": ", ".join(ctx["sentiment"].emotions) or "none",
            "churn_risk": ctx["signals"].churn_risk,
            "escalate": ctx["risk"].escalate,
        }
    )

    csi_values = list(result.csi.model_dump().values())
    cxi_values = list(result.cxi.model_dump().values())
    result = result.model_copy(
        update={
            "csi_percent": _to_percent(csi_values),
            "cxi_percent": _to_percent(cxi_values),
        }
    )
    return {**ctx, "experience": result}


experience_scoring_stage = RunnableLambda(_score_experience)
