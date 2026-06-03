import json
import sys
import argparse
import uuid
from rich.console import Console
from rich.json import JSON
from .pipeline import pipeline
from .pipeline.trend_aggregation import aggregate_trends
from .schemas import FeedbackAnalysis

console = Console()


def analyze_single(
    raw_text: str, feedback_id: str | None = None, model: str | None = None
) -> FeedbackAnalysis:
    import time
    from .metrics import (
        DEDUP_CACHE_HITS,
        DEDUP_CACHE_MISSES,
        PIPELINE_REQUEST_DURATION,
    )

    req_start = time.perf_counter()

    # Short-circuit: check for duplicate BEFORE running the expensive LLM pipeline.
    # Previously this check ran after pipeline.invoke(), so all 10 LLM stages fired
    # regardless, and FeedbackAnalysis(**hits[0]["analysis"]) always raised KeyError
    # (silently caught) because the stored payload has no "analysis" key.
    try:
        from vectordb.store import find_duplicates, get_analysis_by_id
        import os
        threshold = float(os.getenv("DEDUP_THRESHOLD", "0.95"))
        matches = find_duplicates(raw_text, threshold=threshold)
        if matches:
            cached = get_analysis_by_id(matches[0])
            if cached:
                DEDUP_CACHE_HITS.inc()
                PIPELINE_REQUEST_DURATION.labels(outcome="cache_hit").observe(
                    time.perf_counter() - req_start
                )
                return cached
    except Exception:
        pass  # never block if Qdrant is unavailable

    # Reached only when no cached duplicate was served — full pipeline runs.
    DEDUP_CACHE_MISSES.inc()

    fid = feedback_id or str(uuid.uuid4())

    # Apply the producer's model routing hint for the whole pipeline run, then reset.
    from .llm import set_target_model, reset_target_model
    token = set_target_model(model)
    try:
        ctx = pipeline.invoke({"raw_text": raw_text, "feedback_id": fid})
    finally:
        reset_target_model(token)
    result = FeedbackAnalysis(
        normalized=ctx["normalized"],
        redacted=ctx["redacted"],
        enrichment=ctx["enrichment"],
        taxonomy=ctx["taxonomy"],
        sentiment=ctx["sentiment"],
        signals=ctx["signals"],
        risk=ctx["risk"],
        executive=ctx["executive"],
        pipeline_confidence=ctx.get("pipeline_confidence"),
        needs_review=ctx.get("needs_review"),
    )

    # Queue for active learning review if confidence_stage flagged it
    if result.needs_review:
        try:
            from analyzer.active_learning import enqueue
            enqueue(fid, result)
        except Exception:
            pass

    PIPELINE_REQUEST_DURATION.labels(outcome="computed").observe(
        time.perf_counter() - req_start
    )
    return result


def analyze_batch(texts: list[str]) -> dict:
    analyses = [analyze_single(t) for t in texts]
    trends = aggregate_trends(analyses)
    return {
        "individual": [a.model_dump() for a in analyses],
        "trends": trends.model_dump(),
    }


def main():
    parser = argparse.ArgumentParser(description="Customer Experience Semantic Analyzer")
    parser.add_argument("--text", type=str, help="Single feedback text to analyze")
    parser.add_argument("--file", type=str, help="Path to JSON file with list of feedback strings")
    parser.add_argument("--out", type=str, help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    if args.text:
        console.print("[bold cyan]Analyzing feedback...[/bold cyan]")
        result = analyze_single(args.text)
        output = result.model_dump_json(indent=2)
    elif args.file:
        with open(args.file) as f:
            texts = json.load(f)
        console.print(f"[bold cyan]Analyzing {len(texts)} feedback items...[/bold cyan]")
        result = analyze_batch(texts)
        output = json.dumps(result, indent=2)
    else:
        console.print("[yellow]No input provided. Pipe text via stdin or use --text / --file[/yellow]")
        raw = sys.stdin.read().strip()
        if not raw:
            parser.print_help()
            sys.exit(1)
        result = analyze_single(raw)
        output = result.model_dump_json(indent=2)

    if args.out:
        with open(args.out, "w") as f:
            f.write(output)
        console.print(f"[green]Results written to {args.out}[/green]")
    else:
        console.print(JSON(output))


if __name__ == "__main__":
    main()
