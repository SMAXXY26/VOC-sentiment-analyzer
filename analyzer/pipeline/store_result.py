from langchain_core.runnables import RunnableLambda

from ..schemas import FeedbackAnalysis


def _store(ctx: dict) -> dict:
    # feedback_id must be set by analyze_single before pipeline.invoke().
    # We no longer generate a random UUID here — that broke traceability because
    # each call to store_result would produce a different ID for the same analysis.
    feedback_id = ctx.get("feedback_id")
    if not feedback_id:
        import warnings

        warnings.warn(
            "store_result: 'feedback_id' missing from pipeline context — analysis will not be stored.",
            stacklevel=2,
        )
        return ctx

    # Build the analysis object outside the Qdrant try so a store failure can
    # still buffer it for retry (analysis is complete; only the write failed).
    analysis = FeedbackAnalysis(
        normalized=ctx["normalized"],
        redacted=ctx["redacted"],
        enrichment=ctx["enrichment"],
        taxonomy=ctx["taxonomy"],
        sentiment=ctx["sentiment"],
        signals=ctx["signals"],
        risk=ctx["risk"],
        executive=ctx["executive"],
        experience=ctx.get("experience"),
        pipeline_confidence=ctx.get("pipeline_confidence"),
        needs_review=ctx.get("needs_review"),
    )
    raw_text = ctx["normalized"].original
    source = ctx.get("source", "unknown")

    try:
        from vectordb.store import store_analysis

        store_analysis(
            feedback_id=feedback_id,
            raw_text=raw_text,
            analysis=analysis,
            source=source,
        )
        # Qdrant is reachable — opportunistically drain any local fallback buffer.
        try:
            from .store_buffer import flush_store_buffer

            flush_store_buffer()
        except Exception:
            pass
    except Exception:
        # Qdrant unavailable: never lose the analysis. Prefer the durable Kafka retry
        # lane (survives restarts, multi-replica safe); only if Kafka is also down/
        # disabled do we fall back to the best-effort local file buffer.
        enqueued = False
        try:
            from ..store_retry import publish_store_retry

            enqueued = publish_store_retry(feedback_id, raw_text, analysis, source)
        except Exception:
            enqueued = False
        if not enqueued:
            try:
                from .store_buffer import buffer_failed_store

                buffer_failed_store(feedback_id, raw_text, analysis, source)
            except Exception:
                pass  # never block the pipeline
    return ctx


store_result_stage = RunnableLambda(_store)
