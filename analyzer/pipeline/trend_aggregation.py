from collections import Counter

from langchain_core.prompts import ChatPromptTemplate

from ..llm import get_llm
from ..schemas import FeedbackAnalysis, TrendAggregation

_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a customer insights analyst. Identify recurring themes and systemic "
        "issues across a batch of customer feedback items."
    )),
    ("human", (
        "Summaries from {count} feedback items:\n{summaries}\n\n"
        "Top topics across all feedback:\n{topics}\n\n"
        "Identify:\n"
        "- common_themes: recurring patterns across feedback items\n"
        "- top_issues: most frequently reported problems"
    )),
])


def aggregate_trends(analyses: list[FeedbackAnalysis]) -> TrendAggregation:
    sentiment_dist = Counter(a.sentiment.sentiment for a in analyses)
    escalation_count = sum(1 for a in analyses if a.risk.escalate)
    churn_count = sum(1 for a in analyses if a.signals.churn_risk)

    summaries = "\n".join(
        f"- {a.enrichment.summary}" for a in analyses
    )
    all_topics = [t for a in analyses for t in a.enrichment.key_topics]
    top_topics = ", ".join(t for t, _ in Counter(all_topics).most_common(15))

    # LLM only fills qualitative fields; counts are computed deterministically
    from pydantic import BaseModel

    class _LLMThemes(BaseModel):
        common_themes: list[str]
        top_issues: list[str]

    chain = _prompt | get_llm().with_structured_output(_LLMThemes)
    llm_result = chain.invoke({
        "count": len(analyses),
        "summaries": summaries,
        "topics": top_topics,
    })

    return TrendAggregation(
        common_themes=llm_result.common_themes,
        top_issues=llm_result.top_issues,
        sentiment_distribution=dict(sentiment_dist),
        escalation_count=escalation_count,
        churn_risk_count=churn_count,
    )
