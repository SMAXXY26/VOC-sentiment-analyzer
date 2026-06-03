"""Durable retry lane for failed Qdrant writes, backed by Kafka (Redpanda).

Replaces the earlier local JSONL file buffer, which had real durability gaps:
  - /tmp is ephemeral, so a pod restart lost exactly the data the failsafe existed
    to protect;
  - a threading.Lock only coordinates within one process, so multiple uvicorn
    workers or pod replicas would corrupt a shared file;
  - the file grew unbounded.

The platform already runs Kafka, so the industry-standard move is to reuse it:
when store_result_stage can't reach Qdrant, the completed analysis is published to
`feedback.store_retry` (durable, replayable, partitioned). A background consumer
thread in the analyzer drains that topic and re-attempts the store, committing the
offset only after a successful write — so while Qdrant is down, messages are simply
redelivered (at-least-once), and nothing is lost across restarts.

Everything here is optional and defensive: if KAFKA_BROKERS is unset or kafka-python
isn't installed, publish/consume become no-ops and the caller falls back to the local
buffer (analyzer/pipeline/store_buffer.py) as a last resort.
"""

from __future__ import annotations

import json
import os
import threading
import time

from .schemas import FeedbackAnalysis

STORE_RETRY_TOPIC = os.getenv("STORE_RETRY_TOPIC", "feedback.store_retry")
_BROKERS = os.getenv("KAFKA_BROKERS", "")

_producer = None
_producer_lock = threading.Lock()
_consumer_started = False


def _kafka_enabled() -> bool:
    return bool(_BROKERS.strip())


def _get_producer():
    """Lazily build a singleton KafkaProducer; None if Kafka is unavailable."""
    global _producer
    if not _kafka_enabled():
        return None
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is None:
            try:
                from kafka import KafkaProducer

                _producer = KafkaProducer(
                    bootstrap_servers=_BROKERS.split(","),
                    value_serializer=lambda v: json.dumps(v).encode(),
                    acks="all",  # durability over latency for the retry lane
                    retries=3,
                    linger_ms=10,
                )
            except Exception:
                _producer = None
    return _producer


def publish_store_retry(feedback_id: str, raw_text: str, analysis: FeedbackAnalysis, source: str) -> bool:
    """Publish a failed store to the retry topic. Returns True if enqueued durably."""
    producer = _get_producer()
    if producer is None:
        return False
    try:
        producer.send(
            STORE_RETRY_TOPIC,
            {
                "feedback_id": feedback_id,
                "raw_text": raw_text,
                "source": source,
                "analysis_json": analysis.model_dump_json(),
            },
        )
        producer.flush(timeout=5)
        return True
    except Exception:
        return False


def _try_store(rec: dict) -> bool:
    """Attempt one Qdrant write. False means Qdrant is still unreachable (retry)."""
    try:
        from vectordb.store import store_analysis

        analysis = FeedbackAnalysis.model_validate_json(rec["analysis_json"])
        store_analysis(
            feedback_id=rec["feedback_id"],
            raw_text=rec["raw_text"],
            analysis=analysis,
            source=rec.get("source", "unknown"),
        )
        return True
    except KeyError:
        # Malformed record can never succeed — drop it (return True to commit past it).
        return True
    except Exception:
        return False


def _consume_loop() -> None:
    from kafka import KafkaConsumer

    consumer = KafkaConsumer(
        STORE_RETRY_TOPIC,
        bootstrap_servers=_BROKERS.split(","),
        group_id=os.getenv("STORE_RETRY_GROUP", "store-retry"),
        enable_auto_commit=False,  # commit only after a successful store
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    backoff = 1.0
    for msg in consumer:
        # Block on this record until Qdrant accepts it, then commit and move on.
        # While Qdrant is down the retry lane simply waits — at-least-once, no loss.
        while not _try_store(msg.value):
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        backoff = 1.0
        try:
            consumer.commit()
        except Exception:
            pass  # next poll re-attempts; store is idempotent on feedback_id


def start_retry_consumer() -> bool:
    """Start the background retry-drain thread once. No-op if Kafka is disabled."""
    global _consumer_started
    if _consumer_started or not _kafka_enabled():
        return False
    try:
        import kafka  # noqa: F401
    except Exception:
        return False
    _consumer_started = True
    threading.Thread(target=_consume_loop, name="store-retry", daemon=True).start()
    return True
