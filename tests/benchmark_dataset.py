"""Research-grade benchmark of the full analysis pipeline over the REAL dataset.

Unlike benchmark_pipeline.py (synthetic SAMPLE_TEXTS, latency only), this runs the
actual customer-visit feedback from data.csv through POST /analyze and reports what
a reviewer would want to see:

  * Latency distribution (p50/p95/p99/max) + throughput (req/s) per concurrency level
  * Success/failure breakdown with error taxonomy
  * Dedup cache-hit rate and estimated LLM calls saved (from /metrics)
  * Per-stage mean latency (pipeline_stage_duration_seconds sum/count delta)
  * Token throughput (prompt + completion tokens, tokens/s) from /metrics
  * GPU utilisation snapshot (from /system)
  * Score distributions over the corpus — the actual research output:
      CSI %, CX %, sentiment mix, category mix, escalation/churn rate,
      pipeline_confidence, needs_review count

Each /analyze call runs all 7 LLM stages, so this is an end-to-end pipeline benchmark,
not a raw-LLM microbenchmark (use benchmark_vllm.py for TTFT/ITL).

Usage:
    # analyzer API must be reachable (see ANALYZER_URL); vLLM + Qdrant must be up.
    python tests/benchmark_dataset.py --limit 679 --concurrency 2
    python tests/benchmark_dataset.py --concurrency 1 2 4 --limit 100
    ANALYZER_URL=http://localhost:8080 python tests/benchmark_dataset.py
"""

import argparse
import asyncio
import csv
import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx
from benchmark_utils import compute_stats
from rich.console import Console
from rich.table import Table

ANALYZER_URL = os.getenv("ANALYZER_URL", "http://localhost:8080")
DATA_CSV = os.getenv(
    "DATASET_CSV", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.csv")
)
console = Console()


# ── dataset ──────────────────────────────────────────────────────────────────


