"""Stress test for the Kafka ingestion path (producer + consumer + analyzer).

Floods the Rust producer at PRODUCER_URL with concurrent POST /feedback requests,
measures latency and throughput, then polls the consumer's Prometheus metrics to
watch the queue drain end-to-end.

Usage:
    python tests/stress_kafka.py --total 1000 --concurrency 50
    python tests/stress_kafka.py --total 5000 --concurrency 100 --batch 20
    PRODUCER_URL=http://192.168.1.51:3001 python tests/stress_kafka.py --total 500
"""

import argparse
import asyncio
import os
import random
import statistics
import string
import time
import uuid
from dataclasses import dataclass, field

import httpx

PRODUCER_URL = os.getenv("PRODUCER_URL", "http://localhost:3001")
PRODUCER_METRICS = os.getenv("PRODUCER_METRICS", "http://localhost:9001/metrics")
CONSUMER_METRICS = os.getenv("CONSUMER_METRICS", "http://localhost:9002/metrics")

SAMPLE_TEXTS = [
    "The product arrived damaged and I want a full refund immediately.",
    "Loved the packaging but the item itself feels cheap for the price.",
    "Customer service was incredibly helpful, resolved my issue in minutes.",
    "Shipping took three weeks longer than promised, very disappointing.",
    "Best purchase I've made this year, will definitely recommend to friends.",
    "App keeps crashing whenever I try to check out — losing sales over this.",
    "Quality is fine but the sizing chart was completely wrong.",
    "Five stars for the delivery driver but the product itself is mediocre.",
]


@dataclass
class Stats:
    latencies_ms: list[float] = field(default_factory=list)
    successes: int = 0
    failures: int = 0
    errors: dict[str, int] = field(default_factory=dict)


def make_payload() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "text": random.choice(SAMPLE_TEXTS),
        "source": "stress_test",
        "rating": round(random.uniform(1, 5), 1),
        "submitted_at": None,
        "metadata": {"run_id": "".join(random.choices(string.ascii_lowercase, k=8))},
    }


async def send_one(client: httpx.AsyncClient, stats: Stats, endpoint: str, body):
    t0 = time.perf_counter()
    try:
        r = await client.post(endpoint, json=body, timeout=30.0)
        dt = (time.perf_counter() - t0) * 1000
        stats.latencies_ms.append(dt)
        if r.status_code < 300:
            stats.successes += 1
        else:
            stats.failures += 1
            key = f"http_{r.status_code}"
            stats.errors[key] = stats.errors.get(key, 0) + 1
    except Exception as e:
        stats.failures += 1
        key = type(e).__name__
        stats.errors[key] = stats.errors.get(key, 0) + 1


async def worker(queue: asyncio.Queue, client: httpx.AsyncClient, stats: Stats, endpoint: str):
    while True:
        body = await queue.get()
        if body is None:
            queue.task_done()
            return
        await send_one(client, stats, endpoint, body)
        queue.task_done()


async def run_load(total: int, concurrency: int, batch_size: int) -> Stats:
    stats = Stats()
    queue: asyncio.Queue = asyncio.Queue(maxsize=concurrency * 4)

    if batch_size > 1:
        endpoint = f"{PRODUCER_URL}/feedback/batch"
        n_requests = (total + batch_size - 1) // batch_size
        bodies = [[make_payload() for _ in range(batch_size)] for _ in range(n_requests)]
    else:
        endpoint = f"{PRODUCER_URL}/feedback"
        bodies = [make_payload() for _ in range(total)]

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        workers = [asyncio.create_task(worker(queue, client, stats, endpoint)) for _ in range(concurrency)]
        t0 = time.perf_counter()
        for body in bodies:
            await queue.put(body)
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        elapsed = time.perf_counter() - t0

    print_results(stats, elapsed, total, batch_size)
    return stats


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def print_results(stats: Stats, elapsed: float, total: int, batch_size: int):
    effective_msgs = stats.successes * batch_size
    print("\n" + "=" * 60)
    print(f"Producer load: POST {'batch' if batch_size > 1 else 'single'}")
    print("=" * 60)
    print(f"  Requests sent      : {stats.successes + stats.failures} ({total} target)")
    print(f"  Successes          : {stats.successes}")
    print(f"  Failures           : {stats.failures}")
    if stats.errors:
        print(f"  Error breakdown    : {stats.errors}")
    print(f"  Elapsed            : {elapsed:.2f}s")
    print(f"  Request throughput : {stats.successes / elapsed:.1f} req/s")
    if batch_size > 1:
        print(f"  Message throughput : {effective_msgs / elapsed:.1f} msgs/s ({batch_size} per req)")
    if stats.latencies_ms:
        print(
            f"  Latency (ms)       : "
            f"p50={pct(stats.latencies_ms, 50):.1f}  "
            f"p95={pct(stats.latencies_ms, 95):.1f}  "
            f"p99={pct(stats.latencies_ms, 99):.1f}  "
            f"max={max(stats.latencies_ms):.1f}  "
            f"mean={statistics.mean(stats.latencies_ms):.1f}"
        )
    print("=" * 60)


async def fetch_metric(url: str, metric_name: str) -> float | None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            for line in r.text.splitlines():
                if line.startswith(metric_name) and not line.startswith("#"):
                    parts = line.rsplit(" ", 1)
                    return float(parts[-1])
    except Exception:
        return None
    return None


async def watch_consumer_drain(expected_msgs: int, max_wait_s: int):
    print(f"\nWatching consumer drain (expecting ~{expected_msgs} analyzed messages)...")
    start = await fetch_metric(CONSUMER_METRICS, "feedback_analyzed_total")
    if start is None:
        print("  (consumer metrics unreachable — skipping drain watch)")
        return
    t0 = time.perf_counter()
    last_count = start
    while time.perf_counter() - t0 < max_wait_s:
        await asyncio.sleep(5)
        now = await fetch_metric(CONSUMER_METRICS, "feedback_analyzed_total") or last_count
        delta = now - start
        rate = (now - last_count) / 5
        print(f"  t+{int(time.perf_counter() - t0):3d}s  analyzed={int(delta)}/{expected_msgs}  rate={rate:.1f} msgs/s")
        last_count = now
        if delta >= expected_msgs:
            print(
                f"\n  Queue drained in {time.perf_counter() - t0:.1f}s, end-to-end throughput {expected_msgs / (time.perf_counter() - t0):.1f} msgs/s"
            )
            return
    print(f"\n  Timed out after {max_wait_s}s; {int(last_count - start)}/{expected_msgs} analyzed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=500, help="total messages to enqueue")
    parser.add_argument("--concurrency", type=int, default=50, help="concurrent HTTP connections")
    parser.add_argument("--batch", type=int, default=1, help="messages per request (>1 uses /feedback/batch)")
    parser.add_argument("--watch", type=int, default=180, help="seconds to watch consumer drain (0 to skip)")
    args = parser.parse_args()

    print(f"Target: {PRODUCER_URL}")
    print(f"Plan  : {args.total} messages, concurrency={args.concurrency}, batch={args.batch}\n")

    stats = asyncio.run(run_load(args.total, args.concurrency, args.batch))

    if args.watch > 0:
        expected = stats.successes * args.batch
        asyncio.run(watch_consumer_drain(expected, args.watch))


if __name__ == "__main__":
    main()
