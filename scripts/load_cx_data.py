"""Bulk-load a public CX dataset into Qdrant via the analysis pipeline.

Pulls real customer-experience text from a HuggingFace dataset, runs each item
through the full pipeline, and (via store_result_stage) populates the
`feedback_analyses` collection used for dedup / RAG / clustering / drift.

This fills the *vector DB* — not the SQLite EDBMS that backs the chatbot/orders UI.

Usage:
    python scripts/load_cx_data.py --limit 200
    python scripts/load_cx_data.py --dataset argilla/customer_assistant \
        --text-field text --limit 500 --semantic-schedule

Requires vLLM reachable (VLLM_BASE_URL) and Qdrant (QDRANT_URL); `pip install datasets`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.progress import track  # noqa: E402

from analyzer.main import analyze_single  # noqa: E402
from ingestion import HFDatasetIngester  # noqa: E402

load_dotenv()
console = Console()


def main():
    p = argparse.ArgumentParser(description="Load an online CX dataset into Qdrant.")
    p.add_argument("--dataset", default="argilla/customer_assistant", help="HuggingFace dataset id")
    p.add_argument("--split", default="train")
    p.add_argument("--text-field", default="text")
    p.add_argument("--rating-field", default=None)
    p.add_argument("--limit", type=int, default=200, help="max rows to ingest (keeps GPU time bounded)")
    p.add_argument("--semantic-schedule", action="store_true", help="reorder by similarity for prefix-cache reuse")
    args = p.parse_args()

    console.print(f"[bold cyan]Fetching up to {args.limit} rows from {args.dataset}...[/bold cyan]")
    records = HFDatasetIngester(
        dataset=args.dataset,
        split=args.split,
        text_field=args.text_field,
        rating_field=args.rating_field,
        limit=args.limit,
    ).ingest()
    console.print(f"[green]Loaded {len(records)} records[/green]")

    if args.semantic_schedule and len(records) > 2:
        from analyzer.scheduler import schedule

        records = schedule(records, key=lambda r: r.text)
        console.print("[cyan]Reordered by semantic similarity (prefix-cache friendly)[/cyan]")

    stored = 0
    for rec in track(records, description="Analyzing → Qdrant..."):
        try:
            analyze_single(rec.text)  # store_result_stage persists to feedback_analyses
            stored += 1
        except Exception as exc:
            console.print(f"[yellow]skip: {str(exc)[:80]}[/yellow]")

    console.print(f"[bold green]Done. {stored}/{len(records)} analyses stored to Qdrant.[/bold green]")
    console.print("Verify: GET /analyses/summary  ·  POST /cluster  ·  GET /drift")


if __name__ == "__main__":
    main()
