# Startup Guide

## 1. Start Infrastructure (Qdrant + Dev Container)

```bash
docker-compose up -d qdrant
docker-compose up dev
```

---

## 2. Inside the Dev Container (open a new terminal)

```bash
docker exec -it analyzer-dev bash
```

### Start vLLM (GPU — required for analyzing new feedback)

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --host 0.0.0.0 --port 8000 \
  --dtype half --max-model-len 1024 \
  --gpu-memory-utilization 0.82 \
  --quantization awq_marlin \
  --max-num-seqs 2 \
  --enforce-eager
```

Wait for: `Application startup complete.`

### Start FastAPI (open another terminal tab)

```bash
docker exec -d -e QDRANT_URL=http://qdrant:6333 analyzer-dev \
  uvicorn analyzer.api:app --host 0.0.0.0 --port 8080
```

Verify: `curl http://localhost:8080/health`

---

## 3. Start Dashboard (host machine)

```bash
cd /home/vinesh/Documents/Summer2026/dashboard && npm run dev
```

Open: http://localhost:3000/outputs

---

## 4. Run Pipeline on New Feedback

```bash
# CSV
docker exec -it analyzer-dev python run_pipeline.py \
  --source csv --file tests/dummy_data/clothing_reviews.csv \
  --text-col text --out results.json

# Single item
docker exec -it analyzer-dev python -m analyzer.main \
  --text "Your feedback text here"
```

---

## 5. Import Existing Results into Qdrant

```bash
docker exec -e QDRANT_URL=http://qdrant:6333 analyzer-dev \
  python import_results.py results.json
```

---

## 6. Shutdown

```bash
# Stop FastAPI and vLLM inside container
docker exec analyzer-dev pkill -f uvicorn
docker exec analyzer-dev pkill -f vllm

# Stop containers
docker-compose down
```

---

## Quick Reference

| Service     | URL                          |
|-------------|------------------------------|
| vLLM        | http://localhost:8000        |
| FastAPI     | http://localhost:8080        |
| Dashboard   | http://localhost:3000 (host dev) / http://localhost:3000 (Docker) |
| Qdrant UI   | http://localhost:6333/dashboard |
