"""Export human-corrected items from the review queue as DPO chosen/rejected pairs.

Chosen  = the corrected analysis (human said this is right)
Rejected = the original low-confidence analysis (human said this was wrong)

Usage:
    python training/export_dpo_data.py --out training/data/dpo.jsonl
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

SYSTEM_PROMPT = """You are a Customer Experience (CX) analyst. Given a raw customer feedback message, analyze it and return a structured JSON analysis with the following fields:

{
  "taxonomy": {"category": "...", "subcategory": "...", "confidence": 0.0},
  "sentiment": {"sentiment": "...", "emotions": [], "intensity": 0},
  "signals": {"churn_risk": false, "upsell_opportunity": false, "feature_requests": [], "bug_reports": [], "competitor_mentions": []},
  "risk": {"escalate": false, "risk_level": "...", "reason": "...", "suggested_action": "..."}
}

Return only the JSON object."""


def build_prompt(raw_text: str) -> str:
    return f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{raw_text}<|im_end|>\n<|im_start|>assistant\n"


def fetch_analysis_by_id(client, feedback_id: str, collection: str) -> dict | None:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    try:
        results, _ = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[FieldCondition(key="feedback_id", match=MatchValue(value=feedback_id))]),
            limit=1,
            with_payload=True,
        )
        if results and results[0].payload.get("analysis_json"):
            return json.loads(results[0].payload["analysis_json"])
    except Exception:
        pass
    return None


def slim_analysis(analysis: dict) -> str:
    slim = {k: analysis.get(k, {}) for k in ("taxonomy", "sentiment", "signals", "risk")}
    return json.dumps(slim, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="training/data/dpo.jsonl")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    args = parser.parse_args()

    os.environ["QDRANT_URL"] = args.qdrant_url

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from training._report import banner, step, summary, warn
    from vectordb.client import ANALYSES_COLLECTION, get_client

    banner("DPO data export", "review_queue corrections → chosen/rejected pairs")
    client = get_client()
    REVIEW_COLLECTION = "review_queue"

    step(f"Connecting to Qdrant at {args.qdrant_url}")

    # Scroll review_queue for reviewed items with corrections
    try:
        queue_points, _ = client.scroll(
            collection_name=REVIEW_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="status", match=MatchValue(value="reviewed"))]),
            limit=5000,
            with_payload=True,
        )
    except Exception as e:
        warn(f"Could not read review_queue collection: {e}")
        queue_points = []

    written = 0
    skipped = 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    with open(args.out, "w") as f:
        for point in queue_points:
            p = point.payload or {}
            correction = p.get("correction")
            if not correction:
                skipped += 1
                continue

            raw_text = p.get("raw_text", "").strip()
            feedback_id = p.get("feedback_id")
            if not raw_text or not feedback_id:
                skipped += 1
                continue

            # Chosen: the corrected analysis stored in feedback_analyses
            chosen_analysis = fetch_analysis_by_id(client, feedback_id, ANALYSES_COLLECTION)
            if not chosen_analysis:
                skipped += 1
                continue

            # Rejected: reconstruct from the original pre-correction fields on the queue item
            rejected_slim = {
                "taxonomy": {
                    "category": p.get("current_category", "Other"),
                    "subcategory": p.get("current_subcategory", ""),
                    "confidence": p.get("pipeline_confidence", 0.5),
                },
                "sentiment": {
                    "sentiment": p.get("current_sentiment", "neutral"),
                },
                "signals": {},
                "risk": {},
            }

            record = {
                "prompt": build_prompt(raw_text),
                "chosen": slim_analysis(chosen_analysis),
                "rejected": json.dumps(rejected_slim, separators=(",", ":")),
            }
            f.write(json.dumps(record) + "\n")
            written += 1

    summary(
        "DPO export complete",
        dpo_pairs_written=written,
        skipped=skipped,
        output=args.out,
    )
    if written == 0:
        warn("0 pairs — the review queue has no human corrections yet.")
        warn("Submit corrections via POST /review/<feedback_id> to build DPO data.")


if __name__ == "__main__":
    main()
