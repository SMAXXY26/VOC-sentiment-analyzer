from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from ..llm import get_llm
from ..schemas import TaxonomyClassification

_CATEGORIES = (
    "Billing, Product Quality, Customer Support, Shipping & Delivery, "
    "Account Management, Technical Issue, Onboarding, Returns & Refunds, Other"
)

_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a customer feedback classifier. "
        "Classify feedback into the most appropriate category and subcategory. "
        f"Top-level categories: {_CATEGORIES}"
    )),
    ("human", (
        "Feedback: {text}\n"
        "Topics: {topics}\n\n"
        "Classify this feedback with a category, subcategory, and confidence score (0-1)."
    )),
])


def _classify(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(TaxonomyClassification)
    result = chain.invoke({
        "text": ctx["redacted"].text,
        "topics": ", ".join(ctx["enrichment"].key_topics),
    })
    return {**ctx, "taxonomy": result}


taxonomy_stage = RunnableLambda(_classify)
