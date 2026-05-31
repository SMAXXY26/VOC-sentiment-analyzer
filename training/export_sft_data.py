"""Export high-confidence FeedbackAnalysis records from Qdrant as ShareGPT JSONL for SFT.

Usage:
    python training/export_sft_data.py --min-confidence 0.75 --out training/data/sft.jsonl
    python training/export_sft_data.py --min-confidence 0.80 --limit 500 --out training/data/sft.jsonl
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

SYSTEM_PROMPT = """You are a Customer Experience (CX) analyst. Given a raw customer feedback message, analyze it and return a structured JSON analysis with the following fields:

{
  "taxonomy": {
    "category": "<one of: Billing, Product, Support, Shipping, Account, Onboarding, Other>",
    "subcategory": "<specific subcategory>",
    "confidence": <0.0-1.0>
  },
  "sentiment": {
    "sentiment": "<positive|negative|neutral>",
    "emotions": ["<emotion>", ...],
    "intensity": <1-10>
  },
  "signals": {
    "churn_risk": <true|false>,
    "upsell_opportunity": <true|false>,
    "feature_requests": ["<request>", ...],
    "bug_reports": ["<bug>", ...],
    "competitor_mentions": ["<competitor>", ...]
  },
  "risk": {
    "escalate": <true|false>,
    "risk_level": "<low|medium|high|critical>",
    "reason": "<why>",
    "suggested_action": "<what to do>"
  }
}

Return only the JSON object. No explanation, no markdown fences."""


def build_assistant_turn(analysis_json: str) -> str | None:
    """Extract only the fields that fit in the token budget from a full FeedbackAnalysis."""
    try:
        full = json.loads(analysis_json)
        slim = {
            "taxonomy": full.get("taxonomy", {}),
            "sentiment": full.get("sentiment", {}),
            "signals": full.get("signals", {}),
            "risk": full.get("risk", {}),
        }
        # Remove None / empty lists to keep compact
        for section in slim.values():
            for k, v in list(section.items()):
                if v is None or v == []:
                    del section[k]
        return json.dumps(slim, separators=(",", ":"))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-confidence", type=float, default=0.75,
                        help="Minimum pipeline_confidence to include (default: 0.75)")
    parser.add_argument("--limit", type=int, default=5000,
                        help="Max Qdrant points to scan (default: 5000)")
    parser.add_argument("--out", default="training/data/sft.jsonl",
                        help="Output JSONL path (default: training/data/sft.jsonl)")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    args = parser.parse_args()

    os.environ["QDRANT_URL"] = args.qdrant_url

    from vectordb.client import get_client, ANALYSES_COLLECTION
    client = get_client()

    print(f"Connecting to Qdrant at {args.qdrant_url}")
    print(f"Scanning up to {args.limit} points with pipeline_confidence >= {args.min_confidence}")

    points, _ = client.scroll(
        collection_name=ANALYSES_COLLECTION,
        limit=args.limit,
        with_payload=True,
        with_vectors=False,
    )

    written = 0
    skipped_no_json = 0
    skipped_low_confidence = 0
    skipped_no_text = 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    with open(args.out, "w") as f:
        for point in points:
            payload = point.payload or {}

            confidence = payload.get("pipeline_confidence")
            if confidence is not None and confidence < args.min_confidence:
                skipped_low_confidence += 1
                continue

            raw_text = payload.get("raw_text", "").strip()
            if not raw_text:
                skipped_no_text += 1
                continue

            analysis_json = payload.get("analysis_json")
            if not analysis_json:
                skipped_no_json += 1
                continue

            assistant_turn = build_assistant_turn(analysis_json)
            if not assistant_turn:
                skipped_no_json += 1
                continue

            record = {
                "conversations": [
                    {"role": "system",    "value": SYSTEM_PROMPT},
                    {"role": "user",      "value": raw_text},
                    {"role": "assistant", "value": assistant_turn},
                ]
            }
            f.write(json.dumps(record) + "\n")
            written += 1

    print(f"\nDone.")
    print(f"  Written            : {written}")
    print(f"  Skipped (low conf) : {skipped_low_confidence}")
    print(f"  Skipped (no text)  : {skipped_no_text}")
    print(f"  Skipped (no json)  : {skipped_no_json}")
    print(f"  Output             : {args.out}")


if __name__ == "__main__":
    main()
