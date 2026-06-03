"""
High-level vector DB operations used by the pipeline.
All public functions gracefully degrade if Qdrant is unreachable.
"""
import uuid
from typing import TYPE_CHECKING, Optional

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from .client import ANALYSES_COLLECTION, get_client
from .embedder import embed

if TYPE_CHECKING:
    # Imported only for type checking — at runtime this would be a circular import
    # (analyzer.schemas → ... → vectordb). The annotations below are strings.
    from analyzer.schemas import FeedbackAnalysis


def store_analysis(
    feedback_id: str,
    raw_text: str,
    analysis: "FeedbackAnalysis",  # type: ignore[name-defined]
    source: str = "unknown",
) -> None:
    try:
        client = get_client()
        summary = analysis.enrichment.summary
        vector = embed(raw_text)  # must match find_duplicates() which embeds raw_text
        payload = {
            "feedback_id": feedback_id,
            "source": source,
            "summary": summary,
            "raw_text": raw_text[:500],  # truncate to avoid large payloads
            "category": analysis.taxonomy.category,
            "subcategory": analysis.taxonomy.subcategory,
            "sentiment": analysis.sentiment.sentiment,
            "intensity": analysis.sentiment.intensity,
            "escalate": analysis.risk.escalate,
            "risk_level": analysis.risk.risk_level,
            "churn_risk": analysis.signals.churn_risk,
            "feature_requests": analysis.signals.feature_requests,
            "emotions": analysis.sentiment.emotions,
            # Full serialized analysis — used by the dedup short-circuit in analyze_single
            "analysis_json": analysis.model_dump_json(),
        }
        client.upsert(
            collection_name=ANALYSES_COLLECTION,
            points=[PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)],
        )
    except Exception:
        pass  # never block the pipeline if Qdrant is unavailable


def find_duplicates(raw_text: str, threshold: float = 0.95) -> list[str]:
    try:
        client = get_client()
        vector = embed(raw_text)
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            limit=3,
            score_threshold=threshold,
        )
        return [h.payload["feedback_id"] for h in hits]
    except Exception:
        return []


def get_rag_context(text: str, k: int = 3) -> list[dict]:
    try:
        client = get_client()
        vector = embed(text)
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            limit=k,
            score_threshold=0.6,
        )
        return [h.payload for h in hits]
    except Exception:
        return []


def get_escalation_precedents(k: int = 3) -> list[dict]:
    # Fixed: was using search() with a zero-vector + filter which is semantically wrong
    # (ANN over a meaningless zero vector). scroll() with a filter is the correct API.
    try:
        client = get_client()
        results, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(key="escalate", match=MatchValue(value=True))]
            ),
            limit=k,
            with_payload=True,
        )
        return [p.payload for p in results]
    except Exception:
        return []


def get_feature_history(k: int = 20) -> list[str]:
    try:
        client = get_client()
        results = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            limit=k,
            with_payload=["feature_requests"],
        )
        features = []
        for point in results[0]:
            features.extend(point.payload.get("feature_requests", []))
        from collections import Counter
        return [f for f, _ in Counter(features).most_common(5)]
    except Exception:
        return []


def get_analysis_by_id(feedback_id: str) -> "Optional[FeedbackAnalysis]":
    """Fetch a previously stored FeedbackAnalysis by feedback_id (used by dedup short-circuit)."""
    try:
        client = get_client()
        results = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]
            ),
            limit=1,
            with_payload=True,
        )
        points = results[0]
        if points and "analysis_json" in points[0].payload:
            from analyzer.schemas import FeedbackAnalysis
            return FeedbackAnalysis.model_validate_json(points[0].payload["analysis_json"])
    except Exception:
        pass
    return None


def search(query: str, k: int = 10) -> list[dict]:
    try:
        client = get_client()
        vector = embed(query)
        hits = client.search(
            collection_name=ANALYSES_COLLECTION,
            query_vector=vector,
            limit=k,
        )
        return [{"score": h.score, **h.payload} for h in hits]
    except Exception:
        return []


if __name__ == "__main__":
    import json
    import sys
    query = " ".join(sys.argv[1:]) or "billing issue"
    results = search(query)
    print(json.dumps(results, indent=2))
