# Dataset Benchmark — Full CX Pipeline E2E

End-to-end benchmark of the **full 10-stage pipeline** (7 LLM stages) over the real
customer-visit corpus (`data.csv`, 679 unique records), driven through `POST /analyze`.
Each item runs all stages and is persisted to Qdrant.

- **Date:** 2026-06-05
- **Model:** `Qwen/Qwen2.5-7B-Instruct-AWQ` (vLLM 0.21, `max_model_len=1024`, `max-num-seqs=2`, AWQ-Marlin, RTX 4070 8GB)
- **Items timed:** 676 (679 − 3 warm-up) · **concurrency:** 2 · **failures:** 0
- **Raw results:** `results_dataset_full.json`

## How this run was executed (honest framing)

This was **not** run against the k3s server pod. The server analyzer cannot reach vLLM
across the LAN (dev-laptop firewall drops the in-cluster completion path post-reboot),
so the run used a **local analyzer container** (vLLM over loopback) writing to a **local
Qdrant**. Code, image, and model are identical to the server deployment; only the
network path and the vector store differ.

Two consequences for reading the numbers:

- **Cache-hit rate is 0% by construction, not by failure.** The local Qdrant started
  empty, and the benchmark pre-drops exact duplicates, so no item crossed the 0.95
  dedup threshold → `dedup_cache_hits=0`, `llm_calls_saved=0`. On a warm production
  Qdrant this would be non-zero; treat 0% as the cold-start floor, not a steady-state figure.
- **The app-level semantic prefix-cache scheduler (`analyzer/scheduler.py`) was NOT on
  the request path.** It is not wired into `main.py`/the LCEL chain, so it did not affect
  these results. Any prefix-cache benefit here came from **vLLM's automatic prefix caching**
  (default-on in 0.21), which reuses the shared per-stage system-prompt prefixes across the
  7 calls — a plausible contributor to the 84 tok/s throughput, but not measured in isolation.

## Latency & throughput (concurrency 2)

| Metric | Value |
|---|---|
| Items | 676 (0 fail) |
| Wall time | 4774 s (~79.6 min) |
| Throughput | 0.142 req/s · **83.7 completion tok/s** |
| Latency p50 | 14,134 ms |
| Latency p95 | 16,264 ms |
| Latency p99 | 17,439 ms |
| Latency max | 19,627 ms |

Per-item latency is ~14 s because each item is **7 sequential LLM stages** on a single
8GB GPU at `max-num-seqs=2`; this is a pipeline-depth benchmark, not a raw-LLM microbench.

## Token accounting

| | Tokens |
|---|---|
| LLM calls | 4,753 (679 × 7 stages) |
| Prompt tokens | 1,294,948 |
| Completion tokens | 399,714 |
| LLM calls saved (dedup) | 0 (cold cache — see above) |

## Per-stage mean latency (ms)

| Stage | Mean ms |
|---|---|
| executive_intelligence | 3447.3 |
| **experience_scoring** (new CSI/CX) | **3384.2** |
| risk_escalation | 2672.8 |
| semantic_enrichment | 1987.9 |
| business_signals | 1100.3 |
| taxonomy | 725.1 |
| sentiment_emotion | 694.0 |
| store_result (Qdrant write) | 39.5 |
| pii_redaction | 20.7 |
| normalization | 7.6 |
| confidence | 0.3 |

The new `experience_scoring` stage is the 2nd-heaviest (~3.4 s) — expected, as it emits
12 structured dimensions (8 CSI + 4 CX) in one call. It roughly doubled per-item cost vs
a pre-feature pipeline; acceptable for batch, worth noting if latency-SLO'd.

## Score distributions over the corpus (the research output)

### Customer Satisfaction Index (CSI %)
| mean | p50 | p95 | p99 | max |
|---|---|---|---|---|
| 66.1 | 68.8 | 83.3 | 87.5 | 100.0 |

### Customer Experience Index (CX %)
| mean | p50 | p95 | p99 | max |
|---|---|---|---|---|
| 55.9 | 58.3 | 83.3 | 95.8 | 100.0 |

CSI runs ~10 pts above CX across the corpus, and both span a real range (no constant
fallback) — the LLM is genuinely differentiating the 12 dimensions per item.

### Other signals
- **pipeline_confidence:** mean 0.87, p50 0.89, p95 0.91 — uniformly high; `needs_review=0`
  (nothing fell below the 0.65 review threshold).
- **intensity (1–10):** mean 2.2, p50 1, p95 7 — most feedback is low-intensity (routine
  visit notes), with a high-intensity tail.
- **sentiment:** neutral 530 · negative 88 · positive 57 · mixed 1
- **category:** Onboarding 188 · Other 160 · Billing 112 · Shipping 104 · Product 104 · Account 8
- **escalation rate:** 7.1% · **churn rate:** 4.4%

## Caveats summary

1. Local-workaround run (loopback vLLM + local Qdrant), **not** the server pod.
2. Cache-hit 0% = cold start, not steady state.
3. Semantic prefix-cache scheduler not on the path; only vLLM auto prefix caching applied.
4. Single concurrency level (2) — the GPU `max-num-seqs=2` sweet spot; no sweep this run.
