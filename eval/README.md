# Model Evaluation

Answers the question the training scripts left open: **did fine-tuning actually help?**

`evaluate.py` runs a labelled eval set through one or more models using the same
structured-extraction prompt the SFT data was built from, parses the JSON, and scores
it against gold labels.

## Metrics
- `json_valid_rate` — fraction of responses that parsed as the expected JSON
- `category_accuracy` — `taxonomy.category` exact match
- `sentiment_accuracy` — `sentiment.sentiment` exact match
- `escalate_accuracy` — `risk.escalate` exact match
- `mean_latency_ms`

## Run

Compare base vs fine-tuned (point at two vLLM endpoints):

```bash
python eval/evaluate.py \
  --model base=http://localhost:8000/v1=Qwen/Qwen2.5-7B-Instruct \
  --model ft=http://localhost:8001/v1=cx-ft-awq \
  --out eval/results.json
```

With two models it prints the per-metric **Δ (ft − base)** so the improvement (or
regression) is explicit.

Single-model baseline:

```bash
python eval/evaluate.py --model base=http://localhost:8000/v1=Qwen/Qwen2.5-7B-Instruct-AWQ
```

## Baseline (Qwen2.5-7B-Instruct-AWQ, 16-item set)

| metric | value |
|---|---|
| json_valid_rate | 100% |
| category_accuracy | 87.5% |
| sentiment_accuracy | 100% |
| escalate_accuracy | **68.8%** |
| mean_latency_ms | ~3400 |

The escalation decision is the weakest dimension — which is precisely what the active
-learning review loop and DPO (training human escalation corrections) are meant to
improve. Re-run with `--model ft=...` after fine-tuning to quantify the lift.

The eval set (`data/cx_eval.jsonl`) is a small hand-labelled gold set across all six
categories; grow it for more reliable numbers.
