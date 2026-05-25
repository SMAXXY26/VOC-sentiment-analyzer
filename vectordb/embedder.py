import asyncio
from functools import lru_cache
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(_MODEL_NAME)


def embed(text: str) -> list[float]:
    """Synchronous embed — safe to call from sync pipeline stages and threadpool handlers."""
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    return _model().encode(texts, normalize_embeddings=True).tolist()


async def embed_async(text: str) -> list[float]:
    """Non-blocking embed for use inside async FastAPI route handlers.
    Runs the CPU-bound encode() in a thread so the event loop is not blocked.
    """
    return await asyncio.to_thread(embed, text)


VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension
