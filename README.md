# VOC Sentiment Analyzer

A production-grade **Voice of Customer (VOC) semantic analysis pipeline** that processes raw customer feedback through a 10-stage NLP pipeline powered by a self-hosted LLM, deployed on Kubernetes.

> Built as a full-stack ML systems project — from GPU inference to Rust microservices to a live React dashboard.

---

## What It Does

Paste any customer feedback → get back structured intelligence:

- **Sentiment & intensity score** (1–10)
- **Category taxonomy** (Billing / Product / Support / Shipping + subcategory)
- **Risk level** (low / medium / high / critical) with escalation flag
- **Churn risk & upsell opportunity** detection
- **PII redaction** before any LLM sees the text
- **Feature request & bug report extraction**
- **Executive summary** with action items and health score

---

## Architecture

```
Customer Feedback
       │
       ▼
┌──────────────────────────────────────────────┐
│  Rust / Axum HTTP Gateway  (port 3001)        │
│  POST /feedback  →  Kafka topic: feedback.raw │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
          ┌────────────────┐
          │   Redpanda     │  (Kafka-compatible broker)
          └────────┬───────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  Rust Consumer  →  Python FastAPI Analyzer   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│           10-Stage LangChain Pipeline         │
│                                               │
│  deduplication → normalization → pii_redact   │
│  → semantic_enrichment (RAG) → taxonomy       │
│  → sentiment_emotion → business_signals       │
│  → risk_escalation → executive_intelligence   │
│  → store_result                               │
└──────────────────┬───────────────────────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
    Qdrant Vector DB    vLLM Server
    (dedup + RAG)    Qwen2.5-7B-AWQ
                     RTX 4070 (8GB)
```

### Deployment Topology

| Machine | Role |
|---|---|
| Dev laptop (RTX 4070) | vLLM bare-metal inference — `0.0.0.0:8000` |
| Server laptop (k3s) | Everything else — Redpanda, Qdrant, analyzer, dashboard, Prometheus, Grafana |

vLLM runs off-cluster; a headless Kubernetes `Service + Endpoints` object routes in-cluster DNS (`http://vllm:8000`) to the GPU machine over LAN.

---

## Stack

