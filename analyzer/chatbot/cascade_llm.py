"""Model cascade router — routes queries to the small draft model (1.5B on 1650 Ti)
or the full target model (7B on 4070) based on query complexity.

Application-level cascade replaces vLLM's single-machine spec decode for our
2-machine setup. The draft model handles simple conversational turns cheaply;
complex/issue-heavy queries go straight to the authoritative model.

Config: set DRAFT_LLM_URL env var to the 1.5B endpoint URL.
If unset or empty, all queries fall back to the big model (safe default).
"""
from __future__ import annotations

import os
from functools import lru_cache

from langchain_openai import ChatOpenAI

from analyzer.llm import get_llm

DRAFT_LLM_URL: str = os.getenv("DRAFT_LLM_URL", "").rstrip("/")

# Keywords that signal the query needs the full model's reasoning power
_COMPLEX_SIGNALS = {
    "why", "explain", "issue", "complaint", "escalate", "broken", "damaged",
    "refund", "wrong", "missing", "urgent", "angry", "terrible", "worst",
    "disappointed", "frustrated", "lost", "never", "impossible", "unacceptable",
    "legal", "manager", "lawsuit", "charged", "overcharged", "fraud",
}


def classify_complexity(query: str) -> str:
    """Return 'small' for simple queries, 'big' for complex/emotional ones."""
    words = set(query.lower().split())
    if len(words) > 20 or words & _COMPLEX_SIGNALS:
        return "big"
    return "small"


@lru_cache(maxsize=4)
def _draft_llm(temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model="Qwen/Qwen2.5-1.5B-Instruct",
        base_url=f"{DRAFT_LLM_URL}/v1" if not DRAFT_LLM_URL.endswith("/v1") else DRAFT_LLM_URL,
        api_key="dummy",
        temperature=temperature,
        max_retries=2,
    )


def get_chat_llm(query: str, temperature: float = 0.3) -> ChatOpenAI:
    """Return the appropriate LLM for the given query.

    - Simple queries → Qwen2.5-1.5B (fast, cheap, runs on 1650 Ti)
    - Complex/emotional queries → Qwen2.5-7B (authoritative, runs on 4070)
    - If DRAFT_LLM_URL is not set → always big model
    """
    if DRAFT_LLM_URL and classify_complexity(query) == "small":
        try:
            return _draft_llm(temperature)
        except Exception:
            pass  # fall through to big model if draft LLM unreachable
    return get_llm(temperature)
