"""
Active learning loop.

Items are enqueued when pipeline_confidence < REVIEW_THRESHOLD (set in confidence_stage.py).
A human reviewer can:
  - GET /review/queue          : see pending items sorted by confidence ascending
  - POST /review/{feedback_id} : submit a correction
  - GET /review/stats          : queue stats

Corrections are written back in two ways:
  1. The stored FeedbackAnalysis in feedback_analyses is updated in-place (payload patch)
  2. The corrected item is appended to the few_shot_examples collection so future
     LLM calls benefit from the correction via RAG context in semantic_enrichment

Qdrant collection: `review_queue`
Point payload schema:
    feedback_id    : str
    summary        : str  (from enrichment)
    raw_text       : str  (truncated)
    current_category : str
    current_sentiment : str
    pipeline_confidence : float
    reason         : str  ("low_confidence" | "escalation")
    status         : "pending" | "reviewed" | "skipped"
    queued_at      : float
    reviewed_at    : float | None
    correction     : dict | None
"""

from __future__ import annotations

import time
import uuid

from vectordb.client import ANALYSES_COLLECTION, FEW_SHOT_COLLECTION, get_client
from vectordb.embedder import embed

REVIEW_COLLECTION = "review_queue"


# ── Collection setup ──────────────────────────────────────────────────────────


def _ensure_review_collection(client) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if REVIEW_COLLECTION not in existing:
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        from vectordb.embedder import VECTOR_SIZE

        client.create_collection(
            collection_name=REVIEW_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(
            collection_name=REVIEW_COLLECTION,
            field_name="status",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=REVIEW_COLLECTION,
            field_name="feedback_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )


# ── Enqueue ───────────────────────────────────────────────────────────────────


def enqueue(feedback_id: str, analysis: "FeedbackAnalysis", reason: str = "low_confidence") -> None:  # noqa: F821
    """
    Add a low-confidence analysis to the review queue.
    Silently no-ops if Qdrant is unavailable.
    """
    try:
        client = get_client()
        _ensure_review_collection(client)

        summary = analysis.enrichment.summary
        payload = {
            "feedback_id": feedback_id,
            "summary": summary,
            "raw_text": analysis.normalized.original[:300],
            "current_category": analysis.taxonomy.category,
            "current_subcategory": analysis.taxonomy.subcategory,
            "current_sentiment": analysis.sentiment.sentiment,
            "pipeline_confidence": analysis.pipeline_confidence,
            "reason": reason,
            "status": "pending",
            "queued_at": time.time(),
            "reviewed_at": None,
            "correction": None,
        }
        from qdrant_client.models import PointStruct

        client.upsert(
            collection_name=REVIEW_COLLECTION,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embed(summary),
                    payload=payload,
                )
            ],
        )
    except Exception:
        pass


# ── Queue retrieval ───────────────────────────────────────────────────────────


def get_queue(limit: int = 50, status: str = "pending") -> list[dict]:
    """
    Return pending review items sorted by pipeline_confidence ascending
    (least confident first — highest value to review).
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = get_client()
        _ensure_review_collection(client)
        results, _ = client.scroll(
            collection_name=REVIEW_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="status", match=MatchValue(value=status))]),
            limit=limit,
            with_payload=True,
        )
        payloads = [p.payload for p in results]
        payloads.sort(key=lambda p: p.get("pipeline_confidence", 1.0))
        return payloads
    except Exception:
        return []


def queue_stats() -> dict:
    """Count items per status."""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = get_client()
        _ensure_review_collection(client)
        stats = {}
        for status in ("pending", "reviewed", "skipped"):
            results, _ = client.scroll(
                collection_name=REVIEW_COLLECTION,
                scroll_filter=Filter(must=[FieldCondition(key="status", match=MatchValue(value=status))]),
                limit=1,
                with_payload=False,
            )
            # scroll returns actual items; for count we use count()
            stats[status] = client.count(
                collection_name=REVIEW_COLLECTION,
                count_filter=Filter(must=[FieldCondition(key="status", match=MatchValue(value=status))]),
            ).count
        return stats
    except Exception:
        return {}


# ── Submit correction ─────────────────────────────────────────────────────────


def submit_correction(
    feedback_id: str,
    corrected_category: str | None = None,
    corrected_subcategory: str | None = None,
    corrected_sentiment: str | None = None,
    reviewer_note: str = "",
) -> dict:
    """
    Apply a human correction:
      1. Update review_queue item status → "reviewed"
      2. Patch feedback_analyses payload with corrected fields
      3. Add corrected item to few_shot_examples for future RAG context

    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = get_client()

        correction = {
            k: v
            for k, v in {
                "corrected_category": corrected_category,
                "corrected_subcategory": corrected_subcategory,
                "corrected_sentiment": corrected_sentiment,
                "reviewer_note": reviewer_note,
            }.items()
            if v is not None
        }

        # 1. Mark as reviewed in the queue
        client.set_payload(
            collection_name=REVIEW_COLLECTION,
            payload={"status": "reviewed", "reviewed_at": time.time(), "correction": correction},
            points=Filter(must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]),
        )

        # 2. Patch the original analysis in feedback_analyses
        patch: dict = {}
        if corrected_category:
            patch["category"] = corrected_category
        if corrected_subcategory:
            patch["subcategory"] = corrected_subcategory
        if corrected_sentiment:
            patch["sentiment"] = corrected_sentiment
        if patch:
            client.set_payload(
                collection_name=ANALYSES_COLLECTION,
                payload=patch,
                points=Filter(must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]),
            )

        # 3. Add to few_shot_examples so future analyses benefit.
        # Re-fetch the just-reviewed item to get its summary.
        reviewed, _ = client.scroll(
            collection_name=REVIEW_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]),
            limit=1,
            with_payload=True,
        )
        if reviewed:
            p = reviewed[0].payload
            summary = p.get("summary", "")
            category = corrected_category or p.get("current_category", "Other")
            sentiment = corrected_sentiment or p.get("current_sentiment", "neutral")
            from qdrant_client.models import PointStruct

            client.upsert(
                collection_name=FEW_SHOT_COLLECTION,
                points=[
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=embed(summary),
                        payload={
                            "feedback_id": feedback_id,
                            "summary": summary,
                            "category": category,
                            "sentiment": sentiment,
                            "source": "human_correction",
                            "added_at": time.time(),
                        },
                    )
                ],
            )

        return {"ok": True, "feedback_id": feedback_id, "correction": correction}
    except Exception as e:
        return {"ok": False, "error": str(e)}