| Layer | Technology |
|---|---|
| LLM inference | [vLLM](https://github.com/vllm-project/vllm) · Qwen2.5-7B-Instruct-AWQ · AWQ quantization |
| Pipeline | Python · LangChain LCEL · Pydantic structured outputs |
| Vector DB | Qdrant (deduplication + RAG) · `all-MiniLM-L6-v2` embeddings |
| Message broker | Redpanda (Kafka-compatible) |
| Ingestion gateway | Rust · Axum · `rdkafka` |
| API | FastAPI |
| Dashboard | Next.js 14 · Tailwind CSS · SWR |
| Kubernetes | k3s · flannel CNI · kube-router network policies |
| Monitoring | Prometheus · Grafana |

---

## Pipeline Stages

Each stage is a `RunnableLambda` chained with LangChain's `|` operator. Every LLM stage uses `.with_structured_output(PydanticModel)` — no string parsing, typed outputs only.

| Stage | Type | What it does |
|---|---|---|
| `deduplication` | Rule-based | Cosine similarity search in Qdrant — returns cached result if duplicate |
| `normalization` | Rule-based | Strips HTML, fixes encoding, detects language |
| `pii_redaction` | Rule-based | Regex + spaCy NER — removes emails, phones, names before LLM sees text |
| `semantic_enrichment` | LLM + RAG | Summary, topics, entities — augmented with similar past feedback |
| `taxonomy` | LLM | Category, subcategory, confidence score |
| `sentiment_emotion` | LLM | Sentiment, emotions list, intensity 1–10 |
| `business_signals` | LLM | Churn risk, upsell opportunity, feature requests, competitor mentions |
| `risk_escalation` | LLM | Escalate flag, risk level, suggested action |
| `executive_intelligence` | LLM | Executive summary, action items, health score 1–10 |
| `store_result` | Rule-based | Saves to Qdrant only if full pipeline succeeds |

---

## Key Engineering Decisions

**GPU memory constraint** — RTX 4070 has 8GB VRAM with ~1.1GB consumed by the display. `--gpu-memory-utilization 0.82` and AWQ quantization fit Qwen2.5-7B within the remaining headroom. `--max-num-seqs 2` caps concurrency to prevent OOM.

**PII before LLM** — `pii_redaction` runs before any LLM stage. The model never sees raw email addresses, phone numbers, or named entities that spaCy identifies as persons.

**Deduplication short-circuit** — if Qdrant finds a past result above 0.95 cosine similarity, the pipeline returns immediately without any LLM calls.

**Offset commit bug (known)** — the Kafka consumer commits offsets before processing. A crashed analyzer silently drops the message. Tracked in `kafka_queue/src/bin/consumer.rs:128`. Fix: commit after publish to `feedback.analyzed`, add dead-letter topic.

---

## Running It

### Prerequisites
- Dev laptop with NVIDIA GPU (8GB+ VRAM)
- Server with k3s installed
- Both on the same LAN

### 1. Start vLLM (dev laptop)
```bash
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --host 0.0.0.0 --port 8000 \
  --dtype half --max-model-len 1024 \
  --gpu-memory-utilization 0.82 \
  --quantization awq \
  --max-num-seqs 2 \
  --enforce-eager
```

### 2. Deploy to k3s (server)
```bash
# Build and import custom images
docker build -t semantic-analyzer-dev .
docker build --network=host -t cx-gateway kafka_queue/
docker tag cx-gateway cx-producer && docker tag cx-gateway cx-consumer
docker build -t cx-dashboard dashboard/

for img in semantic-analyzer-dev cx-producer cx-consumer cx-dashboard; do
  docker save $img | sudo k3s ctr images import -
done

# Deploy
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/vllm/ k8s/qdrant/ k8s/redpanda/ k8s/analyzer/ \
              k8s/producer/ k8s/consumer/ k8s/dashboard/ k8s/monitoring/
```

### 3. Verify
```bash
kubectl -n cx-pipeline get pods
kubectl -n cx-pipeline exec deploy/analyzer -- curl -s http://vllm:8000/health
```

### 4. Run the pipeline
```bash
# Single item
python -m analyzer.main --text "Your product broke and I want a refund"

# Batch from CSV
python run_pipeline.py --source csv --file tests/dummy_data/reviews.csv --text-col text --out results.json
```

---

## Tests
```bash
# Mocked — no vLLM needed
python -m pytest tests/test_pipeline.py -v

# Live — requires vLLM running
python -m pytest tests/test_pipeline.py -v -m live
```

---

## Known Issues / Tech Debt

See `CLAUDE.md` for full architecture notes. Short version:

- Consumer commits Kafka offsets before processing (silent drop on crash)
- No authentication on any endpoint (intentional MVP scope)
- `unix_now()` returns `String` instead of `i64` epoch millis
- Trend aggregation is batch-after-the-fact, not streaming

---

## Project Structure

```
├── analyzer/           # Python LangChain pipeline + FastAPI
│   ├── pipeline/       # 10 stage modules
│   ├── schemas.py      # Pydantic output models
│   └── api.py          # FastAPI endpoints
├── kafka_queue/        # Rust producer + consumer binaries
│   └── src/bin/        # producer.rs, consumer.rs
├── ingestion/          # Pluggable source adapters (CSV, NPS, Typeform, Google Forms)
├── vectordb/           # Qdrant client, embedder, few-shot seeds
├── dashboard/          # Next.js 14 frontend
│   ├── app/analyze/    # Live feedback input page
│   └── app/outputs/    # Analytics dashboard
├── k8s/                # Kubernetes manifests
│   ├── vllm/           # Headless service + endpoints (bare-metal GPU routing)
│   ├── redpanda/       # Kafka broker StatefulSet
│   └── monitoring/     # Prometheus + Grafana
└── monitoring/         # Prometheus config + Grafana dashboards
```
