"""
Entry point: ingest from a source → run semantic analysis → output results.

Usage examples:

  # CSV
  python run_pipeline.py --source csv --file feedback.csv --text-col "response" --out results.json

  # NPS export
  python run_pipeline.py --source nps --file nps_export.csv --out results.json

  # Google Forms CSV export
  python run_pipeline.py --source google_forms --file form.csv \
      --questions "What did you think?" "Any suggestions?" --out results.json

  # Typeform (requires TYPEFORM_API_TOKEN in .env)
  python run_pipeline.py --source typeform --form-id abc123 --out results.json
"""

import argparse
import json
import os

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

from analyzer.main import analyze_single
from analyzer.pipeline.trend_aggregation import aggregate_trends
from ingestion import CSVIngester, GoogleFormsIngester, NPSIngester, RawFeedback, TypeformIngester

load_dotenv()
console = Console()


def load_records(args) -> list[RawFeedback]:
    if args.source == "csv":
        return CSVIngester(
            text_col=args.text_col or "text",
            rating_col=args.rating_col or "rating",
            date_col=args.date_col or "submitted_at",
        ).ingest(args.file)

    if args.source == "nps":
        return NPSIngester(
            score_col=args.score_col or "score",
            comment_col=args.text_col or "comment",
        ).ingest(args.file)

    if args.source == "google_forms":
        return GoogleFormsIngester(
            feedback_questions=args.questions,
            rating_question=args.rating_question,
        ).ingest(args.file)

    if args.source == "typeform":
        token = os.getenv("TYPEFORM_API_TOKEN", "")
        if not token:
            raise ValueError("TYPEFORM_API_TOKEN not set in .env")
        return TypeformIngester(api_token=token).ingest(args.form_id)

    raise ValueError(f"Unknown source: {args.source}")


def main():
    parser = argparse.ArgumentParser(description="CX Pipeline: ingest → analyze")
    parser.add_argument("--source", required=True, choices=["csv", "nps", "google_forms", "typeform"])
    parser.add_argument("--file", help="Path to input file (CSV sources)")
    parser.add_argument("--form-id", help="Typeform form ID")
    parser.add_argument("--text-col", help="Column name for feedback text")
    parser.add_argument("--rating-col", help="Column name for rating")
    parser.add_argument("--date-col", help="Column name for date")
    parser.add_argument("--score-col", help="NPS score column name")
    parser.add_argument("--questions", nargs="+", help="Google Forms question headers")
    parser.add_argument("--rating-question", help="Google Forms rating question header")
    parser.add_argument("--out", required=True, help="Output JSON file path")
    parser.add_argument("--no-trends", action="store_true", help="Skip trend aggregation (faster for single items)")
    parser.add_argument(
        "--semantic-schedule",
        action="store_true",
        help="Reorder the batch by semantic similarity to maximize vLLM "
        "prefix-cache reuse (needs vLLM --enable-prefix-caching)",
    )
    args = parser.parse_args()

    console.print(f"[bold cyan]Loading records from {args.source}...[/bold cyan]")
    records = load_records(args)
    console.print(f"[green]Loaded {len(records)} feedback records[/green]")

    if args.semantic_schedule and len(records) > 2:
        from analyzer.scheduler import schedule

        records = schedule(records, key=lambda r: r.text)
        console.print("[cyan]Reordered batch by semantic similarity (prefix-cache friendly)[/cyan]")

    analyses = []
    for record in track(records, description="Analyzing..."):
        result = analyze_single(record.text)
        analyses.append(
            {
                "source_id": record.id,
                "source": record.source,
                "rating": record.rating,
                "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
                "metadata": record.metadata,
                "analysis": result.model_dump(),
            }
        )

    output: dict = {"results": analyses}

    if not args.no_trends and len(analyses) > 1:
        console.print("[bold cyan]Aggregating trends...[/bold cyan]")
        from analyzer.schemas import FeedbackAnalysis

        parsed = [FeedbackAnalysis(**a["analysis"]) for a in analyses]
        output["trends"] = aggregate_trends(parsed).model_dump()

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2, default=str)

    console.print(f"[bold green]Done. Results written to {args.out}[/bold green]")


if __name__ == "__main__":
    main()
