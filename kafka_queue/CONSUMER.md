# Consumer — Code Reference

## Overview

Reads feedback jobs from the `feedback.raw` Kafka topic, calls the FastAPI analyzer, and publishes results to `feedback.analyzed`.

```
feedback.raw → consumer → POST /analyze (FastAPI) → feedback.analyzed
```

---

## Functions

### `Config::from_env()`
Reads all configuration from environment variables with defaults.

| Variable | Default | Purpose |
|---|---|---|
| `KAFKA_BROKERS` | `localhost:9092` | Redpanda address |
| `KAFKA_RAW_TOPIC` | `feedback.raw` | Topic to read from |
| `KAFKA_ANALYZED_TOPIC` | `feedback.analyzed` | Topic to write results to |
| `ANALYZER_URL` | `http://localhost:8080/analyze` | FastAPI endpoint |
| `KAFKA_GROUP_ID` | `cx-analyzer-group` | Consumer group name |
| `MAX_CONCURRENT` | `4` | Max parallel analyses (semaphore size) |

---

### `main()`
Sets everything up and runs the infinite read loop.

1. Starts Prometheus metrics server on `:9002`
2. Reads config from env
3. Creates the Kafka consumer — subscribes to `feedback.raw`
4. Creates a Kafka producer — for publishing to `feedback.analyzed`
5. Creates an HTTP client — to call FastAPI
6. Creates a semaphore — caps concurrent jobs at `MAX_CONCURRENT`
7. Loops forever — for each message:
   - Deserializes JSON into `AnalysisJob`
   - Commits the offset (marks message as received)
   - Acquires a semaphore slot
   - Spawns a background task calling `process_job`

---

### `process_job()`
Does the actual work for each message. Called concurrently (up to `MAX_CONCURRENT` at a time).

1. Logs start, increments active jobs gauge
2. POSTs `{ "text": ... }` to FastAPI `/analyze`
3. Waits for the response
4. Decrements active jobs gauge
5. On success — wraps result in `AnalysisResult`, publishes to `feedback.analyzed`
6. On failure — logs the error, increments error counter

> Note: messages are committed before processing. A failed analysis is not retried — it is logged and dropped.

---

## Metrics (exposed on `:9002/metrics`)

| Metric | What it tracks |
|---|---|
| `consumer_messages_received_total` | Messages pulled from Kafka |
| `consumer_active_jobs` | Currently in-flight analyses |
| `consumer_available_workers` | Free semaphore slots |
| `consumer_analysis_duration_seconds` | How long each LLM call took |
| `consumer_analyses_completed_total` | Successful analyses |
| `consumer_analyzer_errors_total` | Failed HTTP / parse errors |
| `consumer_publish_errors_total` | Failed result publishes |
| `consumer_kafka_errors_total` | Kafka receive errors |
| `consumer_decode_errors_total` | Bad JSON messages |

---

## Concurrency model

```
Kafka message arrives
        ↓
commit offset (message safe, won't re-deliver)
        ↓
acquire semaphore slot (blocks if 4 already running)
        ↓
spawn tokio task → process_job()
        ↓
release slot when done
```

Max 4 analyses run in parallel. Adjust via `MAX_CONCURRENT` env var.
