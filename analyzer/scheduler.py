"""Semantic request scheduler — reorders a batch to maximize vLLM prefix-cache hits.

We cannot reach into vLLM's KV cache directly. What we *can* do is control the order
in which prompts are sent. vLLM's automatic prefix caching (`--enable-prefix-caching`)
keeps the KV blocks of a shared prompt prefix resident and reuses them for the next
request that starts with the same tokens. Every analysis here shares a long, identical
prefix (the system prompt + few-shot RAG context for similar feedback), so sending
semantically *similar* items back-to-back keeps that prefix hot and skips recomputing
it — fewer prefill FLOPs, higher throughput.

`semantic_order` greedily builds a nearest-neighbour chain over the items' embeddings:
start at the first item, then repeatedly append the unused item most similar to the
last one. O(n²) in the number of items — fine for batch sizes in the hundreds; for
much larger batches you'd switch to a clustering or ANN approach.

The win is observable as a higher prefix-cache hit rate on vLLM's own metrics
(`vllm:gpu_prefix_cache_hit_rate`) and via the pipeline cache-hit panels added in the
observability pass.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence


def semantic_order(
    texts: Sequence[str],
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[int]:
    """Return a permutation of indices ordering `texts` by semantic adjacency.

    embed_fn defaults to vectordb.embedder.embed_batch; inject a stub in tests.
    Returns identity order for trivially small inputs or if embedding fails.
    """
    n = len(texts)
    if n <= 2:
        return list(range(n))

    if embed_fn is None:
        from vectordb.embedder import embed_batch as embed_fn  # noqa: N806

    try:
        import numpy as np

        vecs = np.asarray(embed_fn(list(texts)), dtype=float)
        if vecs.ndim != 2 or vecs.shape[0] != n:
            return list(range(n))
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        sim = vecs @ vecs.T  # cosine similarity matrix (unit vectors)

        order = [0]
        used = {0}
        for _ in range(n - 1):
            sims = sim[order[-1]].copy()
            sims[list(used)] = -np.inf
            nxt = int(np.argmax(sims))
            order.append(nxt)
            used.add(nxt)
        return order
    except Exception:
        # Never let scheduling break a batch run — fall back to original order.
        return list(range(n))


def schedule(items: Sequence, key=lambda x: x, embed_fn=None) -> list:
    """Reorder `items` by semantic adjacency of key(item) (a str). Returns a new list."""
    order = semantic_order([key(it) for it in items], embed_fn=embed_fn)
    return [items[i] for i in order]
