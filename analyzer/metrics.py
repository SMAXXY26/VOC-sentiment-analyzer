"""Prometheus metrics for the analyzer pipeline.

Until now only the Rust producer/consumer exposed metrics (queue concurrency).
The Python analyzer was a black box — no latency percentiles, no cache visibility.
This module defines the analyzer-side metric objects; `api.py` mounts /metrics and
`main.py` + the pipeline stages record into them.

Histogram buckets are tuned for LLM-pipeline latencies (seconds, not milliseconds):
a single /analyze runs ~6-8 LLM calls so end-to-end p95 is multiple seconds.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from prometheus_client import Counter, Histogram

# Buckets in seconds — spread across the realistic LLM-pipeline latency range.
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0)

# Per-stage wall time (label distinguishes normalization / taxonomy / etc.).
PIPELINE_STAGE_DURATION = Histogram(
    "pipeline_stage_duration_seconds",
    "Wall-clock duration of a single pipeline stage",
    labelnames=("stage",),
    buckets=_LATENCY_BUCKETS,
)

# Full analyze_single wall time, split by whether the dedup cache short-circuited.
PIPELINE_REQUEST_DURATION = Histogram(
    "pipeline_request_duration_seconds",
    "End-to-end duration of analyze_single",
    labelnames=("outcome",),  # "cache_hit" | "computed"
    buckets=_LATENCY_BUCKETS,
)

# Dedup short-circuit accounting (the real cache lives in main.analyze_single).
DEDUP_CACHE_HITS = Counter(
    "dedup_cache_hits_total",
    "Feedback items served from a cached duplicate analysis (no LLM calls)",
)
DEDUP_CACHE_MISSES = Counter(
    "dedup_cache_misses_total",
    "Feedback items with no cached duplicate — full pipeline ran",
)


@contextmanager
def stage_timer(stage: str):
    """Record the wall time of a `with` block into the per-stage histogram."""
    start = time.perf_counter()
    try:
        yield
    finally:
        PIPELINE_STAGE_DURATION.labels(stage=stage).observe(time.perf_counter() - start)


def timed_stage(name: str, runnable):
    """Wrap an LCEL runnable so each invocation records into PIPELINE_STAGE_DURATION.

    Returns a RunnableLambda preserving the dict-in/dict-out contract, so it composes
    with `|` exactly like the original stage.
    """
    from langchain_core.runnables import RunnableLambda

    def _invoke(ctx: dict) -> dict:
        with stage_timer(name):
            return runnable.invoke(ctx)

    return RunnableLambda(_invoke)
