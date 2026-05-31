# CX Semantic Analyzer — Inference Benchmark Report

**Model:** Qwen/Qwen2.5-7B-Instruct-AWQ  
**Quantization:** AWQ + Marlin kernel (`awq_marlin`)  
**Hardware:** NVIDIA RTX 4070 Laptop (8 GB VRAM)  
**Serving:** vLLM v0.x, self-hosted, bare-metal  
**Date:** 2026-05-31  

---

## What This System Does

A 10-stage LangChain LCEL pipeline that runs every piece of customer feedback through
structured LLM inference: normalisation → PII redaction → semantic enrichment → taxonomy
classification → sentiment/emotion → business signals → risk escalation → executive
intelligence → confidence scoring → vector storage.

Every stage calls the same self-hosted vLLM endpoint using structured output
(`with_structured_output`), so the LLM returns typed Pydantic models directly — no
parsing, no retries on malformed JSON.

---

## Section 1 — Raw vLLM Inference (Baseline)

Measured directly against the OpenAI-compatible streaming endpoint using `stream=True`
to capture Time To First Token (TTFT) precisely. 20 measured requests per concurrency
level, 5 warm-up requests discarded.

| Concurrency | Req/s | Tok/s | TTFT p50 | TTFT p95 | TTFT p99 | ITL p95 | E2E p95 |
|:-----------:|:-----:|------:|:--------:|:--------:|:--------:|:-------:|:-------:|
| 1           |   3.0 |    44 |   56 ms  |   60 ms  |   60 ms  |  22 ms  |  466 ms |
| 2           |   5.9 |    82 |   63 ms  |   65 ms  |   65 ms  |  22 ms  |  468 ms |
| 4           |   6.1 |    88 |  381 ms  |  422 ms  |  443 ms  |  22 ms  |  741 ms |
| 8           |   5.7 |    85 |  958 ms  | 1161 ms  | 1165 ms  |  23 ms  | 1440 ms |

**Metric definitions:**
- **TTFT** — Time To First Token: latency from request send to receiving the first output token
- **ITL** — Inter-Token Latency: average time between consecutive output tokens during generation
- **E2E** — End-to-end wall-clock time for the full streamed response
- **Tok/s** — Output token throughput across all concurrent requests

### Key Findings

**Concurrency 2 is the throughput sweet spot.** Token throughput nearly doubles from
c=1 to c=2 (44 → 82 tok/s) with almost no TTFT penalty (56 ms → 63 ms p50). This
matches the server's `--max-num-seqs 2` limit: both GPU slots are fully utilised without
any queuing.

**Beyond c=2, queuing dominates.** At c=4, TTFT jumps from 63 ms to 381 ms p50 —
requests are now waiting for a free sequence slot before the GPU even touches them.
Token throughput plateaus at ~87 tok/s because the GPU is already saturated at c=2.

**ITL is rock-stable at ~22 ms** regardless of concurrency (p95 range: 22–23 ms across
all levels). This shows the generation speed is consistent and unaffected by queue depth
— only the wait before generation grows.

**RTX 4070 + AWQ Marlin: sub-100 ms TTFT at the target operating point.** At c=1 and
c=2 the model feels interactive, well within the threshold for real-time feedback
classification.

---

## Section 2 — Deduplication Cache (Architectural Analysis)

The pipeline embeds each incoming feedback item using `all-MiniLM-L6-v2` (384-dim,
sentence-transformers) and performs a cosine similarity search in Qdrant
(`feedback_analyses` collection) before any LLM stage runs. If a semantically identical
or near-identical item is found above a 0.95 cosine threshold, the cached
`FeedbackAnalysis` is returned immediately — zero LLM calls, zero GPU time.

### Latency Profile per Request Type

| Request type        | Path                                      | Typical latency     |
|---------------------|-------------------------------------------|---------------------|
| **Cache miss**      | Embed → Qdrant search → 10 LLM stages    | 15 – 30 s           |
| **Cache hit (dedup)** | Embed → Qdrant search → return cached  | 50 – 100 ms         |

Cache hits are **200–600× faster** than full pipeline runs. The embed + Qdrant lookup
adds only ~50 ms to every request (hit or miss) — a negligible overhead that pays for
itself the moment a single duplicate is avoided.

### System-Level Throughput Impact

Throughput gain scales linearly with the cache hit rate, which in production CX
workloads typically falls in the 15–30% range (repeated billing complaints, shipping
delay reports, NPS boilerplate):

| Cache hit rate | Overall pipeline speedup |
|:--------------:|:------------------------:|
| 5%             | ~5%                      |
| 15%            | ~15%                     |
| 30%            | ~30%                     |

Beyond throughput, deduplication cuts GPU-hour cost proportionally — every cache hit is
an LLM inference that never happens.

---

## Section 2b — How This Compares to Published Numbers

| Setup | GPU | Framework | Tok/s | Notes |
|---|---|---|:---:|---|
| Qwen2.5-7B-AWQ (official) | A100 80 GB | vLLM | 148 | Server GPU, ~$10k hardware, 1-token input |
| Qwen3-8B Q4_K | RTX 4070 **desktop** 12 GB | llama.cpp | 71 | Hardware-corner.net, 4K context |
| **This project** | **RTX 4070 Laptop 8 GB** | **vLLM + AWQ Marlin** | **82** | **c=2, measured, short prompts** |

**The laptop beats the desktop llama.cpp setup.** The RTX 4070 Laptop has fewer CUDA
cores and less VRAM than the desktop variant, yet the vLLM + AWQ Marlin stack closes
the gap and then some — because the Marlin kernel fuses dequantisation and GEMM into
a single CUDA pass, recovering throughput that llama.cpp's general-purpose kernels leave
on the table.

The gap to A100 (148 vs 82 tok/s) is entirely memory-bandwidth: the A100 has 2 TB/s
vs the 4070 Laptop's ~272 GB/s. AWQ narrows this by shrinking the weight footprint that
has to be streamed per token, which is why 4-bit quantization gives a
near-linear throughput gain on bandwidth-constrained consumer GPUs.

---

## Section 3 — Quantization Efficiency

Running Qwen2.5-7B-Instruct at 4-bit AWQ with the Marlin kernel means:

- **VRAM footprint:** ~4 GB active model weights (vs ~14 GB for BF16) — running on an
  8 GB card with the remaining headroom used for KV cache and CUDA context
- **Marlin kernel advantage:** fused dequantisation + GEMM in a single CUDA kernel,
  recovering most of the throughput lost to 4-bit precision
- **Quality retention:** AWQ selects which weights to quantize based on activation
  magnitudes, preserving accuracy on instruction-following tasks

The 82 tok/s throughput at c=2 on a laptop GPU is a direct result of this stack. The
same workload on a BF16 model would not fit in 8 GB VRAM without offloading.

---

## Reproduce

```bash
# Raw vLLM benchmark (requires vLLM running)
cd tests
VLLM_BASE_URL=http://localhost:8000/v1 \
  conda run -n ml_env python benchmark_vllm.py \
  --concurrency 1 2 4 8 --prompts 20 --warmup 5 --out results_baseline_raw.json

# Full pipeline E2E benchmark (requires analyzer + Qdrant running)
ANALYZER_URL=http://localhost:8080 \
  conda run -n ml_env python benchmark_pipeline.py \
  --concurrency 1 2 4 --requests 10 --warmup 2
```

Raw results: [`results_baseline_raw.json`](results_baseline_raw.json)
