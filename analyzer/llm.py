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
from functools import lru_cache
from itertools import cycle
from threading import Lock

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


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
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """
    Return a ChatOpenAI instance pointed at the next vLLM endpoint (round-robin).
    With a single endpoint this is equivalent to the original lru_cache singleton.
    """
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
