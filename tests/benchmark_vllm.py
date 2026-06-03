"""Raw vLLM inference benchmark — TTFT, ITL, token throughput, E2E latency.

Connects directly to the vLLM OpenAI-compatible endpoint using stream=True so
TTFT (time to first token) can be measured. The FastAPI /analyze endpoint is
non-streaming and runs 6-8 LLM calls internally, so raw vLLM TTFT must be
measured here, not through the pipeline.

Usage:
    python tests/benchmark_vllm.py
    python tests/benchmark_vllm.py --concurrency 1 4 8 16 --prompts 30
    VLLM_BASE_URL=http://192.168.1.11:8000/v1 python tests/benchmark_vllm.py
"""

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass, field

from benchmark_utils import LatencyStats, compute_stats
from openai import AsyncOpenAI
from rich.console import Console
from rich.table import Table

MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct-AWQ")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://192.168.1.11:8000/v1")

# Short prompts that stay well within the 1024 token context window
PROMPTS = [
    "Summarize this feedback in one sentence: The product arrived damaged.",
    "Summarize this feedback in one sentence: Great experience, loved the fast delivery.",
    "Summarize this feedback in one sentence: Customer service was unhelpful, waited 3 days.",
    "Summarize this feedback in one sentence: The app keeps crashing on checkout.",
    "Summarize this feedback in one sentence: Exactly as described, will buy again.",
    "Summarize this feedback in one sentence: Shipping took three weeks longer than promised.",
    "Summarize this feedback in one sentence: Quality is poor for the price paid.",
    "Summarize this feedback in one sentence: Easy returns process, resolved quickly.",
    "Summarize this feedback in one sentence: The sizing chart was completely wrong.",
    "Summarize this feedback in one sentence: Best purchase this year, highly recommend.",
]


@dataclass
class RequestResult:
    ttft_ms: float
    itl_values_ms: list[float] = field(default_factory=list)
    total_output_tokens: int = 0
    e2e_ms: float = 0.0
    success: bool = True
    error: str = ""


async def measure_one(client: AsyncOpenAI, prompt: str, semaphore: asyncio.Semaphore) -> RequestResult:
    async with semaphore:
        t_start = time.perf_counter()
        ttft_ms: float | None = None
        itl_values: list[float] = []
        output_tokens = 0
        prev_ts = t_start
        try:
            stream = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                ts = time.perf_counter()
                if chunk.choices and chunk.choices[0].delta.content:
                    if ttft_ms is None:
                        ttft_ms = (ts - t_start) * 1000
                    else:
                        itl_values.append((ts - prev_ts) * 1000)
                    prev_ts = ts
                if chunk.usage:
                    output_tokens = chunk.usage.completion_tokens or output_tokens
            e2e_ms = (time.perf_counter() - t_start) * 1000
            return RequestResult(
                ttft_ms=ttft_ms if ttft_ms is not None else e2e_ms,
                itl_values_ms=itl_values,
                total_output_tokens=output_tokens,
                e2e_ms=e2e_ms,
            )
        except Exception as exc:
            e2e_ms = (time.perf_counter() - t_start) * 1000
            return RequestResult(ttft_ms=0.0, e2e_ms=e2e_ms, success=False, error=str(exc))


async def run_level(concurrency: int, num_prompts: int, warmup: int) -> dict:
    client = AsyncOpenAI(base_url=VLLM_BASE_URL, api_key="dummy")
    semaphore = asyncio.Semaphore(concurrency)

    warmup_tasks = [
        measure_one(client, PROMPTS[i % len(PROMPTS)], semaphore) for i in range(warmup)
    ]
    await asyncio.gather(*warmup_tasks)

    t_wall = time.perf_counter()
    tasks = [
        measure_one(client, PROMPTS[i % len(PROMPTS)], semaphore) for i in range(num_prompts)
    ]
    results: list[RequestResult] = await asyncio.gather(*tasks)
    wall_elapsed = time.perf_counter() - t_wall

    successes = [r for r in results if r.success]
    failures = len(results) - len(successes)
    total_output_tokens = sum(r.total_output_tokens for r in successes)

    ttft_stats = compute_stats([r.ttft_ms for r in successes])
    all_itl = [v for r in successes for v in r.itl_values_ms]
    itl_stats = compute_stats(all_itl)
    e2e_stats = compute_stats([r.e2e_ms for r in successes])

    return {
        "concurrency": concurrency,
        "num_prompts": num_prompts,
        "successes": len(successes),
        "failures": failures,
        "wall_elapsed_s": round(wall_elapsed, 2),
        "req_per_sec": round(len(successes) / wall_elapsed, 2) if wall_elapsed > 0 else 0.0,
        "token_throughput_per_sec": round(total_output_tokens / wall_elapsed, 1) if wall_elapsed > 0 else 0.0,
        "ttft_ms": ttft_stats.__dict__,
        "itl_ms": itl_stats.__dict__,
        "e2e_ms": e2e_stats.__dict__,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark raw vLLM TTFT and throughput.")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8],
                        help="concurrency levels to sweep (default: 1 4 8)")
    parser.add_argument("--prompts", type=int, default=20,
                        help="measured requests per concurrency level (default: 20)")
    parser.add_argument("--warmup", type=int, default=3,
                        help="warm-up requests discarded before measurement (default: 3)")
    parser.add_argument("--out", default="results_vllm.json",
                        help="output JSON file (default: results_vllm.json)")
    args = parser.parse_args()

    print(f"Target : {VLLM_BASE_URL}")
    print(f"Model  : {MODEL_NAME}")
    print(f"Plan   : concurrency={args.concurrency}, prompts={args.prompts}, warmup={args.warmup}\n")

    all_results = []
    for c in args.concurrency:
        print(f"  Running concurrency={c} (warmup={args.warmup} + measured={args.prompts})...")
        result = asyncio.run(run_level(c, args.prompts, args.warmup))
        all_results.append(result)
        ttft = result["ttft_ms"]
        print(f"    TTFT p50={ttft['p50']:.0f}ms  p95={ttft['p95']:.0f}ms  "
              f"tok/s={result['token_throughput_per_sec']:.0f}  failures={result['failures']}")

    console = Console()
    table = Table(title="vLLM Benchmark Results", show_lines=True)
    table.add_column("Conc.", justify="right")
    table.add_column("Req/s", justify="right")
    table.add_column("Tok/s", justify="right")
    table.add_column("TTFT mean", justify="right")
    table.add_column("TTFT p50", justify="right")
    table.add_column("TTFT p95", justify="right")
    table.add_column("TTFT p99", justify="right")
    table.add_column("ITL p95", justify="right")
    table.add_column("E2E p95", justify="right")
    table.add_column("Fail", justify="right")

    for r in all_results:
        ttft = r["ttft_ms"]
        itl = r["itl_ms"]
        e2e = r["e2e_ms"]
        table.add_row(
            str(r["concurrency"]),
            f"{r['req_per_sec']:.1f}",
            f"{r['token_throughput_per_sec']:.0f}",
            f"{ttft['mean']:.0f} ms",
            f"{ttft['p50']:.0f} ms",
            f"{ttft['p95']:.0f} ms",
            f"{ttft['p99']:.0f} ms",
            f"{itl['p95']:.0f} ms",
            f"{e2e['p95']:.0f} ms",
            str(r["failures"]),
        )

    console.print()
    console.print(table)

    with open(args.out, "w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
