"""FastAPI analyzer pipeline E2E benchmark — P50/P95/P99 latency, req/s.

Measures total wall-clock time from POST /analyze to full JSON response.
Each request runs the full 10-stage LLM pipeline (~6-8 LLM calls), so latency
is high by design. This tells you end-to-end throughput, not raw LLM speed
(use benchmark_vllm.py for TTFT and token throughput).

Usage:
    python tests/benchmark_pipeline.py
    python tests/benchmark_pipeline.py --concurrency 1 2 4 --requests 10
    ANALYZER_URL=http://192.168.1.3:8080 python tests/benchmark_pipeline.py
"""

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass

import httpx
from rich.console import Console
from rich.table import Table

from benchmark_utils import compute_stats

ANALYZER_URL = os.getenv("ANALYZER_URL", "http://localhost:8080")

SAMPLE_TEXTS = [
    "The product arrived damaged and I want a full refund immediately.",
    "Loved the packaging but the item itself feels cheap for the price.",
    "Customer service was incredibly helpful, resolved my issue in minutes.",
    "Shipping took three weeks longer than promised, very disappointing.",
    "Best purchase I've made this year, will definitely recommend to friends.",
    "App keeps crashing whenever I try to check out — losing sales over this.",
    "Quality is fine but the sizing chart was completely wrong, I had to return it.",
    "Five stars for the delivery driver but the product itself is mediocre.",
    "I was charged twice for one order and nobody responds to my support tickets.",
    "Excellent build quality, fast delivery, and the packaging was eco-friendly.",
]


@dataclass
class PipelineResult:
    latency_ms: float
    status: int
    has_confidence: bool
    success: bool
    error: str = ""


async def analyze_one(
    client: httpx.AsyncClient, text: str, semaphore: asyncio.Semaphore
) -> PipelineResult:
    async with semaphore:
        t_start = time.perf_counter()
        try:
            r = await client.post(
                f"{ANALYZER_URL}/analyze",
                json={"text": text},
                timeout=180.0,
            )
            latency_ms = (time.perf_counter() - t_start) * 1000
            has_confidence = False
            if r.status_code == 200:
                try:
                    has_confidence = r.json().get("pipeline_confidence") is not None
                except Exception:
                    pass
            return PipelineResult(
                latency_ms=latency_ms,
                status=r.status_code,
                has_confidence=has_confidence,
                success=r.status_code == 200,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000
            return PipelineResult(
                latency_ms=latency_ms, status=0, has_confidence=False,
                success=False, error=str(exc)[:80],
            )


async def run_level(concurrency: int, num_requests: int, warmup: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(
        max_connections=concurrency + 2,
        max_keepalive_connections=concurrency,
    )
    async with httpx.AsyncClient(limits=limits) as client:
        warmup_tasks = [
            analyze_one(client, SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)], semaphore)
            for i in range(warmup)
        ]
        await asyncio.gather(*warmup_tasks)

        t_wall = time.perf_counter()
        tasks = [
            analyze_one(client, SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)], semaphore)
            for i in range(num_requests)
        ]
        results: list[PipelineResult] = await asyncio.gather(*tasks)
        wall_elapsed = time.perf_counter() - t_wall

    successes = [r for r in results if r.success]
    failures = len(results) - len(successes)
    error_counts: dict[str, int] = {}
    for r in results:
        if not r.success:
            key = r.error if r.error else f"http_{r.status}"
            error_counts[key] = error_counts.get(key, 0) + 1

    latency_stats = compute_stats([r.latency_ms for r in successes])

    return {
        "concurrency": concurrency,
        "num_requests": num_requests,
        "successes": len(successes),
        "failures": failures,
        "errors": error_counts,
        "wall_elapsed_s": round(wall_elapsed, 2),
        "req_per_sec": round(len(successes) / wall_elapsed, 4) if wall_elapsed > 0 else 0.0,
        "latency_ms": latency_stats.__dict__,
        "with_confidence_score": sum(1 for r in successes if r.has_confidence),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark FastAPI analyzer pipeline E2E latency.")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4],
                        help="concurrency levels to sweep (default: 1 2 4)")
    parser.add_argument("--requests", type=int, default=10,
                        help="measured requests per concurrency level (default: 10)")
    parser.add_argument("--warmup", type=int, default=2,
                        help="warm-up requests discarded before measurement (default: 2)")
    parser.add_argument("--out", default="results_pipeline.json",
                        help="output JSON file (default: results_pipeline.json)")
    args = parser.parse_args()

    print(f"Target  : {ANALYZER_URL}/analyze")
    print(f"Plan    : concurrency={args.concurrency}, requests={args.requests}, warmup={args.warmup}")
    print("Note    : each request runs the full 10-stage LLM pipeline (~6-8 LLM calls)\n")

    all_results = []
    for c in args.concurrency:
        print(f"  Running concurrency={c} (warmup={args.warmup} + measured={args.requests})...")
        result = asyncio.run(run_level(c, args.requests, args.warmup))
        all_results.append(result)
        lat = result["latency_ms"]
        print(f"    p50={lat['p50']:.0f}ms  p95={lat['p95']:.0f}ms  p99={lat['p99']:.0f}ms  "
              f"req/s={result['req_per_sec']:.4f}  failures={result['failures']}")

    console = Console()
    table = Table(title="Pipeline E2E Benchmark Results", show_lines=True)
    table.add_column("Conc.", justify="right")
    table.add_column("Req/s", justify="right")
    table.add_column("mean (ms)", justify="right")
    table.add_column("p50 (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    table.add_column("p99 (ms)", justify="right")
    table.add_column("max (ms)", justify="right")
    table.add_column("Failures", justify="right")

    for r in all_results:
        lat = r["latency_ms"]
        table.add_row(
            str(r["concurrency"]),
            f"{r['req_per_sec']:.4f}",
            f"{lat['mean']:.0f}",
            f"{lat['p50']:.0f}",
            f"{lat['p95']:.0f}",
            f"{lat['p99']:.0f}",
            f"{lat['max']:.0f}",
            str(r["failures"]),
        )

    console.print()
    console.print(table)

    with open(args.out, "w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
