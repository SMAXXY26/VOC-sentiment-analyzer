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

    try:
        from vectordb.store import store_analysis
        analysis = FeedbackAnalysis(
            normalized=ctx["normalized"],
            redacted=ctx["redacted"],
            enrichment=ctx["enrichment"],
            taxonomy=ctx["taxonomy"],
            sentiment=ctx["sentiment"],
            signals=ctx["signals"],
            risk=ctx["risk"],
            executive=ctx["executive"],
        )
        store_analysis(
            feedback_id=feedback_id,
            raw_text=ctx["normalized"].original,
            analysis=analysis,
            source=ctx.get("source", "unknown"),
        )
    except Exception:
        pass  # never block pipeline if vector DB is unavailable
    return ctx


store_result_stage = RunnableLambda(_store)