def load_texts(path: str, limit: int | None) -> list[str]:
    """Load unique, non-trivial feedback_text rows from data.csv."""
    seen: set[str] = set()
    texts: list[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            t = (row.get("feedback_text") or "").strip()
            if len(t) <= 3:
                continue
            key = t.lower()
            if key in seen:  # exact-dup guard: real dups would just hit the dedup short-circuit
                continue
            seen.add(key)
            texts.append(t)
    if limit is not None:
        texts = texts[:limit]
    return texts


# ── /metrics scraping (Prometheus exposition) ────────────────────────────────


def scrape_metrics(url: str) -> dict:
    """Fetch and parse the analyzer /metrics endpoint into the counters we report on."""
    try:
        body = httpx.get(f"{url}/metrics", timeout=10.0).text
    except Exception as exc:
        console.print(f"[yellow]/metrics unavailable: {str(exc)[:80]}[/yellow]")
        return {}

    def _sum(metric: str) -> float:
        # Sum all label-series of a counter/histogram-sum line.
        total = 0.0
        for m in re.finditer(rf"^{re.escape(metric)}(?:{{[^}}]*}})?\s+([0-9eE.+-]+)$", body, re.M):
            try:
                total += float(m.group(1))
            except ValueError:
                pass
        return total

    # Per-stage histogram sum/count → mean seconds per stage.
    stage_sum: dict[str, float] = {}
    stage_cnt: dict[str, float] = {}
    for m in re.finditer(r'pipeline_stage_duration_seconds_(sum|count)\{stage="([^"]+)"\}\s+([0-9eE.+-]+)', body):
        kind, stage, val = m.group(1), m.group(2), float(m.group(3))
        (stage_sum if kind == "sum" else stage_cnt)[stage] = val

    return {
        "dedup_cache_hits": _sum("dedup_cache_hits_total"),
        "dedup_cache_misses": _sum("dedup_cache_misses_total"),
        "llm_calls": _sum("llm_calls_total"),
        "llm_calls_saved": _sum("llm_calls_saved_total"),
        "prompt_tokens": _sum("llm_prompt_tokens_total"),
        "completion_tokens": _sum("llm_completion_tokens_total"),
        "needs_review": _sum("needs_review_total"),
        "stage_sum": stage_sum,
        "stage_cnt": stage_cnt,
    }


def metrics_delta(before: dict, after: dict) -> dict:
    if not before or not after:
        return {}
    out = {}
    for k in (
        "dedup_cache_hits",
        "dedup_cache_misses",
        "llm_calls",
        "llm_calls_saved",
        "prompt_tokens",
        "completion_tokens",
        "needs_review",
    ):
        out[k] = round(after.get(k, 0) - before.get(k, 0), 2)
    # Per-stage mean latency over the window.
    stage_means = {}
    for stage, asum in after.get("stage_sum", {}).items():
        d_sum = asum - before.get("stage_sum", {}).get(stage, 0.0)
        d_cnt = after.get("stage_cnt", {}).get(stage, 0.0) - before.get("stage_cnt", {}).get(stage, 0.0)
        if d_cnt > 0:
            stage_means[stage] = round(d_sum / d_cnt * 1000, 1)  # ms
    out["stage_mean_ms"] = dict(sorted(stage_means.items(), key=lambda kv: -kv[1]))
    return out


# ── request driver ───────────────────────────────────────────────────────────


@dataclass
class Result:
    latency_ms: float
    status: int
    success: bool
    error: str = ""
    analysis: dict = field(default_factory=dict)


async def analyze_one(client, text, sem) -> Result:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{ANALYZER_URL}/analyze", json={"text": text}, timeout=300.0)
            lat = (time.perf_counter() - t0) * 1000
            body = r.json() if r.status_code == 200 else {}
            return Result(lat, r.status_code, r.status_code == 200, analysis=body)
        except Exception as exc:
            return Result((time.perf_counter() - t0) * 1000, 0, False, error=str(exc)[:100])


async def run_level(texts, concurrency, warmup) -> dict:
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency + 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        # Warm up on the first few items (discarded) so caches/JIT are hot.
        await asyncio.gather(*(analyze_one(client, texts[i % len(texts)], sem) for i in range(warmup)))

        t_wall = time.perf_counter()
        results = await asyncio.gather(*(analyze_one(client, t, sem) for t in texts))
        wall = time.perf_counter() - t_wall

    succ = [r for r in results if r.success]
    errs: dict[str, int] = {}
    for r in results:
        if not r.success:
            k = r.error or f"http_{r.status}"
            errs[k] = errs.get(k, 0) + 1

    return {
        "concurrency": concurrency,
        "num_items": len(texts),
        "successes": len(succ),
        "failures": len(results) - len(succ),
        "errors": errs,
        "wall_elapsed_s": round(wall, 2),
        "req_per_sec": round(len(succ) / wall, 4) if wall > 0 else 0.0,
        "latency_ms": compute_stats([r.latency_ms for r in succ]).__dict__,
        "_successes": succ,  # kept for distribution stats; stripped before JSON dump
    }


# ── score distributions (the research payload) ───────────────────────────────


def distributions(successes) -> dict:
    csi, cxi, conf, intens = [], [], [], []
    sentiment: dict[str, int] = {}
    category: dict[str, int] = {}
    escalate = churn = review = 0
    for r in successes:
        a = r.analysis
        exp = a.get("experience") or {}
        if exp.get("csi_percent") is not None:
            csi.append(exp["csi_percent"])
        if exp.get("cxi_percent") is not None:
            cxi.append(exp["cxi_percent"])
        if a.get("pipeline_confidence") is not None:
            conf.append(a["pipeline_confidence"])
        s = a.get("sentiment") or {}
        if s.get("intensity") is not None:
            intens.append(s["intensity"])
        sentiment[s.get("sentiment", "?")] = sentiment.get(s.get("sentiment", "?"), 0) + 1
        cat = (a.get("taxonomy") or {}).get("category", "?")
        category[cat] = category.get(cat, 0) + 1
        if (a.get("risk") or {}).get("escalate"):
            escalate += 1
        if (a.get("signals") or {}).get("churn_risk"):
            churn += 1
        if a.get("needs_review"):
            review += 1

    def stat(vals):
        return compute_stats(vals).__dict__ if vals else None

    n = len(successes) or 1
    return {
        "csi_percent": stat(csi),
        "cxi_percent": stat(cxi),
        "pipeline_confidence": stat(conf),
        "intensity_1_10": stat(intens),
        "sentiment_distribution": dict(sorted(sentiment.items(), key=lambda kv: -kv[1])),
        "category_distribution": dict(sorted(category.items(), key=lambda kv: -kv[1])),
        "escalation_rate_pct": round(escalate / n * 100, 1),
        "churn_rate_pct": round(churn / n * 100, 1),
        "needs_review_count": review,
    }


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(description="Benchmark the full pipeline over the real dataset.")
    p.add_argument("--concurrency", type=int, nargs="+", default=[2], help="concurrency levels (default: 2)")
    p.add_argument("--limit", type=int, default=None, help="max items (default: all unique rows)")
    p.add_argument("--warmup", type=int, default=3, help="warm-up items discarded before timing (default: 3)")
    p.add_argument("--out", default="results_dataset.json", help="output JSON (default: results_dataset.json)")
    args = p.parse_args()

    texts = load_texts(DATA_CSV, args.limit)
    console.print(f"[bold cyan]Loaded {len(texts)} unique feedback items from {DATA_CSV}[/bold cyan]")
    console.print(f"Target: {ANALYZER_URL}/analyze   concurrency={args.concurrency}   warmup={args.warmup}")
    console.print("[dim]Each item = 7 LLM stages end-to-end. This will take a while.[/dim]\n")

    all_levels = []
    dist = None
    for c in args.concurrency:
        console.print(f"[cyan]Running concurrency={c} over {len(texts)} items...[/cyan]")
        before = scrape_metrics(ANALYZER_URL)
        level = asyncio.run(run_level(texts, c, args.warmup))
        after = scrape_metrics(ANALYZER_URL)

        succ = level.pop("_successes")
        level["pipeline_metrics"] = metrics_delta(before, after)
        toks = level["pipeline_metrics"].get("completion_tokens", 0) or 0
        level["completion_tokens_per_sec"] = (
            round(toks / level["wall_elapsed_s"], 1) if level["wall_elapsed_s"] else 0.0
        )
        all_levels.append(level)
        if dist is None:  # distributions are corpus properties — compute once (first level)
            dist = distributions(succ)

        lat = level["latency_ms"]
        console.print(
            f"  p50={lat['p50']:.0f}ms p95={lat['p95']:.0f}ms p99={lat['p99']:.0f}ms "
            f"req/s={level['req_per_sec']:.3f} ok={level['successes']} fail={level['failures']} "
            f"dedup_hits={level['pipeline_metrics'].get('dedup_cache_hits', 0):.0f}"
        )

    # ── tables ──
    t = Table(title="Pipeline E2E over real dataset", show_lines=True)
    for col in ("Conc.", "Items", "Req/s", "tok/s", "p50 ms", "p95 ms", "p99 ms", "max ms", "Fail"):
        t.add_column(col, justify="right")
    for r in all_levels:
        lat = r["latency_ms"]
        t.add_row(
            str(r["concurrency"]),
            str(r["num_items"]),
            f"{r['req_per_sec']:.3f}",
            f"{r['completion_tokens_per_sec']:.0f}",
            f"{lat['p50']:.0f}",
            f"{lat['p95']:.0f}",
            f"{lat['p99']:.0f}",
            f"{lat['max']:.0f}",
            str(r["failures"]),
        )
    console.print()
    console.print(t)

    stages = all_levels[0]["pipeline_metrics"].get("stage_mean_ms", {})
    if stages:
        st = Table(title="Per-stage mean latency (ms)", show_lines=False)
        st.add_column("Stage")
        st.add_column("Mean ms", justify="right")
        for stage, ms in stages.items():
            st.add_row(stage, f"{ms:.1f}")
        console.print()
        console.print(st)

    if dist:
        console.print("\n[bold]Score distributions over corpus:[/bold]")
        for key in ("csi_percent", "cxi_percent", "pipeline_confidence", "intensity_1_10"):
            s = dist[key]
            if s:
                console.print(
                    f"  {key:22s} mean={s['mean']:.1f} p50={s['p50']:.1f} "
                    f"p95={s['p95']:.1f} max={s['max']:.1f} (n={s['count']})"
                )
        console.print(f"  sentiment   {dist['sentiment_distribution']}")
        console.print(f"  category    {dist['category_distribution']}")
        console.print(
            f"  escalation_rate={dist['escalation_rate_pct']}%  churn_rate={dist['churn_rate_pct']}%  "
            f"needs_review={dist['needs_review_count']}"
        )

    payload = {"target": ANALYZER_URL, "num_items": len(texts), "levels": all_levels, "distributions": dist}
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
    console.print(f"\n[green]Full results written to {args.out}[/green]")


if __name__ == "__main__":
    main()
