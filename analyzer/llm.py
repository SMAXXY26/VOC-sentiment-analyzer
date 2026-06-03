"""
Distributed LLM client.

Single-endpoint (default):
    VLLM_BASE_URL=http://localhost:8000/v1   ← behaves exactly as before

Multi-endpoint (distributed inference):
    VLLM_ENDPOINTS=http://192.168.1.11:8000/v1,http://192.168.1.12:8000/v1

When VLLM_ENDPOINTS is set, get_llm() round-robins across all endpoints.
Each endpoint gets its own ChatOpenAI instance cached by (endpoint, temperature).
Health checks are non-blocking — unhealthy endpoints stay in the pool but their
failed invocations will surface as normal LangChain exceptions.

Backward-compatibility note:
    Original code had @lru_cache on get_llm() itself.
    Cache is now on _llm_for_endpoint() per (endpoint, temperature) — same
    observable behaviour for single-endpoint usage; tests that patch
    analyzer.main.pipeline are unaffected.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from functools import lru_cache
from itertools import cycle
from threading import Lock

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


# ── Model routing ────────────────────────────────────────────────────────────
# The Rust producer tags each job with target_model ("big" | "small"); the
# analyzer threads that into this ContextVar so every get_llm() call inside the
# pipeline resolves to the same model for the duration of one analysis — without
# having to pass `model` through all 8 stages. Default None = big model.
_target_model: ContextVar[str | None] = ContextVar("target_model", default=None)


def set_target_model(model: str | None):
    """Set the per-request model hint; returns the token for reset() in a finally."""
    return _target_model.set(model)


def reset_target_model(token) -> None:
    _target_model.reset(token)


# Draft (small) model — same env var the chatbot cascade uses, so a single
# deployment serves both. If unset, "small" silently falls back to the big model.
_DRAFT_URL: str = os.getenv("DRAFT_LLM_URL", "").rstrip("/")
_DRAFT_MODEL: str = os.getenv("DRAFT_MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct-AWQ")


# ── Token / call accounting ──────────────────────────────────────────────────
# A callback attached to every ChatOpenAI instance records call count and token
# usage into Prometheus, labelled by the active cascade tier. This is how the
# "inference economics" and "model-cascade payoff" metrics get their data — without
# touching any of the pipeline stage code.

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402


class _UsageCallback(BaseCallbackHandler):
    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        from .metrics import (
            LLM_CALLS_TOTAL,
            LLM_COMPLETION_TOKENS_TOTAL,
            LLM_PROMPT_TOKENS_TOTAL,
        )

        model = _target_model.get() or "big"
        LLM_CALLS_TOTAL.labels(model=model).inc()

        prompt_tok, completion_tok = self._extract_tokens(response)
        if prompt_tok:
            LLM_PROMPT_TOKENS_TOTAL.labels(model=model).inc(prompt_tok)
        if completion_tok:
            LLM_COMPLETION_TOKENS_TOTAL.labels(model=model).inc(completion_tok)

    @staticmethod
    def _extract_tokens(response) -> tuple[int, int]:
        # Preferred: OpenAI-style token_usage in llm_output (vLLM returns this).
        try:
            usage = (response.llm_output or {}).get("token_usage") or {}
            if usage:
                return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        except Exception:
            pass
        # Fallback: usage_metadata on the generated messages.
        try:
            for gens in response.generations:
                for gen in gens:
                    um = getattr(getattr(gen, "message", None), "usage_metadata", None)
                    if um:
                        return int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
        except Exception:
            pass
        return 0, 0


_usage_callback = _UsageCallback()


# ── Endpoint pool ──────────────────────────────────────────────────────────────

def _parse_endpoints() -> list[str]:
    multi = os.getenv("VLLM_ENDPOINTS", "").strip()
    if multi:
        return [e.strip().rstrip("/") for e in multi.split(",") if e.strip()]
    return [os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")]


_endpoints: list[str] = _parse_endpoints()
_cycle = cycle(range(len(_endpoints)))
_lock = Lock()


def _next_endpoint() -> str:
    with _lock:
        return _endpoints[next(_cycle)]


# ── Cached LLM instances per (endpoint, temperature) ─────────────────────────

@lru_cache(maxsize=16)
def _llm_for_endpoint(endpoint: str, temperature: float) -> ChatOpenAI:
    base = endpoint if endpoint.endswith("/v1") else endpoint + "/v1"
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct-AWQ"),
        base_url=base,
        api_key="dummy",
        temperature=temperature,
        max_retries=3,
        callbacks=[_usage_callback],
    )


@lru_cache(maxsize=4)
def _draft_llm(temperature: float) -> ChatOpenAI:
    base = _DRAFT_URL if _DRAFT_URL.endswith("/v1") else _DRAFT_URL + "/v1"
    return ChatOpenAI(
        model=_DRAFT_MODEL,
        base_url=base,
        api_key="dummy",
        temperature=temperature,
        max_retries=2,
        callbacks=[_usage_callback],
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.1, model: str | None = None) -> ChatOpenAI:
    """
    Return a ChatOpenAI instance for this analysis.

    Model selection (in priority order):
      1. explicit `model` arg
      2. the per-request ContextVar set from the job's target_model
      3. "big" (default)

    "small" routes to the draft model when DRAFT_LLM_URL is configured, else falls
    back to the big model. "big"/None round-robins across the main vLLM endpoints —
    identical to the original behaviour when no routing hint is present.
    """
    target = model or _target_model.get()
    if target == "small" and _DRAFT_URL:
        try:
            return _draft_llm(temperature)
        except Exception:
            pass  # draft unreachable → fall through to big model
    return _llm_for_endpoint(_next_endpoint(), temperature)


def get_healthy_endpoints() -> list[dict]:
    """
    Probe all configured endpoints synchronously.
    Used by GET /system and distributed inference monitoring.
    Never raises — each entry has status 'ok' | 'error' | 'unreachable'.
    """
    results = []
    for ep in _endpoints:
        base = ep.removesuffix("/v1")
        try:
            r = httpx.get(f"{base}/health", timeout=2.0)
            status = "ok" if r.status_code == 200 else "error"
            results.append({"endpoint": ep, "status": status, "http_code": r.status_code})
        except Exception as exc:
            results.append({"endpoint": ep, "status": "unreachable", "error": str(exc)})
    return results


def endpoint_count() -> int:
    return len(_endpoints)
