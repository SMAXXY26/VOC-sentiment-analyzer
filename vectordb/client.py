import os
from functools import lru_cache

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from .embedder import VECTOR_SIZE

load_dotenv()

ANALYSES_COLLECTION = "feedback_analyses"
FEW_SHOT_COLLECTION = "few_shot_examples"


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=url)
    _ensure_collections(client)
    return client


def _ensure_collections(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}

    if ANALYSES_COLLECTION not in existing:
        client.create_collection(
            collection_name=ANALYSES_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(
            collection_name=ANALYSES_COLLECTION,
            field_name="escalate",
            field_schema=PayloadSchemaType.BOOL,
        )
        client.create_payload_index(
            collection_name=ANALYSES_COLLECTION,
            field_name="source",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    if FEW_SHOT_COLLECTION not in existing:
        client.create_collection(
            collection_name=FEW_SHOT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        client.create_payload_index(
            collection_name=FEW_SHOT_COLLECTION,
            field_name="category",
            field_schema=PayloadSchemaType.KEYWORD,
        )
