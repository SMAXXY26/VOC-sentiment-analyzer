"""
Confidence scoring stage.

Runs after all LLM stages, before store_result_stage.
Computes a single pipeline_confidence float (0.0–1.0) from three signals:

  1. taxonomy_confidence (0.4 weight)
     The LLM's own confidence in its category classification.

  2. sentiment_consistency (0.3 weight)
     Does the stated sentiment match the intensity score?
     - positive + high intensity = consistent (e.g. very happy)
     - negative + high intensity = consistent (e.g. very angry)
     - neutral + any intensity   = partially consistent
     Inconsistent combos (e.g. "positive" + intensity 1 with angry emotions) lose points.

  3. novelty_penalty (0.3 weight)
     Items very similar to existing feedback (near-duplicate score > 0.85) are
     penalised — they're likely to be correctly classified via dedup anyway, but
     high novelty items have less prior context to anchor the LLM's output.
     novelty_score = 1.0 - max_dedup_similarity  (0 = exact copy, 1 = totally novel)
     We apply a mild penalty: score = 0.5 + 0.5 * novelty_score
     so even fully novel items score 1.0 and near-duplicates score ~0.5.

Items with pipeline_confidence < REVIEW_THRESHOLD (default 0.65) are queued for
active learning review.
"""

import os

from langchain_core.runnables import RunnableLambda

REVIEW_THRESHOLD = float(os.getenv("REVIEW_THRESHOLD", "0.65"))


def _score_sentiment_consistency(ctx: dict) -> float:
    sentiment = ctx["sentiment"].sentiment  # positive / negative / neutral
    intensity = ctx["sentiment"].intensity  # 1–10
    emotions = ctx["sentiment"].emotions  # list[str]

    if sentiment == "neutral":
        # Neutral with low intensity is fine; neutral with high intensity is odd
        return 1.0 if intensity <= 5 else 0.6

    # Negative emotions in a "positive" labelled item signal confusion
    negative_words = {"frustrated", "angry", "disappointed", "confused", "anxious"}
    emotion_set = {e.lower() for e in emotions}
    mismatch = bool(negative_words & emotion_set) and sentiment == "positive"

    if mismatch:
        return 0.5
    # Intensity ≥ 4 with a definite sentiment = good signal
    return min(1.0, 0.6 + (intensity / 10) * 0.4)


def _novelty_score(ctx: dict) -> float:
    """
    Best-effort novelty score using the dedup similarity stored in ctx.
    If not available (dedup was skipped), assume moderate novelty.
    """
    max_sim = ctx.get("dedup_max_similarity", 0.5)
    return 0.5 + 0.5 * (1.0 - max_sim)


def _compute_confidence(ctx: dict) -> dict:
    taxonomy_conf = ctx["taxonomy"].confidence  # 0–1 from LLM
    sentiment_score = _score_sentiment_consistency(ctx)  # 0–1
    novelty = _novelty_score(ctx)  # 0–1

    pipeline_confidence = round(
        0.4 * taxonomy_conf + 0.3 * sentiment_score + 0.3 * novelty,
        4,
    )

    return {
        **ctx,
        "pipeline_confidence": pipeline_confidence,
        "confidence_breakdown": {
            "taxonomy": round(taxonomy_conf, 4),
            "sentiment_consistency": round(sentiment_score, 4),
            "novelty": round(novelty, 4),
        },
        "needs_review": pipeline_confidence < REVIEW_THRESHOLD,
    }


confidence_stage = RunnableLambda(_compute_confidence)
