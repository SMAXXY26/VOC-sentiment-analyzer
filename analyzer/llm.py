"""
LLM client.

There is exactly ONE load balancer in this system: the Rust inference router
(kafka_queue/src/bin/router.rs). The analyzer always talks to a single base URL —
VLLM_BASE_URL — which in production points at the router (http://router:8100/v1),
and in single-GPU/local setups points straight at a vLLM (http://localhost:8000/v1).

This file used to ALSO do client-side round-robin over VLLM_ENDPOINTS. That created
a real ambiguity — two load balancers, and which one ran depended on env config. The
round-robin is removed: load balancing is the router's job (it routes by live queue
depth, which round-robin can't). VLLM_ENDPOINTS is still read for backward
compatibility, but if it lists more than one endpoint we warn and use the first —
the correct fix is to list those endpoints in the *router's* VLLM_ENDPOINTS instead.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from functools import lru_cache

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
_log = logging.getLogger(__name__)


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


# ── Single inference endpoint (the router, or a direct vLLM) ─────────────────


def _resolve_base_url() -> str:
    """The one base URL the analyzer sends inference to. The router load-balances
    behind it; we do NOT load-balance client-side."""
    legacy = os.getenv("VLLM_ENDPOINTS", "").strip()
    if legacy:
        endpoints = [e.strip().rstrip("/") for e in legacy.split(",") if e.strip()]
        if len(endpoints) > 1:
            _log.warning(
                "VLLM_ENDPOINTS lists %d endpoints, but client-side round-robin was "
                "removed — the router is the load balancer. Using the first (%s); put "
                "the rest in the router's VLLM_ENDPOINTS.",
                len(endpoints),
                endpoints[0],
            )
        if endpoints:
            return endpoints[0]
    return os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")


_BASE_URL: str = _resolve_base_url()


# ── Cached LLM instances per temperature ─────────────────────────────────────


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
    back to the big model. "big"/None go to the single base URL (the router, which
    load-balances across the real GPUs).
    """
    target = model or _target_model.get()
    if target == "small" and _DRAFT_URL:
        try:
            return _draft_llm(temperature)
        except Exception:
            pass  # draft unreachable → fall through to big model
    return _llm_for_endpoint(_BASE_URL, temperature)


def base_url() -> str:
    """The single inference base URL the analyzer uses (router or direct vLLM)."""
    return _BASE_URL


def get_healthy_endpoints() -> list[dict]:
    """
    Health view for GET /inference/endpoints.

    The analyzer points at one base URL (the router). When that base is the router,
    we additionally pull its /fleet so the response shows the real per-GPU backends
    and their live load — the actual distributed-inference picture. Otherwise we just
    probe the single endpoint's /health. Never raises.
    """
    base = _BASE_URL.removesuffix("/v1")

    # Try the router's /fleet for per-backend detail (router-only endpoint).
    try:
        r = httpx.get(f"{base}/fleet", timeout=2.0)
        if r.status_code == 200 and "backends" in r.json():
            return r.json()["backends"]
    except Exception:
        pass

    # Fallback: probe the single endpoint's health.
    try:
        r = httpx.get(f"{base}/health", timeout=2.0)
        status = "ok" if r.status_code == 200 else "error"
        return [{"endpoint": _BASE_URL, "status": status, "http_code": r.status_code}]
    except Exception as exc:
        return [{"endpoint": _BASE_URL, "status": "unreachable", "error": str(exc)}]


def endpoint_count() -> int:
    return len(get_healthy_endpoints())
