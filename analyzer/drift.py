"""
Semantic drift detection.

Detects when the topic or sentiment distribution of incoming feedback shifts
significantly from the historical baseline.

Three drift signals:
  1. Embedding centroid drift
     Cosine distance between the centroid of recent embeddings and the
     baseline centroid. Flags when distance > CENTROID_THRESHOLD (0.10).

  2. Sentiment distribution shift
     Absolute change in the fraction of negative feedback between windows.
     Flags when shift > SENTIMENT_THRESHOLD (0.15 = 15 percentage points).

  3. Category entropy shift
     KL divergence of category distribution between windows.
     Flags when KL > ENTROPY_THRESHOLD (0.3).

Windows:
  - recent_days  (default 7)  : feedback from the last N days
  - baseline_days (default 30) : prior M days (non-overlapping)

Results are stored in the `drift_snapshots` Qdrant collection so drift
can be tracked over time. Each snapshot embeds the summary text.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from typing import Optional

import numpy as np

from vectordb.client import get_client
from vectordb.retrieval import export_embeddings

CENTROID_THRESHOLD = float(0.10)
SENTIMENT_THRESHOLD = float(0.15)
ENTROPY_THRESHOLD = float(0.30)
DRIFT_COLLECTION = "drift_snapshots"


# ── Math helpers ──────────────────────────────────────────────────────────────

def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / (na * nb))


def _centroid(vectors: list[list[float]]) -> Optional[np.ndarray]:
    if not vectors:
        return None
    return np.mean(np.array(vectors, dtype=np.float32), axis=0)


def _sentiment_negative_rate(payloads: list[dict]) -> float:
    if not payloads:
        return 0.0
    neg = sum(1 for p in payloads if p.get("sentiment") == "negative")
    return neg / len(payloads)


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL(P||Q) — categories present in P but absent in Q contribute a large penalty."""
    keys = set(p) | set(q)
    kl = 0.0
    for k in keys:
        pk = p.get(k, 1e-9)
        qk = q.get(k, 1e-9)
        kl += pk * math.log(pk / qk)
    return float(kl)


def _category_dist(payloads: list[dict]) -> dict[str, float]:
    counts = Counter(p.get("category", "Other") for p in payloads)
    total = sum(counts.values()) or 1
    return {cat: count / total for cat, count in counts.items()}


# ── Drift snapshot storage ────────────────────────────────────────────────────

def _ensure_drift_collection(client) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if DRIFT_COLLECTION not in existing:
        from qdrant_client.models import Distance, VectorParams

        from vectordb.embedder import VECTOR_SIZE
        client.create_collection(
            collection_name=DRIFT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def _store_snapshot(snapshot: dict) -> None:
    try:
        import uuid

        from qdrant_client.models import PointStruct

        from vectordb.embedder import embed
        client = get_client()
        _ensure_drift_collection(client)
        summary = (
            f"Drift detected={snapshot['drift_detected']} "
            f"centroid={snapshot['centroid_distance']:.3f} "
            f"sentiment_shift={snapshot['sentiment_shift']:.3f}"
        )
        client.upsert(
            collection_name=DRIFT_COLLECTION,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=embed(summary),
                payload={**snapshot, "stored_at": time.time()},
            )],
        )
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_drift(recent_days: int = 7, baseline_days: int = 30) -> dict:
    """
    Compare the recent window against the baseline window and return a drift report.

    Returns:
    {
        "drift_detected": bool,
        "centroid_distance": float,   # 0 = identical, 1 = orthogonal
        "centroid_alert": bool,
        "sentiment_shift": float,     # fraction shift in negative rate
        "sentiment_alert": bool,
        "category_kl": float,         # KL divergence of category distributions
        "category_alert": bool,
        "recent_n": int,
        "baseline_n": int,
        "computed_at": float,
    }
    """
    now = time.time()
    recent_since   = now - recent_days * 86400
    baseline_since = now - (recent_days + baseline_days) * 86400
    baseline_until = recent_since

    # Fetch both windows
    recent_vecs, recent_payloads = export_embeddings(limit=2000, since_ts=recent_since)
    baseline_vecs, baseline_payloads = export_embeddings(limit=5000, since_ts=baseline_since)

    # Filter baseline to its window (export_embeddings only has a since_ts filter)
    baseline_vecs = [
        v for v, p in zip(baseline_vecs, baseline_payloads)
        if p.get("stored_at", 0) <= baseline_until
    ]
    baseline_payloads = [
        p for p in baseline_payloads
        if p.get("stored_at", 0) <= baseline_until
    ]

    if not recent_vecs or not baseline_vecs:
        return {
            "drift_detected": False,
            "error": "Insufficient data for drift analysis",
            "recent_n": len(recent_vecs),
            "baseline_n": len(baseline_vecs),
            "computed_at": now,
        }

    # 1. Centroid drift
    rc = _centroid(recent_vecs)
    bc = _centroid(baseline_vecs)
    centroid_dist = _cosine_distance(rc, bc)
    centroid_alert = centroid_dist > CENTROID_THRESHOLD

    # 2. Sentiment shift
    recent_neg   = _sentiment_negative_rate(recent_payloads)
    baseline_neg = _sentiment_negative_rate(baseline_payloads)
    sentiment_shift = abs(recent_neg - baseline_neg)
    sentiment_alert = sentiment_shift > SENTIMENT_THRESHOLD

    # 3. Category entropy
    recent_cat_dist   = _category_dist(recent_payloads)
    baseline_cat_dist = _category_dist(baseline_payloads)
    cat_kl = _kl_divergence(recent_cat_dist, baseline_cat_dist)
    cat_alert = cat_kl > ENTROPY_THRESHOLD

    drift_detected = centroid_alert or sentiment_alert or cat_alert

    snapshot = {
        "drift_detected": drift_detected,
        "centroid_distance": round(centroid_dist, 4),
        "centroid_alert": centroid_alert,
        "sentiment_shift": round(sentiment_shift, 4),
        "sentiment_alert": sentiment_alert,
        "recent_negative_rate": round(recent_neg, 4),
        "baseline_negative_rate": round(baseline_neg, 4),
        "category_kl": round(cat_kl, 4),
        "category_alert": cat_alert,
        "recent_n": len(recent_vecs),
        "baseline_n": len(baseline_vecs),
        "recent_days": recent_days,
        "baseline_days": baseline_days,
        "computed_at": now,
    }

    _store_snapshot(snapshot)
    return snapshot


def get_drift_history(limit: int = 30) -> list[dict]:
    """Fetch stored drift snapshots, newest first."""
    try:
        client = get_client()
        _ensure_drift_collection(client)
        results, _ = client.scroll(
            collection_name=DRIFT_COLLECTION,
            limit=limit,
            with_payload=True,
        )
        payloads = [p.payload for p in results]
        payloads.sort(key=lambda p: p.get("computed_at", 0), reverse=True)
        return payloads
    except Exception:
        return []
