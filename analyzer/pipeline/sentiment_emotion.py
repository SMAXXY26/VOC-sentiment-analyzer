from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from ..llm import get_llm
from ..schemas import SentimentEmotion

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a sentiment and emotion analyst specializing in customer experience. "
                "Identify the overall sentiment and specific emotions expressed in feedback. "
                "Common emotions: frustrated, angry, happy, satisfied, confused, disappointed, "
                "excited, anxious, grateful, neutral."
            ),
        ),
        (
            "human",
            (
                "Feedback: {text}\n\n"
                "Determine:\n"
                "- sentiment: positive, negative, or neutral\n"
                "- emotions: list of specific emotions detected\n"
                "- intensity: emotional intensity from 1 (very mild) to 10 (extreme)"
            ),
        ),
    ]
)


def _analyze_sentiment(ctx: dict) -> dict:
    chain = _prompt | get_llm().with_structured_output(SentimentEmotion)
    result = chain.invoke({"text": ctx["redacted"].text})
    return {**ctx, "sentiment": result}


sentiment_emotion_stage = RunnableLambda(_analyze_sentiment)
