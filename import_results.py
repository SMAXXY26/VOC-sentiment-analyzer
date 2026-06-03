"""
Import a results JSON file (from run_pipeline.py) into Qdrant.
Usage: python import_results.py results_clothing.json
"""
import json
import sys
import uuid


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "results_clothing.json"
    with open(path) as f:
        data = json.load(f)

    # handle both {results: [...]} and {individual: [...]} wrapper formats
    if isinstance(data, dict):
        raw_items = data.get("results", data.get("individual", [data]))
    else:
        raw_items = data

    # each item may be a bare FeedbackAnalysis dict OR a wrapper with an "analysis" key
    items = []
    for r in raw_items:
        if "analysis" in r:
            entry = r["analysis"]
            entry["_source"] = r.get("source", "csv")
            items.append(entry)
        else:
            items.append(r)

    from analyzer.schemas import FeedbackAnalysis
    from vectordb.store import store_analysis

    imported = 0
    for item in items:
        try:
            analysis = FeedbackAnalysis(**item)
            feedback_id = str(uuid.uuid4())
            raw_text = item.get("normalized", {}).get("original", "")
            source = item.pop("_source", item.get("source", "csv"))
            store_analysis(
                feedback_id=feedback_id,
                raw_text=raw_text,
                analysis=analysis,
                source=source,
            )
            imported += 1
            print(f"  [{imported}/{len(items)}] {analysis.enrichment.summary[:60]}…")
        except Exception as e:
            print(f"  [skip] {e}")

    print(f"\nDone. Imported {imported}/{len(items)} analyses into Qdrant.")

if __name__ == "__main__":
    main()
