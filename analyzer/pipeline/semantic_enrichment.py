from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import SemanticEnrichment

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a customer experience analyst. "
                "Analyze the feedback and extract structured semantic information. "
                "Be concise and factual."
            ),
        ),
        (
            "human",
            (
                "Similar past feedback for context:\n{rag_context}\n\n"
                "Analyze this customer feedback:\n\n{text}\n\n"
                "Extract:\n"
                "- summary: one sentence capturing the core message\n"
                "- key_topics: main topics discussed (list)\n"
                "- entities: products, features, or services mentioned (list)\n"
                "- context: brief situational context (e.g. post-purchase, onboarding, billing issue)"
            ),
        ),
    ]
)


def _build_rag_context(ctx: dict) -> str:
    try:
        import os

        from vectordb.few_shot import get_few_shot_examples
        from vectordb.store import get_rag_context

        k = int(os.getenv("RAG_K", "3"))
        past = get_rag_context(ctx["redacted"].text, k=k)
        few = get_few_shot_examples(ctx["redacted"].text, k=2)
        combined = past + [f for f in few if f not in past]
        if not combined:
            return "No similar feedback found yet."
        return "\n".join(f"- {item['summary']}" for item in combined[:k])
    except Exception:
        return "No similar feedback found yet."


def _enrich(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(SemanticEnrichment)
    result = chain.invoke(
        {
            "text": ctx["redacted"].text,
            "rag_context": _build_rag_context(ctx),
        }
    )
    return {**ctx, "enrichment": result}


semantic_enrichment_stage = RunnableLambda(_enrich)
