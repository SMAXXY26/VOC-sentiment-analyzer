"""Durable retry buffer for Qdrant writes.

Before this, store_result_stage swallowed Qdrant failures with `except: pass` —
when Qdrant was down, completed analyses were silently lost (never stored, so
absent from dedup/RAG/clustering forever). The analysis still completes (we don't
re-run the LLM), but the write is now appended to a local JSONL buffer and replayed
on the next successful store, so nothing is dropped just because Qdrant blipped.

The buffer is a single append-only JSONL file guarded by a process-level lock.
It is best-effort: if even the local write fails we give up (same as before), but
that is far rarer than a transient Qdrant outage.
"""
from __future__ import annotations

import json
import os
import threading

from ..schemas import FeedbackAnalysis

BUFFER_PATH = os.getenv("STORE_BUFFER_PATH", "/tmp/cx_store_buffer.jsonl")

_lock = threading.Lock()


def _set_pending_gauge(n: int) -> None:
    """Publish the pending count if prometheus_client is available (optional dep)."""
    try:
        from prometheus_client import Gauge

        global _GAUGE
        try:
            _GAUGE
        except NameError:
            _GAUGE = Gauge("store_retry_pending", "Analyses buffered awaiting Qdrant retry")
        _GAUGE.set(n)
    except Exception:
        pass


def buffer_failed_store(feedback_id: str, raw_text: str, analysis: FeedbackAnalysis, source: str) -> None:
    """Append a failed Qdrant write to the local buffer for later replay."""
    record = {
        "feedback_id": feedback_id,
        "raw_text": raw_text,
        "source": source,
        "analysis_json": analysis.model_dump_json(),
    }
    try:
        with _lock:
            with open(BUFFER_PATH, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        _set_pending_gauge(pending_count())
    except Exception:
        pass  # local disk also unavailable — nothing more we can do


def pending_count() -> int:
    try:
        with open(BUFFER_PATH) as fh:
            return sum(1 for line in fh if line.strip())
    except FileNotFoundError:
        return 0
    except Exception:
        return 0


def flush_store_buffer() -> int:
    """Replay buffered writes into Qdrant. Returns how many were successfully stored.

    Records that still fail are kept for the next attempt. Called opportunistically
    after a successful live store (so we only retry when Qdrant is clearly back).
    """
    with _lock:
        try:
            with open(BUFFER_PATH) as fh:
                lines = [ln for ln in fh if ln.strip()]
        except FileNotFoundError:
            return 0
        except Exception:
            return 0

        if not lines:
            return 0

        from vectordb.store import store_analysis

        stored = 0
        still_failed: list[str] = []
        for ln in lines:
            try:
                rec = json.loads(ln)
                analysis = FeedbackAnalysis.model_validate_json(rec["analysis_json"])
                store_analysis(
                    feedback_id=rec["feedback_id"],
                    raw_text=rec["raw_text"],
                    analysis=analysis,
                    source=rec.get("source", "unknown"),
                )
                stored += 1
            except Exception:
                still_failed.append(ln)  # Qdrant still down or record unusable

        try:
            if still_failed:
                with open(BUFFER_PATH, "w") as fh:
                    fh.writelines(still_failed)
            else:
                os.remove(BUFFER_PATH)
        except Exception:
            pass

    _set_pending_gauge(len(still_failed))
    return stored
