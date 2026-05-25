from functools import lru_cache
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct-AWQ"),
        base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        api_key="dummy",
        temperature=temperature,
        max_retries=3,
    )
