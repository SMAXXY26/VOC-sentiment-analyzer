"""Model-tier routing for the analysis pipeline.

v1 routed on a keyword list ("refund", "fraud", ...). That misses intent: "I'm fine,
just want to cancel" has no trigger word but is a churn/cancellation signal that wants
the full model. Since a 1.5B draft model is already deployed, use IT as the router —
a single low-token classification call that reads intent, not surface words.

Precedence (env MODEL_ROUTER, default "model"):
  - "model"   : ask the 1.5B model; on failure/unavailable, fall back to keywords
  - "keyword" : use the producer's keyword hint / the keyword classifier (no LLM call)
  - "off"     : honour the explicit hint as-is (or "big")

The keyword classifier (analyzer.chatbot.cascade_llm.classify_complexity) remains the
single Python source of truth for the fallback — the Rust producer mirrors it, guarded
by tests/test_hardening.py::test_classifier_keyword_parity.
"""

from __future__ import annotations

import os

_ROUTER_SYSTEM = (
    "You are a router. Classify the customer message as complex or simple.\n"
    "complex = emotional, a complaint or escalation, churn or cancellation intent, "
    "billing/fraud/charge disputes, multi-part, or ambiguous wording needing careful "
    "reasoning.\n"
    "simple = a routine, clearly-stated, low-stakes request or a short factual question.\n"
    "Output ONLY one word — complex or simple — and nothing else."
)


def _route_with_model(text: str) -> str | None:
    """Classify with the 1.5B draft model. Returns 'big'/'small', or None if the draft
    model isn't configured or the call fails (caller then falls back to keywords)."""
    from .chatbot.cascade_llm import DRAFT_LLM_URL as _DRAFT_URL
    from .chatbot.cascade_llm import _draft_llm
    from .llm import reset_target_model, set_target_model

    if not _DRAFT_URL:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _draft_llm(0.0).bind(max_tokens=8)
        # Label this call as a "small"-model call for the token/usage metrics.
        tok = set_target_model("small")
        try:
            resp = llm.invoke([SystemMessage(content=_ROUTER_SYSTEM), HumanMessage(content=text[:600])])
        finally:
            reset_target_model(tok)
        out = str(resp.content).strip().lower()
        # Parse whichever label appears first (handles a stray preamble/punctuation).
        i_c, i_s = out.find("complex"), out.find("simple")
        if i_c == -1 and i_s == -1:
            return None
        if i_s == -1 or (i_c != -1 and i_c < i_s):
            return "big"
        return "small"
    except Exception:
        return None


def resolve_model_tier(text: str, hint: str | None = None) -> str:
    """Decide which model tier ('big'|'small') analyses this text."""
    mode = os.getenv("MODEL_ROUTER", "model").lower()

    if mode == "off":
        return hint if hint in ("big", "small") else "big"

    if mode == "model":
        decided = _route_with_model(text)
        if decided:
            return decided
        # model router unavailable/failed → fall through to keyword fallback

    # "keyword" mode, or model-router fallback: prefer the producer's hint, else classify.
    if hint in ("big", "small"):
        return hint
    from .chatbot.cascade_llm import classify_complexity

    return classify_complexity(text)
