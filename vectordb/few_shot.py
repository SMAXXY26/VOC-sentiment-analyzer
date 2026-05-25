"""
Seed and manage curated few-shot examples in Qdrant.
Run directly to seed: python -m vectordb.few_shot
"""
import json
import uuid
from pathlib import Path

from qdrant_client.models import PointStruct

from .client import get_client, FEW_SHOT_COLLECTION
from .embedder import embed

_SEEDS_FILE = Path(__file__).parent / "seeds" / "examples.json"


def seed_few_shot_examples(examples: list[dict] | None = None) -> int:
    if examples is None:
        with open(_SEEDS_FILE) as f:
            examples = json.load(f)

    client = get_client()
    points = []
    for ex in examples:
        vector = embed(ex["text"])
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=ex,
        ))

    client.upsert(collection_name=FEW_SHOT_COLLECTION, points=points)
    return len(points)


def get_few_shot_examples(text: str, k: int = 3, category: str | None = None) -> list[dict]:
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = get_client()
        vector = embed(text)
        query_filter = None
        if category:
            query_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )
        hits = client.search(
            collection_name=FEW_SHOT_COLLECTION,
            query_vector=vector,
            limit=k,
            query_filter=query_filter,
            score_threshold=0.5,
        )
        return [h.payload for h in hits]
    except Exception:
        return []


if __name__ == "__main__":
    count = seed_few_shot_examples()
    print(f"Seeded {count} few-shot examples into Qdrant.")
