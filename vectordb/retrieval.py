"""
Advanced vector DB retrieval patterns over the feedback_analyses collection.

Complements vectordb/store.py (which handles pipeline-level reads/writes).
This module provides richer query patterns: filtered search, time-window
retrieval, batch get, and embedding export for clustering/drift analysis.
"""

from __future__ import annotations

import time
from typing import Optional

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Range,
)

from .client import ANALYSES_COLLECTION, get_client
from .embedder import embed

# ── Filtered semantic search ───────────────────────────────────────────────────


def filtered_search(
    query: str,
    k: int = 10,
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
    risk_level: Optional[str] = None,
    escalate: Optional[bool] = None,
    churn_risk: Optional[bool] = None,
    min_intensity: Optional[int] = None,
) -> list[dict]:
    """
    Semantic search with optional payload filters.
    All filters are ANDed together. Unset filters are ignored.
    Returns dicts with score + full payload.
    """
    try:
        conditions = []
        if category:
            conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if sentiment:
            conditions.append(FieldCondition(key="sentiment", match=MatchValue(value=sentiment)))
        if risk_level:
            conditions.append(FieldCondition(key="risk_level", match=MatchValue(value=risk_level)))
        if escalate is not None:
            conditions.append(FieldCondition(key="escalate", match=MatchValue(value=escalate)))
        if churn_risk is not None:
            conditions.append(FieldCondition(key="churn_risk", match=MatchValue(value=churn_risk)))
        if min_intensity is not None:
            conditions.append(FieldCondition(key="intensity", range=Range(gte=min_intensity)))

        query_filter = Filter(must=conditions) if conditions else None
        vector = embed(query)
        client = get_client()
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            query_filter=query_filter,
            limit=k,
        )
        return [{"score": h.score, **h.payload} for h in hits]
    except Exception:
        return []


# ── Time-window retrieval ─────────────────────────────────────────────────────


def time_window_search(
    query: str,
    since_ts: float,
    until_ts: Optional[float] = None,
    k: int = 20,
) -> list[dict]:
    """
    Semantic search restricted to a Unix-timestamp window.
    Requires feedback points to have a 'stored_at' float payload field.
    Falls back to unfiltered search if field is absent.
    """
    until_ts = until_ts or time.time()
    try:
        conditions = [FieldCondition(key="stored_at", range=Range(gte=since_ts, lte=until_ts))]
        vector = embed(query)
        client = get_client()
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            query_filter=Filter(must=conditions),
            limit=k,
        )
        return [{"score": h.score, **h.payload} for h in hits]
    except Exception:
        return []


# ── Batch get by feedback_id ──────────────────────────────────────────────────


def batch_get(feedback_ids: list[str]) -> list[dict]:
    """Fetch multiple analyses by feedback_id. Returns found payloads (missing IDs silently skipped)."""
    if not feedback_ids:
        return []
    try:
        client = get_client()
        results, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="feedback_id", match=MatchAny(any=feedback_ids))]),
            limit=len(feedback_ids),
            with_payload=True,
        )
        return [p.payload for p in results]
    except Exception:
        return []


# ── Embedding export for clustering / drift ───────────────────────────────────


def export_embeddings(
    limit: int = 2000,
    since_ts: Optional[float] = None,
) -> tuple[list[list[float]], list[dict]]:
    """
    Fetch raw embedding vectors + payloads from Qdrant.
    Returns (vectors, payloads) — parallel lists.
    Used by clustering and drift detection modules.
    """
    try:
        client = get_client()
        conditions = []
        if since_ts is not None:
            conditions.append(FieldCondition(key="stored_at", range=Range(gte=since_ts)))

        query_filter = Filter(must=conditions) if conditions else None
        results, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )
        vectors = [list(p.vector) for p in results if p.vector is not None]
        payloads = [p.payload for p in results if p.vector is not None]
        return vectors, payloads
    except Exception:
        return [], []


# ── Nearest neighbours for a stored point ────────────────────────────────────


def nearest_to(feedback_id: str, k: int = 5) -> list[dict]:
    """Find k most similar stored analyses to a given feedback_id."""
    try:
        client = get_client()
        results, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]),
            limit=1,
            with_vectors=True,
        )
        if not results or results[0].vector is None:
            return []
        vector = list(results[0].vector)
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            limit=k + 1,  # +1 because the point itself is returned
        )
        return [{"score": h.score, **h.payload} for h in hits if h.payload.get("feedback_id") != feedback_id][:k]
    except Exception:
        return []
