import asyncio
import logging
import os
from functools import lru_cache

import httpx
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDER_URL = os.getenv("EMBEDDER_URL", "").rstrip("/")
_log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(_MODEL_NAME)


@lru_cache(maxsize=1)
def _http_client() -> httpx.Client:
    return httpx.Client(timeout=2.0)


@lru_cache(maxsize=1)
def _async_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=2.0)


def embed(text: str) -> list[float]:
    """Synchronous embed — safe to call from sync pipeline stages and threadpool handlers."""
    if _EMBEDDER_URL:
        try:
            r = _http_client().post(f"{_EMBEDDER_URL}/embed", json={"text": text})
            r.raise_for_status()
            return r.json()["embedding"]
        except Exception as exc:
            _log.warning("embedder service unreachable (%s), falling back to CPU", exc)
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    if _EMBEDDER_URL:
        try:
            r = _http_client().post(f"{_EMBEDDER_URL}/embed/batch", json={"texts": texts})
            r.raise_for_status()
            return r.json()["embeddings"]
        except Exception as exc:
            _log.warning("embedder service unreachable (%s), falling back to CPU", exc)
    return _model().encode(texts, normalize_embeddings=True).tolist()


async def embed_async(text: str) -> list[float]:
    """Non-blocking embed for use inside async FastAPI route handlers."""
    if _EMBEDDER_URL:
        try:
            r = await _async_http_client().post(f"{_EMBEDDER_URL}/embed", json={"text": text})
            r.raise_for_status()
            return r.json()["embedding"]
        except Exception as exc:
            _log.warning("embedder service unreachable (%s), falling back to CPU", exc)
    return await asyncio.to_thread(embed, text)


VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension
